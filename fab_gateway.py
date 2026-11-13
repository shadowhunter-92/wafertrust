"""AgentBridge-powered governance gateway for fab equipment agents.

This is the wedge: a neutral trust layer sitting between an AI agent and the
SECS/GEM equipment boundary. It reuses AgentBridge's real trust kernel —
Ed25519 identity, declarative policy, wafer-dollar budgets, human approvals,
and a hash-chained tamper-evident audit log — and adds fab semantics:

  * read tools pass through (the "flight recorder" still audits them)
  * write tools are approval-gated and risk-budgeted in wafer-dollars
  * a per-call blast-radius cap denies actions that risk too much at once

Governance is the actual AgentBridge GovernanceGateway, not a reimplementation.
"""

from __future__ import annotations

import os
import sys

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
                 read_tools=None, write_tools=None, tool_costs=None):
        self.equipment = equipment
        self.agent_id = agent_id
        self.read_tools = READ_TOOLS if read_tools is None else read_tools
        self.write_tools = WRITE_TOOLS if write_tools is None else write_tools
        self.tool_costs = TOOL_COSTS if tool_costs is None else tool_costs
        all_tools = self.read_tools + self.write_tools

        self.identities = IdentityRegistry()
        self.identities.register(AgentIdentity.generate(agent_id))

        self.budgets = BudgetManager()
        self.budgets.set_budget(agent_id, Budget(spend_limit=budget_limit, rate_limit=1000))

        self.approvals = ApprovalQueue()
        for tool in self.write_tools:
            self.approvals.mark_sensitive(tool)

        policy_set = PolicySet([
            AllowOnlyCapabilities(all_tools),
            RequireApprovalAboveCost(approval_threshold),
            MaxCostPerCall(max_cost),
        ])
        self.policy = PolicyEngine(self.identities, self.budgets, approvals=self.approvals,
                                   require_verified=False, policy_set=policy_set)
        self.gw = GovernanceGateway(identities=self.identities, budgets=self.budgets,
                                    approvals=self.approvals, policy=self.policy,
                                    require_verified=False)

    def tool_cost(self, tool: str) -> float:
        return self.tool_costs.get(tool, 1)

    async def _invoke(self, dst_wire: dict) -> dict:
        params = dst_wire["params"]
        return self.equipment.dispatch(params["name"], params.get("arguments", {}))

    async def governed_call(self, tool: str, arguments: dict, cost: float | None = None) -> dict:
        cost = self.tool_cost(tool) if cost is None else cost
        wire = {"jsonrpc": "2.0", "id": f"{tool}", "method": "tools/call",
                "params": {"name": tool, "arguments": arguments}}
        try:
            result = await self.gw.route_call(
                agent_id=self.agent_id, src_proto="mcp", dst_proto="mcp",
                src_wire=wire, invoke=self._invoke, cost=cost)
            return {"allowed": True, "result": result, "cost": cost}
        except GovernanceError as exc:
            return {"allowed": False, "reason": str(exc),
                    "needs_approval": exc.decision.needs_approval,
                    "approval_id": exc.approval_id, "cost": cost}

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