# WaferTrust

**The trust layer for every wafer.** A neutral governance layer for AI agents that act on
semiconductor fab equipment — a read-only "flight recorder," approval-gated writes,
wafer-dollar risk budgets, and a hash-chained, Ed25519-signed audit. Built on the
[AgentBridge](https://github.com/shadowhunter-92/agentbridge) trust kernel.

## The gap

A fab tool can report its own cybersecurity posture, but it cannot tell you **what an AI
agent just did to it**. SEMI E191 reports computing-device status (device ID, OS details) —
it says nothing about agent actions. So today an agent can call `set_equipment_constant`,
`execute_command`, or start a process job with no identity, no approval, no budget, and no
audit. In our run, one out-of-range setpoint scrapped a 25-wafer lot (**~$500,000**) and the
equipment's own E191-style report still said `agentAudit = 'none'`.

WaferTrust fills that gap: a neutral layer between the agent and the SECS/GEM equipment
boundary that makes every action **identified, authorized, budgeted, approved, and logged**.

## What's unique

- **Wafer-dollar risk budgets.** Each write carries a blast radius in wafer-dollars (a
  setpoint change or `ABORT` risks a whole lot). A per-shift budget and a per-call cap deny
  any action — *even an approved one* — that would risk more than the shift allows.
- **A signed, hash-chained flight recorder.** Every call (reads included) is recorded with
  an Ed25519 agent identity and chained so the log is tamper-evident and independently
  verifiable (`verify_integrity() → True`). Replayable and attributable.
- **Fab-specific, MCP-native.** SECS/GEM tool semantics (E30 GEM reads, equipment constants,
  process jobs, carriers) governed at the MCP `tools/call` boundary — not a generic OT proxy.
- **Real kernel, not a mock.** Governance is AgentBridge's actual `GovernanceGateway`
  (Ed25519 identity, declarative policy, budgets, human approvals, hash-chained audit) with
  fab semantics added on top.

Unlike general OT / OPC UA authorization gateways, WaferTrust is built for the fab: SECS/GEM
semantics, wafer-dollar blast-radius budgets, and an audit trail aligned to the SEMI
equipment-cybersecurity standards below.

## What it shows

Same equipment, same agent — two outcomes:

- **Ungoverned:** an agent calls `set_equipment_constant(2001, 500)` with no identity,
  approval, budget, or audit. One out-of-range setpoint scraps a 25-wafer lot (**~$500,000**)
  with no tamper-evident record of who did it or why.
- **Governed:** reads pass through and are logged; writes are blocked pending human approval;
  approved writes execute within a $600k/shift wafer-dollar budget; a circuit breaker denies
  any action that would risk more than the shift allows. Every call is identified (Ed25519),
  authorized, budgeted, approved, and recorded in a hash-chained audit (integrity verifies `True`).

## How it maps to the SEMI equipment-cybersecurity standards

*Conceptual alignment, not compliance or certification. The demo runs on simulator stubs.*

| Standard | What it covers | Where WaferTrust fits |
|----------|----------------|------------------------|
| **SEMI E187** — Cybersecurity of Fab Equipment | Baseline hardening of the equipment (OS, network, endpoint). | Complements it: hardening secures the box; WaferTrust governs the **AI-agent access path** to it (identity, authorization, audit). |
| **SEMI E188** — Malware Free Equipment Integration | Malware-free delivery, installation, and maintenance. | Supports the intent: approval-gated, logged writes make changes during maintenance/integration **authorized and attributable** (not a substitute for malware scanning). |
| **SEMI E191** — Computing Device Cybersecurity Status Reporting | Reports device ID and OS/security status. | Fills the blind spot: E191 reports device status, **not agent actions**. The flight recorder adds the missing agent-action audit trail. The demo extends a simulated E191-style report with an `agentAudit` field to show today's gap (`'none'`). |

## Demos

| File | Scenario |
|------|----------|
| `demo.py` | SECS/GEM equipment: 6 scenes (ungoverned scrap → governed reads → approval-gated write → budget circuit breaker → hash-chained audit). |
| `maintenance_demo.py` | Maintenance/facilities wedge: read-only flight recorder + approval-gated `dispatch_work_order`. |
| `equipment.py` | In-process SECS/GEM equipment simulator. Mirrors the go-factory-io / secsgem-mcp-server data model (SV, EC, alarms, process jobs, carriers, E191-style report) so the demo runs laptop-only. |
| `maintenance_system.py` | Maintenance-system stub (assets, sensors, work orders). |
| `fab_gateway.py` | Governance gateway wrapping AgentBridge's trust kernel; governs 6 read + 4 write tools at the MCP boundary. |

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
laptop-only simulator stubs (no real fab hardware); in production the gateway's `invoke`
would call the real secsgem-mcp-server → go-factory-io REST API, with the governance layer
unchanged. **Engineering alpha — a prototype, not a production system.**

## Status & what I'm looking for

Independent, bootstrapped, validating whether this is worth building. I'm looking for
**critique and design partners** — fab automation / OT-security practitioners and the
maintainers of SECS/GEM and OPC UA agent bridges — to pressure-test the risk model and tell
me where a neutral audit/approval gate should sit (driver, sidecar, or host). No pitch.

Built on AgentBridge (Apache-2.0).