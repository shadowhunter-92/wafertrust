# WaferTrust

**The trust layer for every wafer.** A neutral governance layer for AI agents that act on
semiconductor fab equipment — a read-only "flight recorder," approval-gated writes,
wafer-dollar risk budgets, and a hash-chained, signed audit. Built on
[AgentBridge](https://github.com/shadowhunter-92/agentbridge).

This repo is a working prototype demonstrating the wedge: start with a **read-only flight
recorder** for the maintenance / facilities / analytics agents fabs run today, then add
**approval-gated writes** bounded by **wafer-dollar risk budgets**.

## What it shows

Same equipment, same agent — two outcomes:

- **Ungoverned:** an agent calls `set_equipment_constant(2001, 500)` with no identity,
  approval, budget, or audit. The equipment's own SEMI E191 report says `agentAudit = 'none'`.
  One out-of-range setpoint scraps a 25-wafer lot (**~$500,000**) with no tamper-evident record.
- **Governed:** reads pass through and are logged; writes are blocked pending human approval;
  approved writes execute within a $600k/shift wafer-dollar budget; a circuit breaker denies
  any action that would risk more than the shift allows. Every call is identified (Ed25519),
  authorized, budgeted, approved, and recorded in a hash-chained audit (integrity verifies `True`).

## Demos

| File | Scenario |
|------|----------|
| `demo.py` | SECS/GEM equipment: 6 scenes (ungoverned scrap → governed reads → approval-gated write → budget circuit breaker → hash-chained audit). |
| `maintenance_demo.py` | Maintenance/facilities wedge: read-only flight recorder + approval-gated `dispatch_work_order`. |
| `equipment.py` | SECS/GEM equipment simulator stub (E30/E40/E87/E116/E191 surface). |
| `maintenance_system.py` | Maintenance-system stub (assets, sensors, work orders). |
| `fab_gateway.py` | Governance gateway wrapping AgentBridge's trust kernel. |

## Artifacts (the proof)

- `audit-flight-recorder.jsonl`, `maintenance-flight-recorder.jsonl` — hash-chained audit entries.
- `secsgem-run-log.txt`, `maintenance-run-log.txt` — full console run logs.

## Run

Requires Python 3.12+ and AgentBridge cloned alongside this folder:

```bash
git clone https://github.com/shadowhunter-92/agentbridge ../agentbridge
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python demo.py
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python maintenance_demo.py
```

`fab_gateway.py` adds `../agentbridge` to the path. The equipment/maintenance systems are
laptop-only simulator stubs (no real fab hardware). Engineering alpha — a prototype, not a
production system.

Built on AgentBridge (Apache-2.0).