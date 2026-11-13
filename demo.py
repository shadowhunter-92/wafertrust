"""The 60-second story: why a fab needs a trust layer for its agents.

Run with the project venv:
    ../.venv/Scripts/python.exe demo.py

Scene 1 shows an UNGOVERNED agent scrapping a $500k lot with one unlogged
command. Scenes 2-6 show the SAME equipment behind AgentBridge: reads pass
through and are audited, writes are approval-gated and wafer-budgeted, and every
decision lands in a hash-chained, independently verifiable flight recorder.
"""

from __future__ import annotations

import asyncio
import json
import os

from equipment import SecsGemEquipment, ACTIVE_LOT_WAFERS, WAFER_VALUE_USD
from fab_gateway import FabGovernanceGateway

HERE = os.path.dirname(os.path.abspath(__file__))


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
    gw = FabGovernanceGateway(eq, budget_limit=600_000, approval_threshold=100_000, max_cost=750_000)
    print(f"  Agent identity registered: {gw.agent_id} (Ed25519 DID)")
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
    out = await gw.governed_call("set_equipment_constant", {"ecid": 2001, "value": 400})
    show("write", out)
    b = gw.budget()
    print(f"  Budget spent ${b.spent:,.0f} / ${b.spend_limit:,.0f}; remaining ${b.remaining():,.0f}")

    hr("SCENE 5 — Wafer-dollar circuit breaker: budget exhausted")
    out = await gw.governed_call("execute_command", {"command": "ABORT"})
    show("write", out)
    if out.get("approval_id"):
        gw.approve(out["approval_id"])
    out = await gw.governed_call("execute_command", {"command": "ABORT"})
    show("write", out)
    print("  >> Even with approval, the action is denied: it would risk more")
    print("     wafer-dollars than the shift budget allows.")

    hr("SCENE 6 — The flight recorder: hash-chained, verifiable audit")
    entries = gw.audit_entries()
    for e in entries:
        print(f"  #{e.seq:<2} {e.decision:<5} {e.capability:<24} {e.entry_hash[:12]}  {e.reason}")
    print(f"\n  Audit integrity verified: {gw.verify_integrity()}")
    path = os.path.join(HERE, "audit-flight-recorder.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps({
                "seq": e.seq, "actor": e.actor, "action": e.action,
                "capability": e.capability, "decision": e.decision,
                "reason": e.reason, "cost": e.cost, "entry_hash": e.entry_hash,
            }, default=str) + "\n")
    print(f"  Exported {len(entries)} signed entries -> {os.path.basename(path)}")
    print("\n  Same equipment. Same agent. One trusts nothing; the other can prove")
    print("  every action was identified, authorized, budgeted, approved, and logged.\n")


if __name__ == "__main__":
    asyncio.run(main())