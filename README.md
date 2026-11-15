# WaferTrust

[![tests](https://github.com/shadowhunter-92/wafertrust/actions/workflows/tests.yml/badge.svg)](https://github.com/shadowhunter-92/wafertrust/actions/workflows/tests.yml)

**The trust layer for every wafer.** A neutral governance prototype for AI agents that act on
semiconductor fab equipment — fail-closed Ed25519 caller authentication, a read-only "flight
recorder" with a signed checkpoint, approval-gated writes, and illustrative wafer-dollar risk
budgets. Built on the [AgentBridge](https://github.com/shadowhunter-92/agentbridge) trust kernel.

## The gap

A device-status report is not an agent-action audit trail. SEMI E191 reports
computing-device status, rather than authorizing or recording AI-agent tool calls.
In our simulator, one direct out-of-range setpoint change scraps a 25-wafer lot
(**~$500,000**, assuming $20,000 per wafer). The simulated E191-style report includes
an illustrative `agentAudit = 'none'` extension; this is not a real E191 field.

WaferTrust demonstrates a gateway between an agent and a simulated SECS/GEM equipment
boundary: read calls are logged, and writes require approval and sufficient configured budget.

## What the prototype demonstrates

- **Fail-closed caller authentication.** The kernel runs in production admission mode: every
  call must carry an Ed25519 signature over a canonical payload binding the agent ID, a nonce,
  and the exact request (tool, arguments, operation ID). Unsigned, forged, or mismatched calls
  are denied by the kernel itself, and the denial is audited. An operator-owned capability
  allowlist applies on top of registered identity.
- **Wafer-dollar risk budgets.** Writes carry fixed, illustrative costs: $500,000 for a
  setpoint change, command, or process-job action; $50,000 for a carrier action. A cumulative
  budget and per-call cap apply even after approval. These are not live lot-value estimates,
  and the example shift budget has no automatic shift reset.
- **A durable, hash-chained flight recorder with a signed checkpoint.** Identity, budgets,
  approvals, the operation ledger, and the audit chain share one SQLite store. The full chain
  exports with every field (timestamps, protocols, prev-hash) and re-verifies independently
  from the exported file. A separate operator key signs a checkpoint over the chain head.
  Entries are hash-chained, not individually signed; a checkpoint authenticates its signer's
  statement, not independent custody or the equipment's actual outcome.
- **A call journal.** Every governed call's exact arguments and outcome are recorded and bound
  to its audit entry hash, so the sequence of what ran can be reconstructed afterwards.
- **Optional durable keys + anchored checkpoints.** An encrypted keystore (AES-256-GCM under a
  scrypt passphrase) can persist the agent/operator/witness keys across restarts, and each export
  adds an independent-witness anchor envelope plus an optional RFC 3161 TSA time anchor. The
  demos default to ephemeral keys and witness-only anchoring. This is encryption at rest and an
  offline witness on the same host — not an HSM, not independent custody, and FreeTSA is not a
  qualified timestamp authority (details below).
- **Fab-first, MCP-wire integration.** Reads, equipment constants, process jobs, and carriers
  are routed through the MCP `tools/call` representation. This is a library demo, not a
  standalone MCP server or a live SECS/GEM connection.
- **Real kernel, not a mock.** Governance uses AgentBridge's actual `GovernanceGateway`
  (`require_verified=True`) for policy, budgets, approvals, and audit. Approval grants are
  one-shot and bound to the exact request: an approved retry must reuse the blocked call's
  operation ID, and a succeeded operation ID cannot be replayed.

The focus is semiconductor workflows and wafer-dollar cost accounting, not a claim that
SECS/GEM governance is otherwise absent. It governs tool access, not process physics:
there is no live interlock, rate-of-change, or cross-tag safety-envelope model.

## What it shows

Same simulated equipment, same demo agent — two outcomes:

- **Ungoverned:** a direct `set_equipment_constant(2001, 500)` call scraps a simulated
  25-wafer lot (**~$500,000**) without a gateway audit.
- **Governed:** reads pass through and are logged; a setpoint write waits for human approval;
  the approved write consumes $500,000 of a configured $600,000 budget; a subsequent
  $500,000 `ABORT` is denied even after approval; an impostor signing with the wrong key is
  denied fail-closed. The exported chain re-verifies from genesis and the signed checkpoint
  verifies `True`. This demonstrates authentication, approval, and budget enforcement, not
  detection of unsafe setpoints or a guarantee of preventing real wafer losses.

## Architecture

The gateway is a thin fab-semantics wrapper; the trust decisions are made by AgentBridge's
real kernel. Every call — allowed or denied — is appended to the hash-chained audit.

```mermaid
flowchart TD
    A["Demo agent<br/>holds Ed25519 private key"] -->|"signs tool + args + operation_id + nonce"| G

    subgraph WT["WaferTrust · fab_gateway.py"]
        G["governed_call<br/>builds MCP tools/call wire + request-bound proof"]
    end

    G --> K

    subgraph AB["AgentBridge kernel · real GovernanceGateway (require_verified=True)"]
        K["route_call"] --> ID["IdentityRegistry<br/>verify Ed25519 proof — fail-closed"]
        ID --> POL["PolicyEngine<br/>AllowOnlyCapabilities · RequireApprovalAboveCost · MaxCostPerCall"]
        POL --> BUD["BudgetManager<br/>wafer-dollar spend + per-call cap"]
        BUD --> APP["ApprovalQueue<br/>one-shot, request-bound grants"]
        APP --> AUD["AuditLog<br/>hash-chained SQLite store"]
    end

    APP -->|"allowed"| EQ["Equipment simulator<br/>equipment.py / maintenance_system.py"]
    APP -->|"denied / needs approval"| DENY["GovernanceError<br/>denial is audited too"]

    OP["Operator<br/>separate key"] -->|"approve by approval_id"| APP
    AUD --> EXP["export_flight_recorder<br/>full-field JSONL + signed checkpoint + call journal + witness anchor"]
    OP -->|"signs checkpoint over chain head"| EXP
    EXP --> VER["verify_export.py<br/>standalone re-verification, no simulator"]
```

## Durable keys + anchored checkpoints (optional)

The demos generate fresh keys each run and anchor checkpoints with an offline witness. Two
optional layers let a longer-lived deployment go further — both are **stepping stones, not
production custody or qualified anchoring**.

- **Encrypted keystore (`keystore.py`).** Pass a `Keystore(path, passphrase)` to the gateway and
  the agent, operator, and witness keys persist across restarts. Keys are encrypted at rest with
  AES-256-GCM under a scrypt-derived passphrase key; the file is written atomically. Omit it (the
  demo default) and keys stay ephemeral. This is encryption on the same host — **not an HSM or a
  remote key manager** — with no rotation or revocation. Keystores are gitignored; never commit one.
- **Independent-witness anchor (`anchor.py`).** Every export adds a witness envelope: a third,
  distinct Ed25519 key co-signs the checkpoint digest and sequence. The kernel rejects a checkpoint
  witnessed by the same key that signed it, and `verify_export.py` rejects a truncated or forked
  chain past the anchor. In the demo the witness key lives on the same host, so this is an offline
  two-party check — **not independent custody**.
- **Optional RFC 3161 time anchor (`tsa.py`).** Pass a `TsaClient` and each export also timestamps
  the checkpoint digest with a TSA, saving a DER token. The pinned cert (`tsa/freetsa.pem`) is
  FreeTSA's public TSA signing certificate — a free service, **not a qualified timestamp authority**.
  The time anchor only proves the digest existed at a point in time; it is not independent custody,
  and nothing is published to an append-only public log. Tests and CI mock the client, so no network
  is needed to run the suite.

Verify an export with independently pinned trust roots (otherwise the witness check is
self-consistency only, and the verifier warns):

```bash
python verify_export.py audit --operator-key "$OPERATOR_PUB_HEX" --witness-key "$WITNESS_PUB_HEX"
```

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
| `demo.py` | SECS/GEM equipment: 7 scenes (ungoverned scrap → governed reads → approval-gated write → budget circuit breaker → impersonation denied → complete signed export). |
| `maintenance_demo.py` | Maintenance/facilities wedge: read-only flight recorder + approval-gated `dispatch_work_order` + impersonation denied (6 scenes). |
| `verify_export.py` | Standalone verifier: re-checks an exported chain, checkpoint signature, journal linkage, and witness anchor (with optional pinned trust roots + TSA token) without the simulator. |
| `test_hardening.py` | 14 tests: fail-closed authentication, request-bound approvals, budget breaker, idempotency, export/checkpoint tamper detection. |
| `test_custody_anchor.py` | 13 tests: encrypted keystore round-trip + wrong-passphrase rejection, witness anchor + tamper detection, mocked TSA, durable identity across restart, pinned-root verification. |
| `keystore.py` | Optional encrypted-at-rest key custody (AES-256-GCM under a scrypt passphrase); persists agent/operator/witness keys across restarts. |
| `anchor.py` | Independent-witness anchor wrapper over the kernel's `external_anchor`; creates and verifies a witness envelope over the checkpoint. |
| `tsa.py` | Optional RFC 3161 TSA adapter (`rfc3161ng`); timestamps the checkpoint digest. Mocked in tests/CI; pinned FreeTSA cert for live use. |
| `equipment.py` | In-process SECS/GEM equipment simulator. Mirrors the go-factory-io / secsgem-mcp-server data model (SV, EC, alarms, process jobs, carriers, E191-style report) so the demo runs laptop-only. |
| `maintenance_system.py` | Maintenance-system stub (assets, sensors, work orders). |
| `fab_gateway.py` | Governance gateway wrapping AgentBridge's trust kernel; governs 6 read + 4 write tools at the MCP boundary with request-bound signed proofs. |

## Artifacts (the proof)

- `audit-flight-recorder.jsonl`, `maintenance-flight-recorder.jsonl` — complete audit exports:
  every field of every entry (seq, timestamp, actor, action, protocols, capability, decision,
  reason, cost, prev_hash, entry_hash). Independently verifiable from the file alone.
- `audit-checkpoint.json`, `maintenance-checkpoint.json` — Ed25519-signed checkpoints over the
  chain head, produced with a separate operator key.
- `audit-witness.json`, `maintenance-witness.json` — independent-witness envelopes co-signing the
  checkpoint digest and sequence with a third, distinct key.
- `audit-anchor.json`, `maintenance-anchor.json` — anchor metadata: the operator/witness public
  keys, the anchor reference, and whether an independent time anchor was applied.
- `audit-tsa-token.der`, `maintenance-tsa-token.der` — *optional* RFC 3161 TSA tokens, present only
  when a `TsaClient` is configured (the demos default to witness-only, so these are absent).
- `audit-call-journal.jsonl`, `maintenance-call-journal.jsonl` — exact tool arguments and
  outcomes for every governed call, bound to audit entry hashes.
- `secsgem-run-log.txt`, `maintenance-run-log.txt` — console run logs from the current code.

Verify any export yourself (requires the AgentBridge clone, no simulator):

```bash
python verify_export.py audit
python verify_export.py maintenance
```

The hash chain detects edits within the retained history; it is not WORM storage or
independent proof of a destination effect. The demos generate fresh keys per run and use an
offline, same-host witness; the optional encrypted keystore and FreeTSA time anchor (above) are
stepping stones, not HSM-grade custody or qualified anchoring. A real deployment still needs
independent key custody and an external anchor in a separate trust domain.

## Quickstart

Python 3.12+ and Git. Clone the demo and the AgentBridge kernel as siblings, install the
pinned dependencies, and run — one paste in Git Bash (Linux/macOS: swap the activate line):

```bash
git clone https://github.com/shadowhunter-92/wafertrust
git clone https://github.com/shadowhunter-92/agentbridge
cd wafertrust
python -m venv .venv
source .venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

PYTHONUTF8=1 python demo.py
PYTHONUTF8=1 python maintenance_demo.py
PYTHONUTF8=1 python -m unittest test_hardening test_custody_anchor -v
python verify_export.py audit
python verify_export.py maintenance
```

`fab_gateway.py` resolves the kernel at `../agentbridge`, so the two folders must stay
siblings. The same steps run in CI ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)),
which pins the kernel to a verified commit.

### What a run looks like

Captured verbatim from a real `demo.py` run (approval IDs and hashes are regenerated each
run; full transcript in [`secsgem-run-log.txt`](secsgem-run-log.txt)):

```text
SCENE 1 — UNGOVERNED: an agent changes a setpoint directly
  Result: {'ok': False, 'scrappedWafers': 25, 'damageUsd': 500000, 'reason': '500.0 outside [200,450]'}
  >> 25 wafers scrapped, $500,000 lost,
     and NO tamper-evident record of who did it or why.

SCENE 3 — GOVERNED: a write is BLOCKED pending human approval
  [write] BLOCKED  approval required for 'set_equipment_constant'

SCENE 4 — Human approves; the write executes within budget
  [write] ALLOWED  cost=$500,000  -> {'ok': True, 'ecid': 2001, 'value': 400.0}
  Budget spent $500,000 / $600,000; remaining $100,000

SCENE 5 — Wafer-dollar circuit breaker: budget exhausted
  [write] BLOCKED  spend cap exceeded (500000.0+0+500000.0 > 600000)
  >> Even with approval, the action is denied: it would risk more
     wafer-dollars than the shift budget allows.

SCENE 6 — IMPERSONATION: a forged call is denied fail-closed
  [forged] BLOCKED  request-bound signed agent proof required

SCENE 7 — The flight recorder: complete, signed, independently verifiable
  Audit integrity verified (durable chain): True
  Signed checkpoint (operator key) -> audit-checkpoint.json: verified True
  Independent witness over checkpoint -> audit-witness.json: verified True
  Independently time-anchored (TSA): False
  Independent re-verification from the exported file: True
```

Each demo run recreates its own SQLite governance store (`*.sqlite3`, gitignored); the
exported JSONL/checkpoint/journal/witness/anchor files are the shareable evidence. `fab_gateway.py`
sets `AGENTBRIDGE_ENV=production` process-wide for fail-closed admission — this is a single-process
demo, not a mixed-mode library. The equipment/maintenance systems are laptop-only simulator
stubs, with no real fab hardware. A real integration would need an actual equipment connector,
HSM-grade operator key custody, an independently anchored checkpoint in a separate trust domain,
and deployment-specific risk policies. The optional encrypted keystore, offline witness, and
FreeTSA time anchor here are stepping stones toward those — not substitutes. **Engineering alpha —
a prototype, not a production system.**

## Status & what I'm looking for

Independent, bootstrapped, validating whether this is worth building. I'm looking for
**critique and design partners** — fab automation / OT-security practitioners and the
maintainers of SECS/GEM and OPC UA agent bridges — to pressure-test the risk model and tell
me where a neutral audit/approval gate should sit (driver, sidecar, or host). No pitch.

See [THREAT_MODEL.md](THREAT_MODEL.md) for the assets, trust boundaries, tested mitigations,
and the explicit non-goals (no process-physics safety, no WORM, no HSM-grade or independent custody).

## License

WaferTrust is licensed under the [Apache License 2.0](LICENSE).
Copyright 2026 Haider Ali. Built on AgentBridge (Apache-2.0).