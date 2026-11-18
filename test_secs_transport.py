"""Tests for the real HSMS/SECS-II wire path (#33).

Offline mapping unit tests + loopback integration tests (sim in-process + host
adapter on a free TCP port). The endpoint is a SOFTWARE SIMULATOR, not real equipment.
"""
from __future__ import annotations

import socket
import unittest

from secs_equipment_sim import SecsEquipmentSim, SV_MODEL, EC_MODEL


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


if __name__ == "__main__":
    unittest.main()