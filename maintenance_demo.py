"""The wedge demo: govern the maintenance agent fabs run TODAY.

Customer research found the felt pain is facilities/maintenance/analytics — e.g.
Intel runs agentic maintenance work-order generation "with human oversight at
every step." This demo governs exactly that agent: it may read and recommend
freely (every step audited), but DISPATCHING a work order takes a tool offline
and is approval-gated + wafer-risk-budgeted.

Run:  ../.venv/Scripts/python.exe maintenance_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os

from maintenance_system import MaintenanceSystem
from fab_gateway import FabGovernanceGateway

HERE = os.path.dirname(os.path.abspath(__file__))

READ_TOOLS = ["read_sensor_trends", "get_asset_health", "list_pending_work_orders", "recommend_work_order"]
WRITE_TOOLS = ["dispatch_work_order"]
TOOL_COSTS = {
    "read_sensor_trends": 0, "get_asset_health": 0, "list_pending_work_orders": 0,
    "recommend_work_order": 0, "dispatch_work_order": 200_000,
}


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
    sys = MaintenanceSystem()
    gw = FabGovernanceGateway(
        sys, agent_id="fab-maintenance-agent", budget_limit=300_000,
        approval_threshold=50_000, max_cost=250_000,
        read_tools=READ_TOOLS, write_tools=WRITE_TOOLS, tool_costs=TOOL_COSTS)

    hr("SCENE 1 — The agent reads asset health (read-only flight recorder)")
    print("  This is the maintenance agent fabs run today (e.g. Intel facilities).")
    print(f"  Identity: {gw.agent_id} (Ed25519 DID). Every read is audited.")
    show("read", await gw.governed_call("read_sensor_trends", {"asset_id": "UPW-PUMP-01"}))
    show("read", await gw.governed_call("get_asset_health", {"asset_id": "UPW-PUMP-01"}))

    hr("SCENE 2 — The agent RECOMMENDS a work order (audited, no actuation)")
    out = await gw.governed_call("recommend_work_order", {
        "asset_id": "UPW-PUMP-01", "issue": "bearing vibration rising (4.8 mm/s)", "priority": "high"})
    show("recommend", out)
    wo_id = out["result"]["workOrderId"] if out["allowed"] else "WO-001"
    print("  >> The recommendation is free, but the flight recorder now proves")
    print("     WHO recommended it, WHAT asset, and WHY — no more tribal knowledge.")

    hr("SCENE 3 — DISPATCH is BLOCKED: it takes a tool offline (wafer-risk)")
    out = await gw.governed_call("dispatch_work_order", {"work_order_id": wo_id, "window": "next-shift"})
    show("dispatch", out)
    approval_id = out.get("approval_id")

    hr("SCENE 4 — Human approves; dispatch executes within the wafer budget")
    if approval_id:
        print(f"  Operator approves {approval_id}: {gw.approve(approval_id)}")
    out = await gw.governed_call("dispatch_work_order", {"work_order_id": wo_id, "window": "next-shift"})
    show("dispatch", out)
    b = gw.budget()
    print(f"  Wafer-budget spent ${b.spent:,.0f} / ${b.spend_limit:,.0f}; remaining ${b.remaining():,.0f}")

    hr("SCENE 5 — The flight recorder: every recommendation + action, verifiable")
    entries = gw.audit_entries()
    for e in entries:
        print(f"  #{e.seq:<2} {e.decision:<5} {e.capability:<24} {e.entry_hash[:12]}  {e.reason}")
    print(f"\n  Audit integrity verified: {gw.verify_integrity()}")
    path = os.path.join(HERE, "maintenance-flight-recorder.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps({
                "seq": e.seq, "actor": e.actor, "action": e.action,
                "capability": e.capability, "decision": e.decision,
                "reason": e.reason, "cost": e.cost, "entry_hash": e.entry_hash,
            }, default=str) + "\n")
    print(f"  Exported {len(entries)} signed entries -> {os.path.basename(path)}")
    print("\n  The agent recommends freely; humans approve action; every step is")
    print("  attributable. That is the trust layer the fab industry says it needs.\n")


if __name__ == "__main__":
    asyncio.run(main())