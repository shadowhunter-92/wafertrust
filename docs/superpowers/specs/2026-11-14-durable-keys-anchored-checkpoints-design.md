# Design: Durable key custody + anchored checkpoints (#34)

Date: 2026-11-14
Status: approved design, pre-implementation
Scope: WaferTrust demo repo only (`fab-governance-demo`). No AgentBridge kernel changes.
Kernel: public `shadowhunter-92/agentbridge` @ `f309a35cb5c3ec4164acea5ba2622dc04be6807c`.

## Problem

Today the demo discloses two trust gaps:

1. Agent and operator Ed25519 keys are generated fresh per run (`AgentIdentity.generate`),
   so identity is not durable across restarts.
2. The audit checkpoint is only locally signed by the operator key. A local signed
   checkpoint is not an externally anchored checkpoint; there is no independent witness
   and no independent time anchor.

This design closes both, using existing kernel APIs, while staying honest about limits.

## Kernel APIs reused (no reimplementation)

- `AgentIdentity.from_private_hex(agent_id, private_hex)` and `AgentIdentity.private_key_hex`
  — load/export a persistent private key. `IdentityRegistry` is already store-backed.
- `AuditLog.checkpoint(sign, public_key_hex)` → `{seq, head_hash, algo, public_key_hex,
  signature_hex, created_at}`; `AuditLog.verify_checkpoint`, `AuditLog.verify_chain`.
- `external_anchor.checkpoint_digest(checkpoint)` — SHA-256 over the canonical checkpoint.
- `external_anchor.create_witness_statement(checkpoint, *, witness_id, witnessed_at,
  anchor_reference, sign)` — independent witness signs the whole checkpoint digest.
- `external_anchor.verify_anchored_audit(records, checkpoint, witness, *,
  checkpoint_key_hex, witness_key_hex)` — verifies full chain + independent witness;
  rejects truncation, fork, rollback, and `witness_key == checkpoint_key`.

## Components

Three distinct Ed25519 keys, all persisted in one encrypted keystore:

- **agent** — signs governed calls (existing role).
- **operator** — signs checkpoints (existing role).
- **witness** — NEW, independent key that signs the witness envelope. Must differ from the
  operator key (kernel enforces this).

### `keystore.py` (new)

Encrypted-at-rest keystore for private key hex.

- Crypto: AES-256-GCM (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`), key derived
  from a passphrase with scrypt (`cryptography.hazmat.primitives.kdf.scrypt.Scrypt`,
  N=2**14, r=8, p=1, 32-byte key, random 16-byte salt). Random 12-byte nonce per write.
- File format (JSON, gitignored): `{version:1, kdf:{salt,n,r,p}, nonce, ciphertext}`,
  where plaintext is a JSON map `{key_id: private_key_hex}`.
- API:
  - `Keystore(path, passphrase)` — opens/creates; decrypts existing file or starts empty.
  - `load_or_generate(key_id) -> AgentIdentity` — returns persisted identity if present,
    else generates, persists, and returns it. Uses kernel `from_private_hex` /
    `private_key_hex`.
  - `save()` — re-encrypts and writes atomically (temp file + replace).
- Wrong passphrase → raise `KeystoreError` (fail-closed; never silently regenerate).
- **Ephemeral mode**: `Keystore(None, None)` keeps keys in memory only, preserving today's
  generate-per-run behavior. This is the default for tests/CI so the existing 14 tests and
  the CI workflow stay unchanged.
- Passphrase source for durable mode: env `WAFERTRUST_KEYSTORE_PASSPHRASE` (demo only;
  documented as not production secret management).

### `anchor.py` (new)

Wraps the kernel witness protocol.

- `create_witness(checkpoint, witness_identity, *, anchor_reference) -> dict` — calls
  `external_anchor.create_witness_statement` with `witness_id = witness_identity.did`,
  `witnessed_at = utcnow iso8601`, `sign = witness_identity.sign`.
- `verify_anchor(records, checkpoint, witness, *, operator_key_hex, witness_key_hex) -> dict`
  — delegates to `external_anchor.verify_anchored_audit`.
- Pure offline; no network.

### `tsa.py` (new, optional)

RFC 3161 time anchor via `rfc3161ng` (pinned `==2.1.3`, MIT).

- `TsaClient(url, certificate_pem, hashname="sha256")` wraps
  `rfc3161ng.RemoteTimestamper`.
- `timestamp(digest_bytes) -> bytes` — returns the raw DER TimeStampResp/token.
- `verify(token_bytes, digest_bytes) -> bool` — `RemoteTimestamper.check`.
- Default URL `https://freetsa.org/tsr`; TSA certificate pinned in repo (`tsa/freetsa.pem`)
  or supplied by path. **FreeTSA is free but not a qualified/audited CA** — documented.
- Network is used ONLY when explicitly enabled. Tests/CI mock `RemoteTimestamper`; no
  network calls in the suite.
- On network/verification failure: return no token and set `independently_time_anchored:
  false`. Never claim a timestamp without a valid, verified token.

## Integration

### `fab_gateway.py`

- `__init__` gains optional `keystore=None` and `witness_id=None`. When a durable keystore
  is supplied, agent/operator/witness identities come from `keystore.load_or_generate`;
  otherwise behavior is unchanged (ephemeral). The witness key is registered nowhere as a
  caller — it only signs witness envelopes.
- `export_flight_recorder` additionally writes:
  - `{stem}-witness.json` — the witness envelope over the checkpoint.
  - `{stem}-anchor.json` — `{independently_time_anchored: bool, tsa_url?, anchor_reference}`.
  - `{stem}-tsa-token.der` — only when a TSA token was obtained and verified.
  - `anchor_reference` in the witness points to the TSA token file (or `"local-witness-only"`).

### `verify_export.py`

- After existing chain/checkpoint/journal checks, load `-witness.json` and run
  `verify_anchored_audit`.
- **Trusted roots (independent pinning).** New optional CLI flags `--operator-key HEX` and
  `--witness-key HEX`. When both are supplied, they are the pinned trust roots and the
  verification is independent of the export's own claims. When omitted, the verifier falls
  back to the checkpoint's `public_key_hex` and the key embedded in the witness `witness_id`
  DID, and prints a loud warning: `self-consistency only — not independently pinned`. This
  mirrors the kernel requirement that trust roots be sourced independently; the demo never
  silently presents embedded-key verification as independent custody.
- If `-tsa-token.der` present, verify it against the checkpoint digest with the pinned TSA
  cert; report `independently_time_anchored` accordingly. Absent token → witness-only,
  explicitly flagged as not independently time-anchored.

### Demos

- `demo.py` / `maintenance_demo.py`: add a short scene showing the witness verification and
  (when enabled) the TSA anchor, printing the honest `independently_time_anchored` flag.
  Default demo run stays offline (witness-only); TSA is opt-in via a flag/env.

## Error handling

- Keystore wrong passphrase / corrupt file → `KeystoreError`, fail-closed.
- Witness key equals operator key → kernel raises `AnchorVerificationError`; surfaced.
- TSA network/verification failure → graceful fallback to witness-only, flag false.
- Truncated/forked/rolled-back chain → `verify_anchored_audit` raises; verifier reports FAIL.

## Testing (TDD; new `test_custody_anchor.py`, existing 14 unchanged)

1. Keystore round-trip: `load_or_generate` persists; a second keystore instance with the
   same passphrase returns the same public key.
2. Wrong passphrase raises `KeystoreError`; ciphertext file contains no plaintext key hex.
3. Ephemeral mode generates in memory and writes no file.
4. Durability: two `FabGovernanceGateway` instances sharing keystore + db reuse the same
   agent public key.
5. Witness requires an independent key (`witness_key == operator_key` rejected).
6. `verify_anchored_audit` passes on an honest export; fails on a truncated chain and on a
   forked head.
7. TSA adapter (mocked `RemoteTimestamper`): success path stores a verified token; network
   failure path yields `independently_time_anchored: false` and no token.
8. `verify_export.py` reports witness verified and the correct anchoring flag.

Each test is written first and watched fail for the expected reason before implementation.

## Honesty updates (README + THREAT_MODEL.md)

- Encrypted-at-rest keys are NOT an HSM; host compromise remains out of scope.
- An offline witness is a second-party signature on the SAME host — it proves the two-party
  protocol and detects truncation/fork, but is NOT independent custody.
- A TSA timestamp is an independent TIME anchor only; FreeTSA is not a qualified CA.
- No production-safety, compliance, or physics claims. Simulator only.

## Dependencies

- Add optional `rfc3161ng==2.1.3` (pulls pyasn1/pyasn1-modules). Keystore/anchor use the
  already-present `cryptography`. requirements.txt documents the TSA extra; CI installs the
  base set and mocks TSA, so CI does not require network.

## Out of scope

- HSM / remote key management, key rotation/revocation UI, multi-tenant custody.
- Qualified TSA / legal-grade timestamping.
- Real SECS/GEM connection (that is #33, designed separately).
- Any change to the AgentBridge kernel or its working tree.

## Delivery

Local-first: implement + verify in the isolated temp venv against the public kernel, update
docs, then present the batch for explicit push approval. Nothing pushed without approval.