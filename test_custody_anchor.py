"""Custody + anchoring tests for WaferTrust #34.

Run with the PUBLIC AgentBridge kernel cloned as the sibling ../agentbridge:
    python -m unittest test_custody_anchor -v
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from unittest import mock

from keystore import Keystore, KeystoreError
from src.governance import AgentIdentity, AuditLog
from src.governance.store import InMemoryStore
import anchor
import tsa
from equipment import SecsGemEquipment
from fab_gateway import FabGovernanceGateway
import verify_export


def run(coro):
    return asyncio.run(coro)


def _chain_with_checkpoint():
    audit = AuditLog(InMemoryStore())
    audit.record(actor="a", action="route_call", source_protocol="mcp",
                 target_protocol="mcp", capability="get_equipment_status",
                 decision="allow", reason="authorized", cost=0)
    op = AgentIdentity.generate("op")
    cp = audit.checkpoint(op.sign, op.public_key_hex)
    records = [asdict(e) for e in audit.entries()]
    return audit, cp, op, records


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
                                 witness_key_hex=op.public_key_hex)

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


class GatewayCustodyCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "g.sqlite3")
        self.ks = os.path.join(self._tmp.name, "keys.json")
        self._gateways = []

    def _gw(self, **kw):
        g = FabGovernanceGateway(SecsGemEquipment(), db_path=self.db, **kw)
        self._gateways.append(g)
        return g

    def tearDown(self):
        for g in self._gateways:
            try:
                g.gw.identities.store.close()
            except Exception:
                pass
        self._tmp.cleanup()

    def test_durable_identity_across_restart(self):
        k = Keystore(self.ks, "pw")
        g1 = self._gw(keystore=k)
        pub = g1.identity.public_key_hex
        g1.gw.identities.store.close()
        k2 = Keystore(self.ks, "pw")
        g2 = self._gw(keystore=k2)
        self.assertEqual(pub, g2.identity.public_key_hex)

    def test_export_witness_and_anchor_flag(self):
        g = self._gw()
        run(g.governed_call("get_equipment_status", {}))
        paths = g.export_flight_recorder(self._tmp.name, "audit")
        self.assertIn("witness", paths)
        self.assertIn("anchor", paths)
        with open(paths["anchor"], encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertFalse(meta["independently_time_anchored"])


class VerifyExportCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "g.sqlite3")
        self._gateways = []

    def _gw(self, **kw):
        g = FabGovernanceGateway(SecsGemEquipment(), db_path=self.db, **kw)
        self._gateways.append(g)
        return g

    def tearDown(self):
        for g in self._gateways:
            try:
                g.gw.identities.store.close()
            except Exception:
                pass
        self._tmp.cleanup()

    def _export(self):
        g = self._gw()
        run(g.governed_call("get_equipment_status", {}))
        g.export_flight_recorder(self._tmp.name, "audit")
        with open(os.path.join(self._tmp.name, "audit-anchor.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_verify_with_pinned_roots(self):
        meta = self._export()
        ok = verify_export.verify("audit", self._tmp.name,
                                  operator_key=meta["operator_key_hex"],
                                  witness_key=meta["witness_key_hex"])
        self.assertTrue(ok)

    def test_tampered_witness_fails(self):
        meta = self._export()
        wpath = os.path.join(self._tmp.name, "audit-witness.json")
        with open(wpath, encoding="utf-8") as fh:
            witness = json.load(fh)
        witness["signature_hex"] = "00" * 64
        with open(wpath, "w", encoding="utf-8") as fh:
            json.dump(witness, fh)
        ok = verify_export.verify("audit", self._tmp.name,
                                  operator_key=meta["operator_key_hex"],
                                  witness_key=meta["witness_key_hex"])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()