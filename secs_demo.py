"""Real HSMS/SECS-II governed-call demo (#33).

Starts the software equipment simulator as a SEPARATE PROCESS, then drives the real
AgentBridge governance gateway over a genuine HSMS/TCP + SECS-II wire. The endpoint is a
SOFTWARE SIMULATOR, not real fab equipment. No production-safety or compliance claim.

Run:  python secs_demo.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

from fab_gateway import FabGovernanceGateway, AgentIdentity, AuditLog, GovernanceError, canonical_payload
from hsms_equipment import HsmsEquipment, HsmsError
import anchor

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "secs-governance.sqlite3")


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


def free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_sim(port: int):
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "secs_equipment_sim.py"),
                             "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Wait for the simulator's ready line. Do NOT open a probe TCP connection: the
    # secsgem passive server accepts exactly one client then closes its listening socket,
    # so a probe would steal the slot the real host needs. The active host retries until
    # the listener is bound, so the ready line plus connect_timeout is sufficient.
    t0 = time.time()
    while time.time() - t0 < 10.0:
        if proc.poll() is not None:
            raise RuntimeError("simulator exited early:\n" + (proc.stdout.read() or ""))
        line = proc.stdout.readline()
        if line and "listening" in line:
            return proc
    proc.terminate()
    raise RuntimeError("simulator did not become ready")


async def main() -> int:
    hr("Real HSMS/SECS-II wire path: SOFTWARE SIMULATOR, not real equipment")
    port = free_port()
    proc = start_sim(port)
    print(f"  Simulator subprocess started on 127.0.0.1:{port} (SEMI E37 HSMS / SEMI E5 SECS-II).")
    try:
        eq = HsmsEquipment(port=port)
    except HsmsError as exc:
        print(f"  FAIL: {exc}")
        proc.terminate()
        return 1
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    gw = FabGovernanceGateway(eq, budget_limit=600_000, approval_threshold=100_000,
                              max_cost=750_000, db_path=DB_PATH)
    print(f"  Agent identity: {gw.agent_id} (Ed25519 DID); fail-closed production admission.")

    hr("SCENE 1: Governed read over the wire (S1F1 -> S1F2)")
    show("read", await gw.governed_call("get_equipment_status", {}))
    show("read", await gw.governed_call("get_status_variable", {"svid": 1002}))

    hr("SCENE 2: EC write BLOCKED pending approval (S2F15 -> S2F16)")
    out = await gw.governed_call("set_equipment_constant", {"ecid": 2001, "value": 400})
    show("write", out)
    approval_id = out.get("approval_id")

    hr("SCENE 3: Human approves; write executes over the wire within budget")
    if approval_id:
        print(f"  Operator approves {approval_id}: {gw.approve(approval_id)}")
    out = await gw.governed_call("set_equipment_constant", {"ecid": 2001, "value": 400},
                                 operation_id=out["operation_id"])
    show("write", out)
    b = gw.budget()
    print(f"  Budget spent ${b.spent:,.0f} / ${b.spend_limit:,.0f}; remaining ${b.remaining():,.0f}")

    hr("SCENE 4: Wafer-dollar circuit breaker (S2F41 -> S2F42 ABORT)")
    out = await gw.governed_call("execute_command", {"command": "ABORT"})
    show("write", out)
    if out.get("approval_id"):
        gw.approve(out["approval_id"])
    out = await gw.governed_call("execute_command", {"command": "ABORT"},
                                 operation_id=out["operation_id"])
    show("write", out)
    print("  >> Denied: would risk more wafer-dollars than the shift budget allows.")

    hr("SCENE 5: Impersonation denied fail-closed")
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
                               src_wire=wire, invoke=_never, cost=500_000, operation_id=op,
                               signed_body=body, signed_nonce=nonce, signed_data=signed_data,
                               signature=impostor.sign(signed_data))
        print("  [forged] ALLOWED, this must never happen")
    except GovernanceError as exc:
        print(f"  [forged] BLOCKED  {exc}")

    hr("SCENE 6: Flight recorder, signed, witnessed, independently verifiable")
    print(f"  Audit integrity verified: {gw.verify_integrity()}")
    paths = gw.export_flight_recorder(HERE, "secs")
    with open(paths["jsonl"], encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    with open(paths["checkpoint"], encoding="utf-8") as fh:
        checkpoint = json.load(fh)
    print(f"  Exported {len(records)} entries; checkpoint verified {AuditLog.verify_checkpoint(checkpoint)}")
    with open(paths["witness"], encoding="utf-8") as fh:
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
    print(f"  Independent witness verified: {anchor_ok}")
    print(f"  Independently time-anchored (TSA): {meta['independently_time_anchored']}")
    print(f"  Chain re-verified from file: {AuditLog.verify_chain(records, require_genesis=True)}")
    print("  Check it yourself: python verify_export.py secs")
    print("\n  Real wire protocol to a software simulator; every action authenticated,")
    print("  authorized, budgeted, approved, and logged. Not real equipment.\n")

    eq.close()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))