"""The 60-second story: why a fab needs a trust layer for its agents.

Run with the project venv:
    ../.venv/Scripts/python.exe demo.py

Scene 1 shows an UNGOVERNED agent scrapping a $500k lot with one unlogged
command. Scenes 2-7 show the SAME equipment behind AgentBridge: every call
carries a request-bound Ed25519 proof (unsigned or forged calls are denied
fail-closed), reads pass through and are audited, writes are approval-gated and
wafer-budgeted, and the complete flight recorder exports with a signed
checkpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

from equipment import SecsGemEquipment, ACTIVE_LOT_WAFERS, WAFER_VALUE_USD
from fab_gateway import (
    FabGovernanceGateway, AgentIdentity, AuditLog, GovernanceError, canonical_payload,
)
import anchor

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "secsgem-governance.sqlite3")


def hr(title=""):
    print("\n" + "=" * 72)
    if title:
        print(title)
        print("=" * 72)


def show(tag, outcome):
    if outcome["allowed"]:
        print(f"  [{tag}] ALLOWED  cost=${outcome['cost']:,.0f}  -> {outcome['result']}")
    else:
        print(f"  [{tag}] BLOCKED  {outcome['reason']}")
        if outcome.get("approval_id"):
            print(f"           pending human approval: {outcome['approval_id']}")


async def main():
    hr("SCENE 1 — UNGOVERNED: an agent changes a setpoint directly")
    eq_raw = SecsGemEquipment()
    print("  Agent calls set_equipment_constant(2001, 500) with NO identity,")
    print("  NO approval, NO budget, NO audit. The equipment's own E191 report")
    print(f"  says agentAudit = '{eq_raw.get_security_status()['agentAudit']}'.")
    res = eq_raw.set_equipment_constant(2001, 500)
    print(f"  Result: {res}")
    print(f"  >> {eq_raw.scrapped_wafers} wafers scrapped, ${eq_raw.damage_usd:,.0f} lost,")
    print("     and NO tamper-evident record of who did it or why.")

    hr("SCENE 2 — GOVERNED: read-only flight recorder (pass-through + audit)")
    eq = SecsGemEquipment()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)  # fresh governance state per run; the exports are the evidence
    gw = FabGovernanceGateway(eq, budget_limit=600_000, approval_threshold=100_000,
                              max_cost=750_000, db_path=DB_PATH)
    print(f"  Agent identity registered: {gw.agent_id} (Ed25519 DID)")
    print("  Every call must carry a request-bound Ed25519 proof; the kernel")
    print("  denies unsigned or forged calls fail-closed (production admission).")
    print(f"  Wafer-dollar budget: ${gw.budget().spend_limit:,.0f}/shift; "
          f"approval above $100k risk; per-call cap $750k")
    show("read", await gw.governed_call("get_equipment_status", {}))
    show("read", await gw.governed_call("list_alarms", {"active_only": True}))

    hr("SCENE 3 — GOVERNED: a write is BLOCKED pending human approval")
    out = await gw.governed_call("set_equipment_constant", {"ecid": 2001, "value": 400})
    show("write", out)
    approval_id = out.get("approval_id")

    hr("SCENE 4 — Human approves; the write executes within budget")
    if approval_id:
        print(f"  Operator approves {approval_id}: {gw.approve(approval_id)}")
    out = await gw.governed_call("set_equipment_constant", {"ecid": 2001, "value": 400},
                                 operation_id=out["operation_id"])
    show("write", out)
    b = gw.budget()
    print(f"  Budget spent ${b.spent:,.0f} / ${b.spend_limit:,.0f}; remaining ${b.remaining():,.0f}")

    hr("SCENE 5 — Wafer-dollar circuit breaker: budget exhausted")
    out = await gw.governed_call("execute_command", {"command": "ABORT"})
    show("write", out)
    if out.get("approval_id"):
        gw.approve(out["approval_id"])
    out = await gw.governed_call("execute_command", {"command": "ABORT"},
                                 operation_id=out["operation_id"])
    show("write", out)
    print("  >> Even with approval, the action is denied: it would risk more")
    print("     wafer-dollars than the shift budget allows.")

    hr("SCENE 6 — IMPERSONATION: a forged call is denied fail-closed")
    impostor = AgentIdentity.generate("impostor-agent")
    wire = {"jsonrpc": "2.0", "id": "execute_command", "method": "tools/call",
            "params": {"name": "execute_command", "arguments": {"command": "ABORT"}}}
    op = uuid.uuid4().hex
    body = json.dumps({"src": "mcp", "dst": "mcp", "wire": wire, "target_id": None,
                       "operation_id": op}, sort_keys=True, separators=(",", ":")).encode()
    nonce = uuid.uuid4().hex
    signed_data = canonical_payload(gw.agent_id, nonce, body)

    async def _never(_wire):
        return {"should_not_run": True}

    try:
        await gw.gw.route_call(agent_id=gw.agent_id, src_proto="mcp", dst_proto="mcp",
                               src_wire=wire, invoke=_never, cost=500_000,
                               operation_id=op, signed_body=body, signed_nonce=nonce,
                               signed_data=signed_data, signature=impostor.sign(signed_data))
        print("  [forged] ALLOWED — this must never happen")
    except GovernanceError as exc:
        print(f"  [forged] BLOCKED  {exc}")
    print("  >> The impostor signs with its own key, not the registered agent key.")
    print("     No valid proof, no execution — and the denial itself is audited.")

    hr("SCENE 7 — The flight recorder: complete, signed, independently verifiable")
    entries = gw.audit_entries()
    for e in entries:
        print(f"  #{e.seq:<2} {e.decision:<5} {e.capability:<24} {e.entry_hash[:12]}  {e.reason}")
    print(f"\n  Audit integrity verified (durable chain): {gw.verify_integrity()}")
    paths = gw.export_flight_recorder(HERE, "audit")
    with open(paths["jsonl"], encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    with open(paths["checkpoint"], encoding="utf-8") as fh:
        checkpoint = json.load(fh)
    print(f"  Exported {len(records)} full-field entries -> {os.path.basename(paths['jsonl'])}")
    print(f"  Signed checkpoint (operator key) -> {os.path.basename(paths['checkpoint'])}: "
          f"verified {AuditLog.verify_checkpoint(checkpoint)}")
    wpath = paths.get("witness")
    if wpath:
        with open(wpath, encoding="utf-8") as fh:
            witness = json.load(fh)
        with open(paths["anchor"], encoding="utf-8") as fh:
            meta = json.load(fh)
        anchor_ok = True
        try:
            anchor.verify_anchor(records, checkpoint, witness,
                                 operator_key_hex=meta["operator_key_hex"],
                                 witness_key_hex=meta["witness_key_hex"])
        except Exception:
            anchor_ok = False
        print(f"  Independent witness over checkpoint -> {os.path.basename(wpath)}: "
              f"verified {anchor_ok}")
        print(f"  Independently time-anchored (TSA): {meta['independently_time_anchored']}")
    print(f"  Call journal (arguments + outcomes) -> {os.path.basename(paths['journal'])}")
    print(f"  Independent re-verification from the exported file: "
          f"{AuditLog.verify_chain(records, require_genesis=True)}")
    print("  Check it yourself: python verify_export.py audit")
    print("\n  Same equipment. Same agent. One trusts nothing; the other can prove")
    print("  every action was authenticated, authorized, budgeted, approved, and logged.\n")


if __name__ == "__main__":
    asyncio.run(main())