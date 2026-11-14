# WaferTrust threat model

**Status: engineering alpha.** This describes the security properties of the *demo* as it
exists today, on laptop-only simulators. It is not a production security assessment, a
compliance claim, or a safety case. Read it together with the [README](README.md) and the
14 tests in [`test_hardening.py`](test_hardening.py).

## 1. What this is

A single-process Python demo that puts AgentBridge's real `GovernanceGateway` between a demo
agent and a simulated SECS/GEM equipment boundary (`equipment.py`, `maintenance_system.py`).
There is no network transport, no real equipment, and no multi-tenant deployment. The kernel
runs in production admission mode (`AGENTBRIDGE_ENV=production`, `require_verified=True`), so
the authentication and authorization paths are the kernel's real ones, not stubs.

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
| SQLite store | durability within a run | tamper-proofing against an attacker who controls the host |
| Equipment simulator | returning deterministic stub results | representing real fab behavior |

The agent keeps its private key; the registry only ever sees the public half. The operator
key is distinct from the agent key, so a checkpoint is the operator's statement, not another
caller signature.

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
- **External anchoring.** Checkpoints are not timestamped (RFC 3161) or published to an
  append-only log. A checkpoint can be re-signed by a compromised operator key.
- **Durable key custody.** Demo agent and operator keys are generated fresh per run and held
  in-process. There is no keystore, HSM, rotation, or revocation.
- **Transport / network security.** Calls are in-process. There is no TLS, no MCP server
  socket, no SECS/GEM HSMS link to harden.
- **Host / operator compromise.** A compromised host or operator key is outside the model.
- **Production identity / multi-tenancy.** No SSO, no tenant isolation, no scale guarantees.
- **Real lot valuation.** Costs are fixed illustrative wafer-dollars, not live lot values; the
  example shift budget has no automatic shift reset.

## 6. Residual risks

- The demo proves authentication, approval, and budget enforcement *on a simulator*. It does
  not prove that real wafer losses are prevented.
- The audit is only as trustworthy as the host and the operator key that signs checkpoints.
- The simulated E191-style `agentAudit` field is illustrative, not a real SEMI E191 field, and
  the standards mapping in the README is conceptual alignment, not compliance or certification.

## 7. What a real deployment would need

An actual equipment connector (e.g. a SECS/GEM driver), durable operator key custody, externally
anchored checkpoints, deployment-specific risk policies, transport hardening, and a physical
safety layer independent of this access-control layer. None of those are implemented here.