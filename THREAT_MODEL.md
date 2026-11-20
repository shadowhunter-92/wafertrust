# WaferTrust threat model

**Status: engineering alpha.** This describes the security properties of the *demo* as it
exists today, on laptop-only simulators. It is not a production security assessment, a
compliance claim, or a safety case. Read it together with the [README](README.md), the
14 tests in [`test_hardening.py`](test_hardening.py), the custody/anchoring tests in
[`test_custody_anchor.py`](test_custody_anchor.py), and the wire-path tests in
[`test_secs_transport.py`](test_secs_transport.py).

## 1. What this is

A single-process Python demo that puts AgentBridge's real `GovernanceGateway` between a demo
agent and a simulated SECS/GEM equipment boundary (`equipment.py`, `maintenance_system.py`).
The default demos have no network transport and no real equipment. An optional wire path
(`secs_demo.py`) adds a real HSMS/SECS-II TCP link to a software equipment simulator on
localhost; the protocol is real, the device is not (see the wire-path limits below). There is
no multi-tenant deployment. The kernel runs in production admission mode
(`AGENTBRIDGE_ENV=production`, `require_verified=True`), so the authentication and authorization
paths are the kernel's real ones, not stubs.

## 2. Assets

- **Wafer-dollars at risk** — the illustrative cost of an equipment write (e.g. a setpoint
  change that scraps a lot). Budgets bound how much risk approved calls can accumulate.
- **The action record** — who called what, with which arguments, when, and with what outcome.
  The hash-chained audit + call journal are the evidence that an action was authorized.
- **Operator authority** — the ability to approve a sensitive write and to sign a checkpoint
  over the log head. Held by a separate operator key, not the agent key.

## 3. Trust boundaries

| Boundary | Trusted for | Not trusted for |
|----------|-------------|-----------------|
| Demo agent | holding its own Ed25519 private key | self-authorizing writes; it must pass the kernel |
| AgentBridge kernel | verifying proofs, enforcing policy/budget/approval, appending audit | physical safety; it governs *tool access*, not process physics |
| Operator | approving requests and signing checkpoints | being infallible — a compromised operator key defeats the checkpoint |
| Witness key | co-signing the checkpoint anchor envelope | independent custody — in the demo it lives on the same host as the operator |
| SQLite store | durability within a run | tamper-proofing against an attacker who controls the host |
| Equipment simulator | returning deterministic stub results | representing real fab behavior |

The agent keeps its private key; the registry only ever sees the public half. The operator
key is distinct from the agent key, so a checkpoint is the operator's statement, not another
caller signature. A third, distinct witness key co-signs the anchor envelope; the kernel
rejects a checkpoint witnessed by the same key that signed it.

## 4. Threats considered and mitigated (each is tested)

- **Unsigned call** — a call with no request-bound proof is denied fail-closed by the kernel.
- **Forged / impostor call** — a caller signing with a key other than the registered agent key
  is denied; the denial is audited. (Demo scene 6.)
- **Tampered request** — a proof bound to one tool/arguments/operation ID does not validate a
  different request; mismatched bodies are denied.
- **Unauthorized capability** — tools outside the operator-owned allowlist are denied
  (`AllowOnlyCapabilities`).
- **Sensitive write without approval** — writes above the approval threshold block pending a
  human grant (`RequireApprovalAboveCost`); the grant is one-shot and bound to the exact
  request, so an approved retry must reuse the blocked call's operation ID.
- **Replay of a succeeded operation** — a consumed operation ID cannot be replayed.
- **Over-budget action** — even an approved write is denied if it would exceed the cumulative
  budget or the per-call cap (`MaxCostPerCall`). (Demo scene 5.)
- **Audit tampering within retained history** — editing an entry breaks the hash chain;
  `verify_integrity()` and the standalone `verify_export.py` detect it.
- **Export / checkpoint tampering** — the exported chain, the signed checkpoint, and the
  journal-to-entry-hash links are re-verified from the files alone; altering any of them fails
  verification.
- **Checkpoint rollback / truncation past an anchor** — the independent-witness envelope binds
  the checkpoint digest and sequence; `verify_export.py` rejects a truncated or forked chain and
  a checkpoint witnessed by the operator's own key. With `--operator-key`/`--witness-key` the
  trust roots are pinned independently; without them the check is self-consistency only (warned).

## 5. Explicit non-goals (out of scope today)

These are **not** provided, and no claim is made otherwise:

- **Process-physics safety.** No interlocks, rate-of-change limits, or cross-tag safety
  envelope. WaferTrust governs *whether a tool call is authorized*, not *whether the setpoint
  is physically safe*. It does not detect unsafe setpoints.
- **WORM / independent custody.** The hash chain detects edits within retained history; it is
  not write-once storage and not independent proof of a destination effect. An attacker who
  controls the host can rewrite the whole chain.
- **Per-entry signatures.** Entries are hash-chained, not individually signed. The signed
  checkpoint authenticates *who signed it*, not independent custody or the equipment's actual
  outcome.
- **Independent custody / qualified anchoring.** An offline two-party witness envelope and an
  *optional* RFC 3161 TSA time anchor are now provided, but the witness key lives on the same
  host (so it is **not** independent custody), the TSA is FreeTSA (a free public service, **not**
  a qualified timestamp authority), and nothing is published to an append-only public log. A
  compromised operator key can still re-sign a checkpoint; the time anchor only proves the
  checkpoint digest existed at a point in time.
- **HSM-grade key custody.** An *optional* encrypted keystore (AES-256-GCM under a scrypt
  passphrase key) now persists agent/operator/witness keys at rest, but it is encryption on the
  same host — not an HSM or remote key manager — with no rotation or revocation. The demos still
  default to ephemeral, generate-per-run keys. Host compromise remains out of scope.
- **Transport / network security.** The default demos are in-process. The optional HSMS wire
  path is plaintext TCP to a localhost software simulator: no TLS, no HSMS link hardening, no
  MCP server socket. It demonstrates the protocol boundary, not a secured production transport.
- **Host / operator compromise.** A compromised host or operator key is outside the model.
- **Production identity / multi-tenancy.** No SSO, no tenant isolation, no scale guarantees.
- **Real lot valuation.** Costs are fixed illustrative wafer-dollars, not live lot values; the
  example shift budget has no automatic shift reset.

### Real SECS/GEM wire path limits

- The HSMS endpoint (`secs_equipment_sim.py`) is a software simulator, not real equipment. The
  wire protocol (HSMS/SECS-II) is real; the governed device is not.
- `secsgem==0.3.0` is LGPL-2.1-or-later, used as a separable pip dependency (imported, not
  vendored). WaferTrust's own code remains Apache-2.0.
- Bounded tool subset; standard SECS-II structures only. No GEM300, no SECS-I, no full tool
  mapping, no certification, and no production-safety or process-physics claim.
- Governance is unchanged: identity, policy, budgets, approvals, and the hash-chained audit sit
  above the wire boundary exactly as in the in-process demo.

## 6. Residual risks

- The demo proves authentication, approval, and budget enforcement *on a simulator*. It does
  not prove that real wafer losses are prevented.
- The audit is only as trustworthy as the host and the operator key that signs checkpoints.
- The simulated E191-style `agentAudit` field is illustrative, not a real SEMI E191 field, and
  the standards mapping in the README is conceptual alignment, not compliance or certification.

## 7. What a real deployment would need

A connector to real equipment (the demo now speaks real SECS-II/HSMS to a software simulator,
not to a fab tool), HSM-grade operator key custody with
rotation and revocation, an independent witness service in a separate trust domain (or a
qualified TSA) rather than the same-host witness and free FreeTSA used here, deployment-specific
risk policies, transport hardening, and a physical safety layer independent of this
access-control layer. The demo now offers an encrypted-at-rest keystore, an offline witness
envelope, and an optional FreeTSA time anchor as stepping stones — not as substitutes for any of
the above.