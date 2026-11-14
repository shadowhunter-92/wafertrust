# WaferTrust

**The trust layer for every wafer.** A neutral governance prototype for AI agents that act on
semiconductor fab equipment — a read-only "flight recorder," approval-gated writes,
illustrative wafer-dollar risk budgets, and a hash-chained audit. Built on the
[AgentBridge](https://github.com/shadowhunter-92/agentbridge) trust kernel.

## The gap

A device-status report is not an agent-action audit trail. SEMI E191 reports
computing-device status, rather than authorizing or recording AI-agent tool calls.
In our simulator, one direct out-of-range setpoint change scraps a 25-wafer lot
(**~$500,000**, assuming $20,000 per wafer). The simulated E191-style report includes
an illustrative `agentAudit = 'none'` extension; this is not a real E191 field.

WaferTrust demonstrates a gateway between an agent and a simulated SECS/GEM equipment
boundary: read calls are logged, and writes require approval and sufficient configured budget.

## What the prototype demonstrates

- **Wafer-dollar risk budgets.** Writes carry fixed, illustrative costs: $500,000 for a
  setpoint change, command, or process-job action; $50,000 for a carrier action. A cumulative
  budget and per-call cap apply even after approval. These are not live lot-value estimates,
  and the example shift budget has no automatic shift reset.
- **A hash-chained flight recorder.** The full in-process audit can be checked with
  `verify_integrity()`. Entries are not individually signed, and the demo emits no signed
  checkpoints. Hash-chain consistency alone does not prove independent custody, caller
  authenticity, or the equipment's actual outcome.
- **Fab-first, MCP-wire integration.** Reads, equipment constants, process jobs, and carriers
  are routed through the MCP `tools/call` representation. This is a library demo, not a
  standalone MCP server or a live SECS/GEM connection.
- **Real kernel, not a mock.** Governance uses AgentBridge's actual `GovernanceGateway`
  for policy, budgets, approvals, and audit. An Ed25519 identity is registered, but this
  demo sets `require_verified=False` and does not supply caller signatures. Recorded
  agent IDs therefore are not cryptographically authenticated caller attribution.

The focus is semiconductor workflows and wafer-dollar cost accounting, not a claim that
SECS/GEM governance is otherwise absent. It governs tool access, not process physics:
there is no live interlock, rate-of-change, or cross-tag safety-envelope model.

## What it shows

Same simulated equipment, same demo agent — two outcomes:

- **Ungoverned:** a direct `set_equipment_constant(2001, 500)` call scraps a simulated
  25-wafer lot (**~$500,000**) without a gateway audit.
- **Governed:** reads pass through and are logged; a setpoint write waits for human approval;
  the approved write consumes $500,000 of a configured $600,000 budget; a subsequent
  $500,000 `ABORT` is denied even after approval. The full in-process audit's hash-chain
  integrity verifies `True`. This demonstrates approval and budget enforcement, not
  detection of unsafe setpoints or a guarantee of preventing real wafer losses.

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

- `audit-flight-recorder.jsonl`, `maintenance-flight-recorder.jsonl` — summaries of audit
  decisions containing entry hashes. They omit timestamp, source/target protocols, and
  `prev_hash`, so they cannot independently reproduce or verify the full audit chain.
- `secsgem-run-log.txt`, `maintenance-run-log.txt` — historical console run logs. Their
  "signed entries" wording is inaccurate: this demo exports no audit-entry signatures.

The full audit is held in memory and can verify its internal hash-chain consistency during
execution. The summaries do not contain tool arguments/results and are not replay records.

## Run

Requires Python 3.12+ and AgentBridge cloned alongside this folder:

```bash
git clone https://github.com/shadowhunter-92/agentbridge ../agentbridge
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python demo.py
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python maintenance_demo.py
```

`fab_gateway.py` adds `../agentbridge` to the path. The equipment/maintenance systems are
laptop-only simulator stubs, with no real fab hardware. A real integration would need an
actual equipment connector, authenticated caller and operator channels, durable complete
audit exports, and deployment-specific risk policies. Those are not implemented here.
**Engineering alpha — a prototype, not a production system.**

## Status & what I'm looking for

Independent, bootstrapped, validating whether this is worth building. I'm looking for
**critique and design partners** — fab automation / OT-security practitioners and the
maintainers of SECS/GEM and OPC UA agent bridges — to pressure-test the risk model and tell
me where a neutral audit/approval gate should sit (driver, sidecar, or host). No pitch.

## License

WaferTrust is licensed under the [Apache License 2.0](LICENSE).
Copyright 2026 Haider Ali. Built on AgentBridge (Apache-2.0).