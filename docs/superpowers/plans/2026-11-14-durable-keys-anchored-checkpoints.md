# Durable Keys + Anchored Checkpoints (#34) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (subagents are unavailable in this session, so execution is inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Persist agent/operator/witness keys in an encrypted keystore and anchor each audit checkpoint with an independent kernel witness plus an optional RFC 3161 TSA timestamp.

**Architecture:** Reuse kernel APIs (`AgentIdentity.from_private_hex`, `external_anchor.create_witness_statement` / `verify_anchored_audit`). Three small new modules (`keystore.py`, `anchor.py`, `tsa.py`) wrap them; `fab_gateway.py` and `verify_export.py` are extended; demos gain an anchor scene. Ephemeral mode preserves all existing behavior.

**Tech Stack:** Python 3.12, `cryptography` (AESGCM, Scrypt, Ed25519 — already a dep), optional `rfc3161ng==2.1.3` (MIT), stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-14-durable-keys-anchored-checkpoints-design.md`

## Global Constraints

- Demo repo only: `D:\qoder\ASLM EUV\fab-governance-demo`. NEVER modify the AgentBridge kernel or its working tree.
- Kernel sibling path `../agentbridge`; public kernel commit `f309a35cb5c3ec4164acea5ba2622dc04be6807c`.
- Existing 14 tests in `test_hardening.py` MUST stay green and unchanged.
- TSA network calls are mocked in tests/CI; no network in the suite.
- No overclaim: offline witness ≠ independent custody; TSA = independent time anchor only; FreeTSA not a qualified CA; simulator only.
- Local-first: verify in temp venv, then ask before any push. Never commit keystore files or secrets.
- Test runner: `python -m unittest <module> -v`. Temp venv python: `C:/Users/DELL/AppData/Local/Temp/wafertrust-fix-SDZNSF/venv/Scripts/python`; run from the temp `demo/` mirror with `PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1`.

## File Structure

- Create `keystore.py` — encrypted-at-rest key custody (one responsibility: persist/load private keys).
- Create `anchor.py` — kernel witness envelope create/verify + DID key parsing (one responsibility: witness anchoring).
- Create `tsa.py` — optional RFC 3161 client wrapper (one responsibility: time anchoring).
- Create `test_custody_anchor.py` — all new tests.
- Modify `fab_gateway.py` — durable identities + witness/TSA export.
- Modify `verify_export.py` — witness verification, pinned trust roots, optional TSA check.
- Modify `demo.py`, `maintenance_demo.py` — anchor scene.
- Modify `requirements.txt`, `.gitignore`, `README.md`, `THREAT_MODEL.md`.
- Create `tsa/freetsa.pem` — pinned FreeTSA certificate (fetched during Task 3).

---

### Task 1: Encrypted keystore

**Files:**
- Create: `keystore.py`
- Test: `test_custody_anchor.py`

**Interfaces:**
- Consumes: kernel `AgentIdentity.generate`, `AgentIdentity.from_private_hex`, `AgentIdentity.private_key_hex`.
- Produces: `KeystoreError(Exception)`; `Keystore(path: str|None, passphrase: str|None)`; `Keystore.load_or_generate(key_id: str) -> AgentIdentity`; `Keystore.save() -> None`. Ephemeral when `path is None` or `passphrase is None`.

- [ ] **Step 1: Write failing tests**

```python
# test_custody_anchor.py
from __future__ import annotations
import os, tempfile, unittest
from keystore import Keystore, KeystoreError

class KeystoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "keys.json")
    def tearDown(self):
        self._tmp.cleanup()

    def test_roundtrip_persists_same_key(self):
        ks = Keystore(self.path, "correct horse")
        a = ks.load_or_generate("agent-1"); ks.save()
        ks2 = Keystore(self.path, "correct horse")
        b = ks2.load_or_generate("agent-1")
        self.assertEqual(a.public_key_hex, b.public_key_hex)

    def test_wrong_passphrase_fails_closed(self):
        ks = Keystore(self.path, "right"); ks.load_or_generate("a"); ks.save()
        with self.assertRaises(KeystoreError):
            Keystore(self.path, "wrong")

    def test_ciphertext_has_no_plaintext_key(self):
        ks = Keystore(self.path, "pw"); ident = ks.load_or_generate("a"); ks.save()
        blob = open(self.path, encoding="utf-8").read()
        self.assertNotIn(ident.private_key_hex, blob)

    def test_ephemeral_writes_no_file(self):
        ks = Keystore(None, None)
        ks.load_or_generate("a"); ks.save()
        self.assertFalse(os.path.exists(self.path))
```

- [ ] **Step 2: Run, verify FAIL** — `python -m unittest test_custody_anchor.KeystoreCase -v` → ModuleNotFoundError: keystore.

- [ ] **Step 3: Implement `keystore.py`**

```python
"""Encrypted-at-rest custody for Ed25519 private keys (demo-grade, not an HSM)."""
from __future__ import annotations
import json, os, tempfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from src.governance import AgentIdentity

class KeystoreError(Exception):
    pass

class Keystore:
    def __init__(self, path, passphrase):
        self.path = path
        self.passphrase = passphrase
        self._keys: dict[str, str] = {}
        self._ephemeral = path is None or passphrase is None
        if not self._ephemeral and os.path.exists(path):
            self._load()

    def _derive(self, salt: bytes) -> bytes:
        return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(self.passphrase.encode())

    def _load(self):
        try:
            doc = json.load(open(self.path, encoding="utf-8"))
            k = doc["kdf"]
            key = Scrypt(salt=bytes.fromhex(k["salt"]), length=32,
                         n=k["n"], r=k["r"], p=k["p"]).derive(self.passphrase.encode())
            plain = AESGCM(key).decrypt(bytes.fromhex(doc["nonce"]),
                                        bytes.fromhex(doc["ciphertext"]), None)
            self._keys = json.loads(plain)
        except Exception as exc:
            raise KeystoreError("cannot open keystore (wrong passphrase or corrupt file)") from exc

    def load_or_generate(self, key_id: str) -> AgentIdentity:
        if key_id in self._keys:
            return AgentIdentity.from_private_hex(key_id, self._keys[key_id])
        ident = AgentIdentity.generate(key_id)
        self._keys[key_id] = ident.private_key_hex
        return ident

    def save(self):
        if self._ephemeral:
            return
        salt = os.urandom(16)
        key = self._derive(salt)
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(self._keys).encode(), None)
        doc = {"version": 1, "kdf": {"salt": salt.hex(), "n": 2**14, "r": 8, "p": 1},
               "nonce": nonce.hex(), "ciphertext": ct.hex()}
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        os.replace(tmp, self.path)
```

- [ ] **Step 4: Run, verify PASS** — `python -m unittest test_custody_anchor.KeystoreCase -v` → 4 OK.
- [ ] **Step 5: Commit** — `git add keystore.py test_custody_anchor.py && git commit -m "feat: encrypted-at-rest key custody (keystore)"`

---

### Task 2: Witness anchor wrapper

**Files:**
- Create: `anchor.py`
- Test: `test_custody_anchor.py` (append `AnchorCase`)

**Interfaces:**
- Consumes: kernel `external_anchor.create_witness_statement`, `verify_anchored_audit`, `checkpoint_digest`; `AgentIdentity`.
- Produces: `create_witness(checkpoint: dict, witness_identity: AgentIdentity, *, anchor_reference: str) -> dict`; `verify_anchor(records: list, checkpoint: dict, witness: dict, *, operator_key_hex: str, witness_key_hex: str) -> dict`; `witness_key_from_did(witness_id: str) -> str`; re-exports `checkpoint_digest`.

- [ ] **Step 1: Write failing tests** (build a real 2-entry chain via AuditLog + InMemoryStore, sign checkpoint with operator, witness with independent key)

```python
from src.governance import AuditLog, AgentIdentity
from src.governance.store import InMemoryStore
import anchor

def _chain_with_checkpoint():
    audit = AuditLog(InMemoryStore())
    audit.append(actor="a", action="allow", capability="get_equipment_status",
                 decision="allow", reason="authorized", cost=0)
    op = AgentIdentity.generate("op")
    cp = audit.checkpoint(op.sign, op.public_key_hex)
    records = [e.__dict__ for e in audit.entries()]
    return audit, cp, op, records

class AnchorCase(unittest.TestCase):
    def test_witness_verifies_and_requires_independent_key(self):
        audit, cp, op, records = _chain_with_checkpoint()
        wit = AgentIdentity.generate("wit")
        w = anchor.create_witness(cp, wit, anchor_reference="local-witness-only")
        res = anchor.verify_anchor(records, cp, w, operator_key_hex=op.public_key_hex,
                                   witness_key_hex=wit.public_key_hex)
        self.assertTrue(res["verified"])
        with self.assertRaises(Exception):
            anchor.verify_anchor(records, cp, w, operator_key_hex=op.public_key_hex,
                                 witness_key_hex=op.public_key_hex)  # same key rejected

    def test_truncated_chain_fails(self):
        audit, cp, op, records = _chain_with_checkpoint()
        wit = AgentIdentity.generate("wit")
        w = anchor.create_witness(cp, wit, anchor_reference="local-witness-only")
        with self.assertRaises(Exception):
            anchor.verify_anchor(records[:-1], cp, w, operator_key_hex=op.public_key_hex,
                                 witness_key_hex=wit.public_key_hex)

    def test_did_key_parse(self):
        wit = AgentIdentity.generate("wit")
        self.assertEqual(anchor.witness_key_from_did(wit.did), wit.public_key_hex)
```

NOTE: confirm `AuditLog.append` signature against the kernel before finalizing the helper; adjust field names to the real API (read `src/governance/audit.py`). The test must build a genuine chain, not a mock.

- [ ] **Step 2: Run, verify FAIL** — ModuleNotFoundError: anchor.
- [ ] **Step 3: Implement `anchor.py`**

```python
"""Independent-witness anchoring over the kernel's external_anchor protocol."""
from __future__ import annotations
from datetime import datetime, timezone
from src.governance import AgentIdentity
from src.governance.external_anchor import (
    create_witness_statement, verify_anchored_audit, checkpoint_digest,
)

def witness_key_from_did(witness_id: str) -> str:
    prefix = "did:key:ed25519:"
    if not witness_id.startswith(prefix):
        raise ValueError("witness_id is not an ed25519 did:key")
    return witness_id[len(prefix):]

def create_witness(checkpoint: dict, witness_identity: AgentIdentity, *, anchor_reference: str) -> dict:
    return create_witness_statement(
        checkpoint, witness_id=witness_identity.did,
        witnessed_at=datetime.now(timezone.utc).isoformat(),
        anchor_reference=anchor_reference, sign=witness_identity.sign)

def verify_anchor(records, checkpoint, witness, *, operator_key_hex, witness_key_hex) -> dict:
    return verify_anchored_audit(records, checkpoint, witness,
                                 checkpoint_key_hex=operator_key_hex,
                                 witness_key_hex=witness_key_hex)
```

- [ ] **Step 4: Run, verify PASS** — `python -m unittest test_custody_anchor.AnchorCase -v` → 3 OK.
- [ ] **Step 5: Commit** — `git add anchor.py test_custody_anchor.py && git commit -m "feat: independent-witness anchor wrapper over kernel external_anchor"`

---

### Task 3: Optional RFC 3161 TSA adapter (mocked)

**Files:**
- Create: `tsa.py`, `tsa/freetsa.pem`
- Modify: `requirements.txt`
- Test: `test_custody_anchor.py` (append `TsaCase`)

**Interfaces:**
- Consumes: `rfc3161ng.RemoteTimestamper` (optional import).
- Produces: `TsaError(Exception)`; `TsaClient(url: str, certificate_pem: bytes, hashname: str="sha256")`; `TsaClient.timestamp(data: bytes) -> bytes`; `TsaClient.verify(token: bytes, data: bytes) -> bool`; `TSA_AVAILABLE: bool`.

- [ ] **Step 1: Pin FreeTSA cert** — fetch `https://freetsa.org/files/cacert.pem` (and TSA cert if separate) into `tsa/freetsa.pem`. If unreachable, document and use a placeholder-free path: tests mock the client so the cert is only needed for live use. Record the source URL in a comment.
- [ ] **Step 2: Write failing tests (mock RemoteTimestamper)**

```python
from unittest import mock
import tsa

class TsaCase(unittest.TestCase):
    def test_timestamp_and_verify_success(self):
        fake = mock.Mock()
        fake.timestamp.return_value = b"TOKEN"
        fake.check.return_value = True
        with mock.patch.object(tsa, "RemoteTimestamper", return_value=fake):
            c = tsa.TsaClient("https://freetsa.org/tsr", b"CERT")
            tok = c.timestamp(b"digest")
            self.assertEqual(tok, b"TOKEN")
            self.assertTrue(c.verify(tok, b"digest"))

    def test_network_failure_raises_tsaerror(self):
        fake = mock.Mock()
        fake.timestamp.side_effect = OSError("network down")
        with mock.patch.object(tsa, "RemoteTimestamper", return_value=fake):
            c = tsa.TsaClient("https://freetsa.org/tsr", b"CERT")
            with self.assertRaises(tsa.TsaError):
                c.timestamp(b"digest")
```

- [ ] **Step 3: Run, verify FAIL** — ModuleNotFoundError: tsa.
- [ ] **Step 4: Implement `tsa.py`**

```python
"""Optional RFC 3161 time anchor. Network only when explicitly used; mocked in tests."""
from __future__ import annotations
try:
    from rfc3161ng import RemoteTimestamper
    TSA_AVAILABLE = True
except ImportError:  # optional dependency
    RemoteTimestamper = None
    TSA_AVAILABLE = False

class TsaError(Exception):
    pass

class TsaClient:
    def __init__(self, url: str, certificate_pem: bytes, hashname: str = "sha256"):
        if not TSA_AVAILABLE:
            raise TsaError("rfc3161ng not installed; TSA anchoring unavailable")
        self.url = url
        self._rt = RemoteTimestamper(url, certificate=certificate_pem, hashname=hashname)

    def timestamp(self, data: bytes) -> bytes:
        try:
            return self._rt.timestamp(data=data, return_tsr=True)
        except Exception as exc:
            raise TsaError(f"timestamp request failed: {exc}") from exc

    def verify(self, token: bytes, data: bytes) -> bool:
        try:
            return bool(self._rt.check(token, data=data))
        except Exception:
            return False
```

NOTE: `return_tsr=True` returns the raw response object; confirm whether `.timestamp(..., return_tsr=True)` yields bytes or an ASN.1 object and serialize with `pyasn1.codec.der.encoder.encode` if needed. Adjust `timestamp` to always return DER bytes; verify against the real library during this task.

- [ ] **Step 5: Add optional dep** — append to `requirements.txt`:
```
# Optional: RFC 3161 TSA time anchoring (tsa.py). Not needed for tests/CI (mocked).
rfc3161ng==2.1.3
```
- [ ] **Step 6: Run, verify PASS** — `python -m unittest test_custody_anchor.TsaCase -v` → 2 OK.
- [ ] **Step 7: Commit** — `git add tsa.py tsa/freetsa.pem requirements.txt test_custody_anchor.py && git commit -m "feat: optional RFC 3161 TSA adapter (mocked in tests)"`

---

### Task 4: Gateway integration (durable keys + witness/TSA export)

**Files:**
- Modify: `fab_gateway.py`
- Test: `test_custody_anchor.py` (append `GatewayCustodyCase`)

**Interfaces:**
- Consumes: `Keystore`, `anchor.create_witness`, `anchor.checkpoint_digest`, `TsaClient`, `TsaError`.
- Produces: `FabGovernanceGateway(..., keystore=None, tsa_client=None)`; `self.witness` identity; `export_flight_recorder` returns paths plus `"witness"`, `"anchor"`, and optionally `"tsa_token"`.

- [ ] **Step 1: Write failing tests**

```python
from equipment import SecsGemEquipment
from fab_gateway import FabGovernanceGateway

class GatewayCustodyCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "g.sqlite3")
        self.ks = os.path.join(self._tmp.name, "keys.json")
    def tearDown(self):
        self._tmp.cleanup()

    def test_durable_identity_across_restart(self):
        k = Keystore(self.ks, "pw")
        g1 = FabGovernanceGateway(SecsGemEquipment(), db_path=self.db, keystore=k)
        pub = g1.identity.public_key_hex
        g1.gw.identities.store.close()
        k2 = Keystore(self.ks, "pw")
        g2 = FabGovernanceGateway(SecsGemEquipment(), db_path=self.db, keystore=k2)
        self.assertEqual(pub, g2.identity.public_key_hex)
        g2.gw.identities.store.close()

    def test_export_witness_and_anchor_flag(self):
        g = FabGovernanceGateway(SecsGemEquipment(), db_path=self.db)
        run(g.governed_call("get_equipment_status", {}))
        paths = g.export_flight_recorder(self._tmp.name, "audit")
        self.assertIn("witness", paths); self.assertIn("anchor", paths)
        meta = json.load(open(paths["anchor"], encoding="utf-8"))
        self.assertFalse(meta["independently_time_anchored"])  # no TSA client
        g.gw.identities.store.close()
```

(`run` = `asyncio.run`; import asyncio, json at top of test file.)

- [ ] **Step 2: Run, verify FAIL** — TypeError: unexpected keyword 'keystore'.
- [ ] **Step 3: Modify `fab_gateway.py`**
  - Add imports: `from keystore import Keystore`; `import anchor`; `from tsa import TsaClient, TsaError`.
  - Extend `__init__` signature with `keystore=None, tsa_client=None`; store `self.tsa_client = tsa_client`.
  - Replace identity creation:
```python
if keystore is not None:
    self.identity = keystore.load_or_generate(agent_id)
    self.operator = keystore.load_or_generate(agent_id + ":operator")
    self.witness = keystore.load_or_generate(agent_id + ":witness")
else:
    self.identity = AgentIdentity.generate(agent_id)
    self.operator = AgentIdentity.generate(agent_id + ":operator")
    self.witness = AgentIdentity.generate(agent_id + ":witness")
```
  - In `export_flight_recorder`, after writing checkpoint, add:
```python
paths["witness"] = os.path.join(out_dir, f"{stem}-witness.json")
paths["anchor"] = os.path.join(out_dir, f"{stem}-anchor.json")
anchor_ref, time_anchored = "local-witness-only", False
if self.tsa_client is not None:
    digest = anchor.checkpoint_digest(checkpoint).encode("utf-8")
    try:
        token = self.tsa_client.timestamp(digest)
        if self.tsa_client.verify(token, digest):
            paths["tsa_token"] = os.path.join(out_dir, f"{stem}-tsa-token.der")
            with open(paths["tsa_token"], "wb") as fh:
                fh.write(token)
            anchor_ref, time_anchored = f"tsa:{self.tsa_client.url}", True
    except TsaError:
        pass
witness = anchor.create_witness(checkpoint, self.witness, anchor_reference=anchor_ref)
with open(paths["witness"], "w", encoding="utf-8") as fh:
    json.dump(witness, fh, indent=2); fh.write("\n")
with open(paths["anchor"], "w", encoding="utf-8") as fh:
    json.dump({"independently_time_anchored": time_anchored,
               "anchor_reference": anchor_ref,
               "operator_key_hex": self.operator.public_key_hex,
               "witness_key_hex": self.witness.public_key_hex}, fh, indent=2)
    fh.write("\n")
```
- [ ] **Step 4: Run new tests AND existing 14** — `python -m unittest test_custody_anchor test_hardening -v` → all OK (14 unchanged + new).
- [ ] **Step 5: Commit** — `git add fab_gateway.py test_custody_anchor.py && git commit -m "feat: durable identities + witness/TSA export in gateway"`

---

### Task 5: Verifier extension (witness + pinned roots + optional TSA)

**Files:**
- Modify: `verify_export.py`
- Test: `test_custody_anchor.py` (append `VerifyExportCase`)

**Interfaces:**
- Consumes: `anchor.verify_anchor`, `anchor.witness_key_from_did`, `tsa.TsaClient`, `tsa.TSA_AVAILABLE`.
- Produces: `verify(stem, directory=_HERE, operator_key=None, witness_key=None) -> bool`; CLI flags `--operator-key`, `--witness-key`.

- [ ] **Step 1: Write failing test** (export via gateway, then verify with pinned keys returns True; tampered witness fails)

```python
import verify_export

class VerifyExportCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "g.sqlite3")
    def tearDown(self):
        self._tmp.cleanup()

    def test_verify_with_pinned_roots(self):
        g = FabGovernanceGateway(SecsGemEquipment(), db_path=self.db)
        run(g.governed_call("get_equipment_status", {}))
        g.export_flight_recorder(self._tmp.name, "audit")
        meta = json.load(open(os.path.join(self._tmp.name, "audit-anchor.json"), encoding="utf-8"))
        ok = verify_export.verify("audit", self._tmp.name,
                                  operator_key=meta["operator_key_hex"],
                                  witness_key=meta["witness_key_hex"])
        self.assertTrue(ok)
        g.gw.identities.store.close()
```

- [ ] **Step 2: Run, verify FAIL** — TypeError: unexpected keyword 'operator_key'.
- [ ] **Step 3: Modify `verify_export.py`**
  - Import `anchor`, and `from tsa import TsaClient, TSA_AVAILABLE, TsaError`.
  - Extend `verify` signature; after existing checks, if `{stem}-witness.json` exists:
```python
wpath = os.path.join(directory, f"{stem}-witness.json")
witness_ok = True
if os.path.exists(wpath):
    witness = json.load(open(wpath, encoding="utf-8"))
    pinned = operator_key is not None and witness_key is not None
    op_hex = operator_key if pinned else checkpoint["public_key_hex"]
    wit_hex = witness_key if pinned else anchor.witness_key_from_did(witness["witness_id"])
    if not pinned:
        print("  WARNING: self-consistency only — trust roots not independently pinned")
    try:
        anchor.verify_anchor(records, checkpoint, witness,
                             operator_key_hex=op_hex, witness_key_hex=wit_hex)
        print("  independent witness verified: True")
    except Exception as exc:
        witness_ok = False
        print(f"  independent witness verified: False ({exc})")
    ok = ok and witness_ok
```
  - TSA: if `{stem}-tsa-token.der` exists and `TSA_AVAILABLE` and a cert is available, verify against `anchor.checkpoint_digest(checkpoint).encode()`; print `independently_time_anchored`. Absent → print `independently_time_anchored: False (witness-only)`.
  - Update `__main__` to parse `--operator-key`/`--witness-key` (argparse) alongside positional stem/directory.
- [ ] **Step 4: Run, verify PASS** — `python -m unittest test_custody_anchor.VerifyExportCase -v` → OK; re-run `test_hardening` → 14 OK.
- [ ] **Step 5: Commit** — `git add verify_export.py test_custody_anchor.py && git commit -m "feat: verify witness anchor with pinned trust roots + optional TSA"`

---

### Task 6: Demo scenes, docs, ignore rules, full verification

**Files:**
- Modify: `demo.py`, `maintenance_demo.py`, `.gitignore`, `README.md`, `THREAT_MODEL.md`

- [ ] **Step 1: Add anchor scene** — in `demo.py` after the checkpoint print (line ~132), add:
```python
    wpath = paths.get("witness")
    if wpath:
        import anchor
        witness = json.load(open(wpath, encoding="utf-8"))
        meta = json.load(open(paths["anchor"], encoding="utf-8"))
        ok = True
        try:
            anchor.verify_anchor(records, checkpoint, witness,
                                 operator_key_hex=meta["operator_key_hex"],
                                 witness_key_hex=meta["witness_key_hex"])
        except Exception:
            ok = False
        print(f"  Independent witness over checkpoint: verified {ok}")
        print(f"  Independently time-anchored (TSA): {meta['independently_time_anchored']}")
```
Mirror the same block in `maintenance_demo.py` after its checkpoint print.
- [ ] **Step 2: `.gitignore`** — append:
```
*.keystore.json
keys.json
```
(Do NOT ignore `*-witness.json`, `*-anchor.json`, `*-tsa-token.der` — they are shareable evidence.)
- [ ] **Step 3: Docs** — README: add a "Durable keys + anchored checkpoints" subsection (encrypted keystore, independent witness, optional TSA, honest limits) and update the Artifacts list with the new files. THREAT_MODEL: update §5 non-goals (keys now encrypted-at-rest but still not HSM; offline witness ≠ independent custody; TSA = independent time anchor, FreeTSA not qualified) and §7.
- [ ] **Step 4: Full local verification (temp venv mirror)** — sync repo `*.py` + new modules to temp `demo/`, then run:
  - `python -m unittest test_hardening test_custody_anchor -v` → all OK
  - `python demo.py` and `python maintenance_demo.py` → exit 0, anchor scene prints
  - `python verify_export.py audit` and `... maintenance` → RESULT: PASS
- [ ] **Step 5: Commit** — `git add demo.py maintenance_demo.py .gitignore README.md THREAT_MODEL.md && git commit -m "feat: demo anchor scene + docs for durable keys and anchored checkpoints"`
- [ ] **Step 6: Present batch for push approval** — do NOT push without explicit user approval.

---

## Self-Review

- **Spec coverage:** keystore (T1), witness anchor (T2), optional TSA (T3), durable gateway identities + export (T4), verifier pinned roots + TSA (T5), demos/docs/ignore (T6). All spec sections mapped.
- **Placeholders:** two NOTE items (AuditLog.append signature; rfc3161ng return_tsr serialization) are explicit verify-during-task instructions against real APIs, not deferred design — resolved in-task by reading the kernel/library.
- **Type consistency:** `Keystore.load_or_generate`, `anchor.create_witness/verify_anchor/witness_key_from_did/checkpoint_digest`, `TsaClient.timestamp/verify`, `verify(...operator_key,witness_key)`, gateway `keystore`/`tsa_client`/`self.witness`, paths keys `witness`/`anchor`/`tsa_token` are used identically across tasks.