"""Tests for the real HSMS/SECS-II wire path (#33).

Offline mapping unit tests + loopback integration tests (sim in-process + host
adapter on a free TCP port). The endpoint is a SOFTWARE SIMULATOR, not real equipment.
"""
from __future__ import annotations

import socket
import unittest

from secs_equipment_sim import SecsEquipmentSim, SV_MODEL, EC_MODEL
from secsgem.secs.functions import (SecsS01F02, SecsS01F04, SecsS02F16, SecsS02F42)
from hsms_equipment import (decode_online_data, decode_sv_values, decode_eac,
                            decode_hcack, HsmsError, HsmsEquipment, DEMO_SVIDS, DEMO_ECIDS)


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_host(port: int):
    from secsgem.hsms import HsmsSettings, HsmsConnectMode, DeviceType
    from secsgem.secs import SecsHandler
    s = HsmsSettings(address="127.0.0.1", port=port,
                     connect_mode=HsmsConnectMode.ACTIVE, device_type=DeviceType.HOST)
    return SecsHandler(s)


def wait_selected(handler, timeout=6.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        csm = handler.protocol.connection_state
        cs = getattr(csm, "current_state", None)
        name = getattr(cs, "name", str(cs))
        if "SELECTED" in name.upper():
            return True
        time.sleep(0.05)
    return False


class SimReadPath(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.sim = SecsEquipmentSim(port=self.port)
        self.sim.start()
        self.assertTrue(self.sim.wait_ready(5.0))
        self.host = make_host(self.port)
        self.host.enable()
        self.assertTrue(wait_selected(self.host), "HSMS link not selected")

    def tearDown(self):
        self.host.disable()
        self.sim.stop()

    def _decode(self, resp):
        return self.host.settings.streams_functions.decode(resp)

    def test_s1f1_returns_online_data(self):
        fn = self._decode(self.host.send_and_waitfor_response(self.host.stream_function(1, 1)()))
        self.assertEqual(fn.data.data[0].get(), "WaferTrustSim")
        self.assertEqual(fn.data.data[1].get(), "1.0")

    def test_s1f3_returns_requested_sv_values_in_order(self):
        fn = self._decode(self.host.send_and_waitfor_response(
            self.host.stream_function(1, 3)([1002, 1001])))
        vals = [v.get() for v in fn.data.data]
        self.assertEqual(vals, [SV_MODEL[1002][1], SV_MODEL[1001][1]])

    def test_s2f13_returns_requested_ec_values_in_order(self):
        fn = self._decode(self.host.send_and_waitfor_response(
            self.host.stream_function(2, 13)([2001])))
        vals = [v.get() for v in fn.data.data]
        self.assertEqual(vals, [EC_MODEL[2001][1]])


class SimWritePath(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.sim = SecsEquipmentSim(port=self.port)
        self.sim.start()
        self.assertTrue(self.sim.wait_ready(5.0))
        self.host = make_host(self.port)
        self.host.enable()
        self.assertTrue(wait_selected(self.host))

    def tearDown(self):
        self.host.disable()
        self.sim.stop()

    def _decode(self, resp):
        return self.host.settings.streams_functions.decode(resp)

    def test_in_range_ec_write_acks_and_changes_state(self):
        fn = self._decode(self.host.send_and_waitfor_response(
            self.host.stream_function(2, 15)([{"ECID": 2001, "ECV": 400.0}])))
        self.assertEqual(fn.data.get(), 0)            # EAC = 0 (accepted)
        self.assertEqual(self.sim.ec[2001], 400.0)

    def test_out_of_range_ec_write_rejects_and_keeps_state(self):
        before = self.sim.ec[2001]
        fn = self._decode(self.host.send_and_waitfor_response(
            self.host.stream_function(2, 15)([{"ECID": 2001, "ECV": 500.0}])))
        self.assertEqual(fn.data.get(), 1)            # EAC = 1 (rejected)
        self.assertEqual(self.sim.ec[2001], before)   # unchanged
        self.assertGreater(self.sim.scrapped_wafers, 0)

    def test_host_command_abort_acks(self):
        fn = self._decode(self.host.send_and_waitfor_response(
            self.host.stream_function(2, 41)({"RCMD": "ABORT", "PARAMS": []})))
        self.assertEqual(fn.data.data["HCACK"].get(), 0)

    def test_unknown_command_rejected(self):
        fn = self._decode(self.host.send_and_waitfor_response(
            self.host.stream_function(2, 41)({"RCMD": "BOGUS", "PARAMS": []})))
        self.assertEqual(fn.data.data["HCACK"].get(), 1)


class DecodeHelpers(unittest.TestCase):
    def test_decode_online_data(self):
        self.assertEqual(decode_online_data(SecsS01F02(["WaferTrustSim", "1.0"])),
                         ("WaferTrustSim", "1.0"))

    def test_decode_sv_values(self):
        self.assertEqual(decode_sv_values(SecsS01F04([1250, 350, 100])), [1250, 350, 100])

    def test_decode_eac(self):
        self.assertEqual(decode_eac(SecsS02F16(0)), 0)
        self.assertEqual(decode_eac(SecsS02F16(1)), 1)

    def test_decode_hcack(self):
        self.assertEqual(decode_hcack(SecsS02F42({"HCACK": 0, "PARAMS": []})), 0)


class AdapterLoopback(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.sim = SecsEquipmentSim(port=self.port)
        self.sim.start()
        self.assertTrue(self.sim.wait_ready(5.0))
        self.eq = HsmsEquipment(port=self.port)

    def tearDown(self):
        self.eq.close()
        self.sim.stop()

    def test_get_equipment_status(self):
        res = self.eq.dispatch("get_equipment_status", {})
        self.assertEqual(res["communicationState"], "COMMUNICATING")
        self.assertEqual(res["mdlrn"], "WaferTrustSim")

    def test_get_status_variable(self):
        res = self.eq.dispatch("get_status_variable", {"svid": 1002})
        self.assertEqual(res, {"svid": 1002, "value": 350})

    def test_list_equipment_constants(self):
        res = self.eq.dispatch("list_equipment_constants", {})
        self.assertEqual(res["equipmentConstants"],
                         [{"ecid": e, "value": self.sim.ec[e]} for e in DEMO_ECIDS])

    def test_set_equipment_constant_in_range(self):
        res = self.eq.dispatch("set_equipment_constant", {"ecid": 2001, "value": 400})
        self.assertEqual(res, {"ok": True, "ecid": 2001, "value": 400.0})
        self.assertEqual(self.sim.ec[2001], 400.0)

    def test_set_equipment_constant_out_of_range(self):
        res = self.eq.dispatch("set_equipment_constant", {"ecid": 2001, "value": 500})
        self.assertFalse(res["ok"])
        self.assertEqual(res["ecid"], 2001)

    def test_execute_command(self):
        res = self.eq.dispatch("execute_command", {"command": "ONLINE"})
        self.assertEqual(res, {"ok": True, "command": "ONLINE"})

    def test_unsupported_tool_raises(self):
        with self.assertRaises(HsmsError):
            self.eq.dispatch("manage_carrier", {"action": "load", "carrier_id": "C1"})


class AdapterFailClosed(unittest.TestCase):
    def test_connect_failure_raises(self):
        port = free_port()  # nothing listening
        with self.assertRaises(HsmsError):
            HsmsEquipment(port=port, connect_timeout=1.0)


if __name__ == "__main__":
    unittest.main()