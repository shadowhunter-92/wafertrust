"""Custody + anchoring tests for WaferTrust #34.

Run with the PUBLIC AgentBridge kernel cloned as the sibling ../agentbridge:
    python -m unittest test_custody_anchor -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from keystore import Keystore, KeystoreError


class KeystoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "keys.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_roundtrip_persists_same_key(self):
        ks = Keystore(self.path, "correct horse")
        a = ks.load_or_generate("agent-1")
        ks.save()
        ks2 = Keystore(self.path, "correct horse")
        b = ks2.load_or_generate("agent-1")
        self.assertEqual(a.public_key_hex, b.public_key_hex)

    def test_wrong_passphrase_fails_closed(self):
        ks = Keystore(self.path, "right")
        ks.load_or_generate("a")
        ks.save()
        with self.assertRaises(KeystoreError):
            Keystore(self.path, "wrong")

    def test_ciphertext_has_no_plaintext_key(self):
        ks = Keystore(self.path, "pw")
        ident = ks.load_or_generate("a")
        ks.save()
        with open(self.path, encoding="utf-8") as fh:
            blob = fh.read()
        self.assertNotIn(ident.private_key_hex, blob)

    def test_ephemeral_writes_no_file(self):
        ks = Keystore(None, None)
        ks.load_or_generate("a")
        ks.save()
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()