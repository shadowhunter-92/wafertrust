"""AgentBridge-powered governance gateway for fab equipment agents.

This is the wedge: a neutral trust layer sitting between an AI agent and the
SECS/GEM equipment boundary. It reuses AgentBridge's real trust kernel —
Ed25519 identity, declarative policy, wafer-dollar budgets, human approvals,
and a hash-chained tamper-evident audit log — and adds fab semantics:

  * read tools pass through (the "flight recorder" still audits them)
  * write tools are approval-gated and risk-budgeted in wafer-dollars
  * a per-call blast-radius cap denies actions that risk too much at once

Governance is the actual AgentBridge GovernanceGateway, not a reimplementation.

Caller authentication is fail-closed: the gateway runs the kernel in production
admission mode (AGENTBRIDGE_ENV=production), so every call must carry a
request-bound Ed25519 proof over the exact tool, arguments, and operation ID.
Unsigned, forged, or mismatched calls are denied by the kernel itself. This
mode requires a durable store, so identity, budgets, approvals, the operation
ledger, and the audit chain share one SQLite database.

Setting AGENTBRIDGE_ENV is a process-wide side effect: this module is a
single-process demo, not a library to embed in a mixed-mode server.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

# Make the cloned AgentBridge importable (src.governance.*).
_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENTBRIDGE = os.path.join(os.path.dirname(_HERE), "agentbridge")
if _AGENTBRIDGE not in sys.path:
    sys.path.insert(0, _AGENTBRIDGE)

from src.governance import (  # noqa: E402
    AgentIdentity, IdentityRegistry, BudgetManager, Budget,
    ApprovalQueue, PolicyEngine, PolicySet,
    MaxCostPerCall, RequireApprovalAboveCost, AllowOnlyCapabilities,
    GovernanceGateway, GovernanceError,
    AuditLog, SqliteStore, canonical_payload,
)

READ_TOOLS = [
    "get_equipment_status", "list_status_variables", "get_status_variable",
    "list_alarms", "list_equipment_constants", "get_security_status",
]
WRITE_TOOLS = [
    "set_equipment_constant", "execute_command", "manage_process_job", "manage_carrier",
]
ALL_TOOLS = READ_TOOLS + WRITE_TOOLS

# Wafer-dollars-at-risk per call (blast radius). Reads risk nothing.
TOOL_COSTS = {
    "get_equipment_status": 0, "list_status_variables": 0, "get_status_variable": 0,
    "list_alarms": 0, "list_equipment_constants": 0, "get_security_status": 0,
    "set_equipment_constant": 500_000,   # chamber setpoint change affects active lots
    "execute_command": 500_000,          # ABORT/START scraps or moves a lot
    "manage_process_job": 500_000,
    "manage_carrier": 50_000,
}


class FabGovernanceGateway:
    def __init__(self, equipment, *, agent_id="fab-maintenance-agent",
                 budget_limit=600_000, approval_threshold=100_000, max_cost=750_000,
                 read_tools=None, write_tools=None, tool_costs=None, db_path=None):
        self.equipment = equipment
        self.agent_id = agent_id
        self.read_tools = READ_TOOLS if read_tools is None else read_tools
        self.write_tools = WRITE_TOOLS if write_tools is None else write_tools
        self.tool_costs = TOOL_COSTS if tool_costs is None else tool_costs
        all_tools = self.read_tools + self.write_tools

        # Fail-closed admission: the kernel demands a request-bound signed proof
        # and a durable operation_id on every call, and enforces an operator-owned
        # capability allowlist. Merge per agent so several gateways can coexist
        # in one demo process.
        os.environ["AGENTBRIDGE_ENV"] = "production"
        allowlist = json.loads(os.environ.get("AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON", "{}"))
        allowlist[agent_id] = sorted(set(allowlist.get(agent_id, [])) | set(all_tools))
        os.environ["AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON"] = json.dumps(allowlist)

        self.store = SqliteStore(db_path or os.path.join(_HERE, "wafertrust-governance.sqlite3"))

        # The agent keeps its private key; the registry only ever sees the public half.
        self.identity = AgentIdentity.generate(agent_id)
        self.identities = IdentityRegistry(self.store)
        self.identities.register(self.identity)
        # Separate custodian key: checkpoints are the operator's statement about
        # the log head, not another caller signature.
        self.operator = AgentIdentity.generate(agent_id + ":operator")

        self.budgets = BudgetManager(self.store)
        self.budgets.set_budget(agent_id, Budget(spend_limit=budget_limit, rate_limit=1000))

        self.approvals = ApprovalQueue(self.store)
        for tool in self.write_tools:
            self.approvals.mark_sensitive(tool)

        policy_set = PolicySet([
            AllowOnlyCapabilities(all_tools),
            RequireApprovalAboveCost(approval_threshold),
            MaxCostPerCall(max_cost),
        ])
        self.policy = PolicyEngine(self.identities, self.budgets, approvals=self.approvals,
                                   require_verified=True, policy_set=policy_set)
        self.gw = GovernanceGateway(identities=self.identities, budgets=self.budgets,
                                    approvals=self.approvals, policy=self.policy,
                                    audit=AuditLog(self.store), require_verified=True)
        self.journal: list[dict] = []

    def tool_cost(self, tool: str) -> float:
        return self.tool_costs.get(tool, 1)

    async def _invoke(self, dst_wire: dict) -> dict:
        params = dst_wire["params"]
        return self.equipment.dispatch(params["name"], params.get("arguments", {}))

    async def governed_call(self, tool: str, arguments: dict, cost: float | None = None,
                            operation_id: str | None = None) -> dict:
        cost = self.tool_cost(tool) if cost is None else cost
        wire = {"jsonrpc": "2.0", "id": f"{tool}", "method": "tools/call",
                "params": {"name": tool, "arguments": arguments}}
        # An approved retry must reuse the blocked call's operation_id: approval
        # grants are scoped to the exact request, including this ID.
        operation_id = operation_id or uuid.uuid4().hex
        body = json.dumps({"src": "mcp", "dst": "mcp", "wire": wire,
                           "target_id": None, "operation_id": operation_id},
                          sort_keys=True, separators=(",", ":")).encode()
        nonce = uuid.uuid4().hex
        signed_data = canonical_payload(self.agent_id, nonce, body)
        signature = self.identity.sign(signed_data)
        try:
            result = await self.gw.route_call(
                agent_id=self.agent_id, src_proto="mcp", dst_proto="mcp",
                src_wire=wire, invoke=self._invoke, cost=cost,
                operation_id=operation_id, signed_body=body, signed_nonce=nonce,
                signed_data=signed_data, signature=signature)
            outcome = {"allowed": True, "result": result, "cost": cost,
                       "operation_id": operation_id}
        except GovernanceError as exc:
            outcome = {"allowed": False, "reason": str(exc),
                       "needs_approval": exc.decision.needs_approval,
                       "approval_id": exc.approval_id, "cost": cost,
                       "operation_id": operation_id}
        head = self.store.load_audit_head()
        self.journal.append({
            "operation_id": operation_id, "wire": wire, "cost": cost,
            "allowed": outcome["allowed"], "reason": outcome.get("reason"),
            "result": outcome.get("result"),
            "seq": head["seq"] if head else None,
            "entry_hash": head["entry_hash"] if head else None,
        })
        return outcome

    def export_flight_recorder(self, out_dir: str, stem: str) -> dict:
        """Write the complete flight recorder: full-field audit JSONL, an
        Ed25519-signed checkpoint over the chain head, and the call journal
        (exact arguments + outcomes bound to audit entry hashes)."""
        audit = self.gw.audit
        paths = {
            "jsonl": os.path.join(out_dir, f"{stem}-flight-recorder.jsonl"),
            "checkpoint": os.path.join(out_dir, f"{stem}-checkpoint.json"),
            "journal": os.path.join(out_dir, f"{stem}-call-journal.jsonl"),
        }
        with open(paths["jsonl"], "w", encoding="utf-8") as fh:
            fh.write(audit.export_jsonl() + "\n")
        checkpoint = audit.checkpoint(self.operator.sign, self.operator.public_key_hex)
        with open(paths["checkpoint"], "w", encoding="utf-8") as fh:
            json.dump(checkpoint, fh, indent=2)
            fh.write("\n")
        with open(paths["journal"], "w", encoding="utf-8") as fh:
            for rec in self.journal:
                fh.write(json.dumps(rec, default=str) + "\n")
        return paths

    # --- operator helpers ---
    def pending(self):
        return self.approvals.pending()

    def approve(self, approval_id: str) -> bool:
        return self.approvals.approve(approval_id)

    def budget(self):
        return self.budgets.get(self.agent_id)

    def audit_entries(self):
        return self.gw.audit.entries()

    def verify_integrity(self) -> bool:
        return self.gw.audit.verify_integrity()