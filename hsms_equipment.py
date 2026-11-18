"""HSMS host adapter (SEMI E37 active / HOST) implementing the equipment dispatch contract.

Speaks real SECS-II (SEMI E5) over HSMS/TCP to secs_equipment_sim.py (a SOFTWARE
simulator, not real equipment). Same `.dispatch(tool, arguments) -> dict` contract as
equipment.SecsGemEquipment, so the governance gateway is unchanged. Bounded tool subset;
unsupported tools raise HsmsError. No production-safety claim.

Dependency: secsgem==0.3.0 (LGPL-2.1-or-later).
"""
from __future__ import annotations

import time

from secsgem.hsms import HsmsSettings, HsmsConnectMode, DeviceType
from secsgem.secs import SecsHandler

# Demo data-model IDs the adapter queries for list_* tools. A real host discovers IDs
# via S1F11/S2F29 name lists (out of scope for this bounded slice). Standard S1F4/S2F14
# carry positional values only (no IDs/names/units), so we request explicit IDs and zip.
DEMO_SVIDS = [1001, 1002, 1003]
DEMO_ECIDS = [2001, 2002]

SUPPORTED_TOOLS = {
    "get_equipment_status", "get_status_variable", "list_status_variables",
    "list_equipment_constants", "set_equipment_constant", "execute_command",
}


class HsmsError(RuntimeError):
    """HSMS connection or unsupported-tool failure (fail-closed)."""


def decode_online_data(fn) -> tuple[str, str]:
    return (fn.data.data[0].get(), fn.data.data[1].get())


def decode_sv_values(fn) -> list:
    return [v.get() for v in fn.data.data]


def decode_eac(fn) -> int:
    return int(fn.data.get())


def decode_hcack(fn) -> int:
    return int(fn.data.data["HCACK"].get())


class HsmsEquipment:
    def __init__(self, port: int = 5000, address: str = "127.0.0.1",
                 connect_timeout: float = 10.0) -> None:
        settings = HsmsSettings(address=address, port=port,
                                connect_mode=HsmsConnectMode.ACTIVE, device_type=DeviceType.HOST)
        self._handler = SecsHandler(settings)
        self._handler.enable()
        if not self._wait_selected(connect_timeout):
            self._handler.disable()
            raise HsmsError(f"HSMS link not selected within {connect_timeout}s ({address}:{port})")

    def _wait_selected(self, timeout: float) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            csm = self._handler.protocol.connection_state
            cs = getattr(csm, "current_state", None)
            name = getattr(cs, "name", str(cs))
            if "SELECTED" in name.upper():
                return True
            time.sleep(0.05)
        return False

    def _send(self, stream: int, function: int, value):
        klass = self._handler.stream_function(stream, function)
        msg = klass() if value is None else klass(value)
        resp = self._handler.send_and_waitfor_response(msg)
        return self._handler.settings.streams_functions.decode(resp)

    def dispatch(self, tool: str, arguments: dict) -> dict:
        if tool not in SUPPORTED_TOOLS:
            raise HsmsError(f"tool not supported over HSMS: {tool}")
        return getattr(self, "_t_" + tool)(arguments)

    def _t_get_equipment_status(self, args):
        mdln, softrev = decode_online_data(self._send(1, 1, None))
        return {"communicationState": "COMMUNICATING", "mdlrn": mdln, "softrev": softrev}

    def _t_get_status_variable(self, args):
        svid = int(args["svid"])
        vals = decode_sv_values(self._send(1, 3, [svid]))
        return {"svid": svid, "value": vals[0] if vals else None}

    def _t_list_status_variables(self, args):
        vals = decode_sv_values(self._send(1, 3, DEMO_SVIDS))
        return {"statusVariables": [{"svid": s, "value": v} for s, v in zip(DEMO_SVIDS, vals)]}

    def _t_list_equipment_constants(self, args):
        vals = decode_sv_values(self._send(2, 13, DEMO_ECIDS))
        return {"equipmentConstants": [{"ecid": e, "value": v} for e, v in zip(DEMO_ECIDS, vals)]}

    def _t_set_equipment_constant(self, args):
        ecid = int(args["ecid"])
        value = float(args["value"])
        eac = decode_eac(self._send(2, 15, [{"ECID": ecid, "ECV": value}]))
        if eac == 0:
            return {"ok": True, "ecid": ecid, "value": value}
        return {"ok": False, "ecid": ecid, "reason": f"equipment rejected (EAC={eac})"}

    def _t_execute_command(self, args):
        command = str(args["command"]).upper()
        hcack = decode_hcack(self._send(2, 41, {"RCMD": command, "PARAMS": []}))
        if hcack == 0:
            return {"ok": True, "command": command}
        return {"ok": False, "command": command, "reason": f"equipment rejected (HCACK={hcack})"}

    def close(self) -> None:
        self._handler.disable()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()