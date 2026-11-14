"""Encrypted-at-rest custody for Ed25519 private keys (demo-grade, not an HSM).

Keys are persisted with AES-256-GCM under a scrypt-derived passphrase key. This
is encryption at rest on the same host — it is NOT an HSM or remote key manager,
and host compromise remains out of scope. Ephemeral mode (no path/passphrase)
keeps keys in memory only, preserving the demo's generate-per-run behavior.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENTBRIDGE = os.path.join(os.path.dirname(_HERE), "agentbridge")
if _AGENTBRIDGE not in sys.path:
    sys.path.insert(0, _AGENTBRIDGE)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt  # noqa: E402
from src.governance import AgentIdentity  # noqa: E402

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


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

    def _derive(self, salt: bytes, params: dict) -> bytes:
        return Scrypt(salt=salt, length=32, n=params["n"], r=params["r"],
                      p=params["p"]).derive(self.passphrase.encode())

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                doc = json.load(fh)
            k = doc["kdf"]
            key = self._derive(bytes.fromhex(k["salt"]), k)
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
        key = self._derive(salt, _SCRYPT)
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(self._keys).encode(), None)
        doc = {"version": 1, "kdf": {"salt": salt.hex(), **_SCRYPT},
               "nonce": nonce.hex(), "ciphertext": ct.hex()}
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        os.replace(tmp, self.path)