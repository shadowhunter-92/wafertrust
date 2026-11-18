"""Standalone HSMS / SECS-II equipment SIMULATOR (SEMI E37 passive / EQUIPMENT).

This is a SOFTWARE simulator, not real fab equipment. It speaks real HSMS over TCP
and real SECS-II (SEMI E5) messages so the WaferTrust governance layer can be exercised
against a genuine wire protocol boundary. No production-safety or compliance claim.

Run standalone:  python secs_equipment_sim.py --port 5000
Importable:      SecsEquipmentSim(port=...).start()  (tests run it in-process)

Dependency: secsgem==0.3.0 (LGPL-2.1-or-later), imported not vendored.
"""
from __future__ import annotations

import argparse
import socket
import threading
import time

from secsgem.hsms import HsmsSettings, HsmsConnectMode, DeviceType
from secsgem.secs import SecsHandler

# Demo data model (mirrors equipment.py). (name, value) for SV; (name, value, min, max) for EC.
SV_MODEL = {1001: ("WaferCount", 1250), 1002: ("ChamberTemp", 350), 1003: ("ChamberPressure", 100)}
EC_MODEL = {2001: ("ChamberTempSetpoint", 350.0, 200.0, 450.0),
            2002: ("PressureLimit", 100.0, 50.0, 200.0)}
ACTIVE_LOT_WAFERS = 25
WAFER_VALUE_USD = 20_000


def _install_windows_shutdown_filter() -> None:
    """Suppress ONLY secsgem's cosmetic Windows server-cleanup OSError (WinError
    10057/10038 raised when it shutdown()s the listening socket after accept).
    Real errors are passed to the default hook. Absent on Linux."""
    default_hook = threading.excepthook

    def hook(args):
        exc = args.exc_value
        winerror = getattr(exc, "winerror", None)
        if isinstance(exc, OSError) and winerror in (10057, 10038):
            tb = args.exc_traceback
            frames = []
            while tb is not None:
                frames.append(tb.tb_frame.f_code.co_filename)
                tb = tb.tb_next
            if any("tcp_server_connection" in f for f in frames):
                return
        default_hook(args)

    threading.excepthook = hook


class SecsEquipmentSim:
    def __init__(self, port: int = 5000, address: str = "127.0.0.1") -> None:
        self.port = port
        self.address = address
        self.sv = {k: v[1] for k, v in SV_MODEL.items()}
        self.ec = {k: v[1] for k, v in EC_MODEL.items()}
        self.control_state = "ONLINE"
        self.scrapped_wafers = 0
        self.damage_usd = 0
        self.alarms: list[dict] = []
        settings = HsmsSettings(address=address, port=port,
                                connect_mode=HsmsConnectMode.PASSIVE,
                                device_type=DeviceType.EQUIPMENT)
        self.handler = SecsHandler(settings)
        self.handler.register_stream_function(1, 1, self._on_s1f1)
        self.handler.register_stream_function(1, 3, self._on_s1f3)
        self.handler.register_stream_function(2, 13, self._on_s2f13)

    def _on_s1f1(self, handler, message):
        return handler.stream_function(1, 2)(["WaferTrustSim", "1.0"])

    def _on_s1f3(self, handler, message):
        fn = handler.settings.streams_functions.decode(message)
        svids = [int(v.get()) for v in fn.data.data] or sorted(self.sv)
        return handler.stream_function(1, 4)([self.sv[s] for s in svids])

    def _on_s2f13(self, handler, message):
        fn = handler.settings.streams_functions.decode(message)
        ecids = [int(v.get()) for v in fn.data.data] or sorted(self.ec)
        return handler.stream_function(2, 14)([self.ec[e] for e in ecids])

    def start(self) -> None:
        _install_windows_shutdown_filter()
        self.handler.enable()

    def stop(self) -> None:
        self.handler.disable()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        # The secsgem passive server accepts exactly ONE connection then closes its
        # listening socket, so a raw TCP probe would steal that slot and lock out the
        # real host. Poll the server socket instead of opening a connection.
        conn = self.handler.protocol._connection
        t0 = time.time()
        while time.time() - t0 < timeout:
            if getattr(conn, "_server_sock", None) is not None:
                time.sleep(0.1)  # let bind()/listen() finish in the server thread
                return True
            time.sleep(0.02)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="WaferTrust HSMS equipment simulator (software only).")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--address", default="127.0.0.1")
    args = parser.parse_args()
    sim = SecsEquipmentSim(port=args.port, address=args.address)
    sim.start()
    print(f"WaferTrustSim listening on {args.address}:{args.port} (software simulator). Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())