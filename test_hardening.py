"""Hardening tests: fail-closed caller authentication, request-bound approvals,
complete independently verifiable audit exports, and signed checkpoints.

Run with the PUBLIC AgentBridge kernel cloned as the sibling ../agentbridge:
    python -m unittest test_hardening -v
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from equipment import SecsGemEquipment
from fab_gateway import FabGovernanceGateway
from src.governance import AgentIdentity, AuditLog, GovernanceError, canonical_payload
from src.governance.operation_ledger import OperationConflict


def run(coro):
    return asyncio.run(coro)


async def _invoke(_wire):
    return {"ok": True}


def _wire(tool, arguments):
    return {"jsonrpc": "2.0", "id": tool, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}


def _proof(agent_id, wire, operation_id, identity, body_wire=None):
    body = json.dumps({"src": "mcp", "dst": "mcp",
                       "wire": wire if body_wire is None else body_wire,
                       "target_id": None, "operation_id": operation_id},
                      sort_keys=True, separators=(",", ":")).encode()
    nonce = "nonce-" + operation_id
    signed_data = canonical_payload(agent_id, nonce, body)
    return {"signed_body": body, "signed_nonce": nonce,
            "signed_data": signed_data, "signature": identity.sign(signed_data)}


class HardeningCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "governance.sqlite3")
        self.gw = FabGovernanceGateway(SecsGemEquipment(), db_path=self.db_path)

    def tearDown(self):
        store = self.gw.gw.identities.store
        close = getattr(store, "close", None)
        if close:
            close()
        self._tmp.cleanup()

    def _direct(self, wire, operation_id, **proof):
        return run(self.gw.gw.route_call(
            agent_id=self.gw.agent_id, src_proto="mcp", dst_proto="mcp",
            src_wire=wire, invoke=_invoke, cost=0, operation_id=operation_id, **proof))

    def test_unsigned_call_is_denied(self):
        with self.assertRaises(GovernanceError) as ctx:
            self._direct(_wire("get_equipment_status", {}), "u" * 32)
        self.assertIn("request-bound signed agent proof required", str(ctx.exception))

    def test_forged_signature_is_denied(self):
        wire = _wire("get_equipment_status", {})
        impostor = AgentIdentity.generate("impostor")
        proof = _proof(self.gw.agent_id, wire, "f" * 32, impostor)
        with self.assertRaises(GovernanceError) as ctx:
            self._direct(wire, "f" * 32, **proof)
        self.assertIn("request-bound signed agent proof required", str(ctx.exception))

    def test_tampered_request_body_is_denied(self):
        ident = AgentIdentity.generate(self.gw.agent_id)
        self.gw.identities.register(ident)
        wire = _wire("get_status_variable", {"svid": 1})
        proof = _proof(self.gw.agent_id, wire, "t" * 32, ident,
                       body_wire=_wire("get_status_variable", {"svid": 999}))
        with self.assertRaises(GovernanceError) as ctx:
            self._direct(wire, "t" * 32, **proof)
        self.assertIn("request-bound signed agent proof required", str(ctx.exception))

    def test_unregistered_agent_is_denied(self):
        ghost = AgentIdentity.generate("ghost-agent")
        wire = _wire("get_equipment_status", {})
        proof = _proof("ghost-agent", wire, "g" * 32, ghost)
        with self.assertRaises(GovernanceError):
            run(self.gw.gw.route_call(
                agent_id="ghost-agent", src_proto="mcp", dst_proto="mcp",
                src_wire=wire, invoke=_invoke, cost=0, operation_id="g" * 32, **proof))

    def test_valid_read_is_allowed(self):
        out = run(self.gw.governed_call("get_equipment_status", {}))
        self.assertTrue(out["allowed"])
        self.assertEqual(out["cost"], 0)

    def test_write_requires_approval_then_same_operation_retry_succeeds(self):
        args = {"ecid": 2001, "value": 400}
        out = run(self.gw.governed_call("set_equipment_constant", args))
        self.assertFalse(out["allowed"])
        self.assertTrue(out["needs_approval"])
        self.assertTrue(self.gw.approve(out["approval_id"]))
        retry = run(self.gw.governed_call("set_equipment_constant", args,
                                          operation_id=out["operation_id"]))
        self.assertTrue(retry["allowed"])
        self.assertEqual(retry["operation_id"], out["operation_id"])

    def test_approval_grant_is_bound_to_the_original_operation(self):
        args = {"ecid": 2001, "value": 400}
        out = run(self.gw.governed_call("set_equipment_constant", args))
        self.assertTrue(self.gw.approve(out["approval_id"]))
        other = run(self.gw.governed_call("set_equipment_constant", args))
        self.assertFalse(other["allowed"])
        self.assertTrue(other["needs_approval"])
        self.assertNotEqual(other["operation_id"], out["operation_id"])

    def test_budget_breaker_denies_even_after_approval(self):
        args = {"ecid": 2001, "value": 400}
        out = run(self.gw.governed_call("set_equipment_constant", args))
        self.gw.approve(out["approval_id"])
        run(self.gw.governed_call("set_equipment_constant", args,
                                  operation_id=out["operation_id"]))
        abort = run(self.gw.governed_call("execute_command", {"command": "ABORT"}))
        self.assertFalse(abort["allowed"])
        self.gw.approve(abort["approval_id"])
        retry = run(self.gw.governed_call("execute_command", {"command": "ABORT"},
                                          operation_id=abort["operation_id"]))
        self.assertFalse(retry["allowed"])
        self.assertIn("spend cap", retry["reason"])

    def test_reusing_a_succeeded_operation_is_rejected(self):
        args = {"ecid": 2001, "value": 400}
        out = run(self.gw.governed_call("set_equipment_constant", args))
        self.gw.approve(out["approval_id"])
        run(self.gw.governed_call("set_equipment_constant", args,
                                  operation_id=out["operation_id"]))
        with self.assertRaises(OperationConflict):
            run(self.gw.governed_call("set_equipment_constant", args,
                                      operation_id=out["operation_id"]))

    def _export(self):
        run(self.gw.governed_call("get_equipment_status", {}))
        run(self.gw.governed_call("list_alarms", {"active_only": True}))
        return self.gw.export_flight_recorder(self._tmp.name, "audit")

    def test_exported_chain_verifies_and_tampering_breaks_it(self):
        paths = self._export()
        with open(paths["jsonl"], encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        self.assertTrue(records)
        for rec in records:
            for field in ("timestamp", "source_protocol", "target_protocol", "prev_hash"):
                self.assertIn(field, rec)
        self.assertTrue(AuditLog.verify_chain(records, require_genesis=True))
        records[0]["reason"] = "edited after the fact"
        self.assertFalse(AuditLog.verify_chain(records, require_genesis=True))

    def test_checkpoint_is_signed_and_tampering_breaks_it(self):
        paths = self._export()
        with open(paths["jsonl"], encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        with open(paths["checkpoint"], encoding="utf-8") as fh:
            checkpoint = json.load(fh)
        self.assertTrue(AuditLog.verify_checkpoint(checkpoint))
        self.assertEqual(checkpoint["head_hash"], records[-1]["entry_hash"])
        self.assertEqual(checkpoint["seq"], len(records))
        tampered = dict(checkpoint, head_hash="0" * 64)
        self.assertFalse(AuditLog.verify_checkpoint(tampered))

    def test_journal_records_arguments_and_links_to_chain(self):
        paths = self._export()
        with open(paths["jsonl"], encoding="utf-8") as fh:
            hashes = {json.loads(line)["entry_hash"] for line in fh if line.strip()}
        with open(paths["journal"], encoding="utf-8") as fh:
            journal = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(journal), 2)
        for rec in journal:
            self.assertIn(rec["entry_hash"], hashes)
            self.assertEqual(rec["wire"]["method"], "tools/call")
            self.assertIn("name", rec["wire"]["params"])


    def test_standalone_verifier_accepts_complete_export(self):
        from verify_export import verify
        self._export()
        self.assertTrue(verify("audit", self._tmp.name))

    def test_standalone_verifier_rejects_tampered_chain(self):
        from verify_export import verify
        paths = self._export()
        with open(paths["jsonl"], encoding="utf-8") as fh:
            lines = fh.readlines()
        record = json.loads(lines[0])
        record["reason"] = "edited after the fact"
        lines[0] = json.dumps(record) + "\n"
        with open(paths["jsonl"], "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        self.assertFalse(verify("audit", self._tmp.name))


if __name__ == "__main__":
    unittest.main()