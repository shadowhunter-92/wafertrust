# Real SECS/GEM HSMS Wire Path (#33) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagents are unavailable in this session, so execute inline with superpowers:executing-plans.

**Goal:** Add a real HSMS/SECS-II transport (via secsgem) for a bounded subset of fab tools, so a governed call crosses a TCP wire to a software equipment simulator, with the governance layer unchanged.

**Architecture:** The gateway already injects an equipment object and calls `.dispatch(tool, arguments)`. We add `HsmsEquipment` (HSMS host adapter) implementing that same contract, and `secs_equipment_sim.py` (HSMS equipment server, separate process / importable thread). All SECS-II mappings are standard secsgem function structures. Governance, kernel, and existing demos are untouched.

**Tech Stack:** Python 3.12, secsgem==0.3.0 (LGPL-2.1-or-later), AgentBridge kernel @ f309a35 (sibling import), stdlib unittest.

**Spec:** `docs/superpowers/specs/2026-11-16-real-secs-gem-hsms-design.md`

## Global Constraints

- Demo repo only (`fab-governance-demo`). NO AgentBridge kernel changes; NEVER touch the `D:\qoder\ASLM EUV\agentbridge` working tree or the shared `.venv`.
- Kernel pinned: `f309a35cb5c3ec4164acea5ba2622dc04be6807c`.
- Dependency pinned: `secsgem==0.3.0`. Python >= 3.11.
- Existing 27 tests (`test_hardening`, `test_custody_anchor`) MUST stay green and unchanged.
- Honesty: endpoint is a SOFTWARE SIMULATOR, not real equipment. No production-safety / compliance / certification / physics claims. LGPL disclosed.
- All SECS-II mappings use STANDARD secsgem function structures (no private wire extensions).
- Uniform scalar accessor is `var.get()` (ASCII→str, numeric→int/float). NEVER use `.value[0]` on ASCII vars (returns first character).
- Local-first: develop + verify in the isolated mirror, sync verified files to the repo feature branch `tier2-real-secs-gem`, re-verify, then push only after local green (user authorized push-after-local-verify).
- No secrets committed. Sim writes no persistent keys.

## Mirror workflow (every code task)

- Mirror demo dir: `C:/Users/DELL/AppData/Local/Temp/wafertrust-fix-SDZNSF/demo`
- Mirror venv python: `C:/Users/DELL/AppData/Local/Temp/wafertrust-fix-SDZNSF/venv/Scripts/python.exe` (has demo deps + secsgem 0.3.0; kernel sibling at `../agentbridge` @ f309a35).
- Develop/test new code in the mirror. After a task is green, copy the changed code files to the repo `D:/qoder/ASLM EUV/fab-governance-demo/` and commit on `tier2-real-secs-gem`.
- Docs (`README.md`, `THREAT_MODEL.md`), `requirements.txt`, and `.github/workflows/tests.yml` are edited directly in the repo (no kernel needed to verify them).
- Run tests from the mirror demo dir so `../agentbridge` resolves: `cd <mirror>/demo && <venv python> -m unittest ...`.
- Windows note: secsgem 0.3.0 raises a cosmetic `OSError WinError 10057/10038` in the server cleanup thread on shutdown. The sim installs a targeted `threading.excepthook` filter (Task 1). Absent on Ubuntu CI.

## File Structure

- Create `secs_equipment_sim.py` — HSMS equipment server: SV/EC state + S1F1/F2, S1F3/F4, S2F13/F14, S2F15/F16, S2F41/F42 handlers; `SecsEquipmentSim.start/stop/wait_ready`; runnable standalone; Windows shutdown filter.
- Create `hsms_equipment.py` — HSMS host adapter: `HsmsError`, `HsmsEquipment(port,address,connect_timeout)` with `.dispatch/.close` + context manager; pure decode helpers (`decode_online_data`, `decode_sv_values`, `decode_eac`, `decode_hcack`) unit-testable offline; demo SVID/ECID constants.
- Create `secs_demo.py` — subprocess sim + governed scenes over the wire + flight-recorder export + honest banner.
- Create `test_secs_transport.py` — offline mapping unit tests + loopback integration tests + gateway-over-wire test.
- Modify `requirements.txt` — add `secsgem==0.3.0` + license comment.
- Modify `README.md` — "Real SECS/GEM wire path (optional)" section + demos table + honesty note.
- Modify `THREAT_MODEL.md` — simulator endpoint + LGPL dependency + non-goals.
- Modify `.github/workflows/tests.yml` — add `test_secs_transport` to unittest list; add `secs_demo.py` run + its export re-verify.

---

### Task 1: Dependency pin + simulator read path

**Files:**
- Modify: `requirements.txt` (repo)
- Create: `secs_equipment_sim.py` (mirror → repo)
- Test: `test_secs_transport.py` (mirror → repo)

**Interfaces:**
- Consumes: secsgem `HsmsSettings, HsmsConnectMode, DeviceType` from `secsgem.hsms`; `SecsHandler` from `secsgem.secs`.
- Produces: `SecsEquipmentSim(port=5000, address="127.0.0.1")` with `.start()`, `.stop()`, `.wait_ready(timeout=5.0)`, `.handler` (the `SecsHandler`), and state dicts `.sv` (svid→value), `.ec` (ecid→value). Read handlers S1F1/F2, S1F3/F4, S2F13/F14. Module constants `SV_MODEL`, `EC_MODEL`.

- [ ] **Step 1: Pin the dependency (repo)**

Append to `requirements.txt`:

```
# Real SECS/GEM HSMS wire path (#33): secs_equipment_sim.py + hsms_equipment.py.
# License LGPL-2.1-or-later, used as a separable pip dependency (imported, not vendored);
# WaferTrust's own code stays Apache-2.0. Optional: only the HSMS demo/tests import it.
secsgem==0.3.0
```

- [ ] **Step 2: Write the failing read-path test (mirror)**

Create `test_secs_transport.py`:

```python
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
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd <mirror>/demo && <venv python> -m unittest test_secs_transport -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'secs_equipment_sim'`.

- [ ] **Step 4: Implement the simulator read path (mirror)**

Create `secs_equipment_sim.py`:

```python
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
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                with socket.create_connection((self.address, self.port), timeout=0.3):
                    return True
            except OSError:
                time.sleep(0.05)
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
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd <mirror>/demo && <venv python> -m unittest test_secs_transport -v`
Expected: PASS (3 read tests). Cosmetic Windows shutdown noise is filtered.

- [ ] **Step 6: Sync + commit (repo)**

Copy `secs_equipment_sim.py` and `test_secs_transport.py` to the repo. Then:

```bash
git add requirements.txt secs_equipment_sim.py test_secs_transport.py
git commit -m "feat(#33): HSMS equipment simulator read path + secsgem pin"
```

---

### Task 2: Simulator write path (EC write + host command)

**Files:**
- Modify: `secs_equipment_sim.py` (mirror → repo)
- Test: `test_secs_transport.py` (mirror → repo)

**Interfaces:**
- Consumes: Task 1 `SecsEquipmentSim`, `EC_MODEL`, `ACTIVE_LOT_WAFERS`, `WAFER_VALUE_USD`.
- Produces: handlers S2F15/F16 (range-checked EC write, standard single-byte `EAC`) and S2F41/F42 (host command, top-level `HCACK`). Sim state `.ec`, `.control_state`, `.scrapped_wafers`, `.damage_usd`, `.alarms` updated on writes.

- [ ] **Step 1: Write the failing write-path tests (mirror)**

Append to `test_secs_transport.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd <mirror>/demo && <venv python> -m unittest test_secs_transport.SimWritePath -v`
Expected: FAIL — sim returns S09F05 (unexpected function) because S2F15/S2F41 handlers are not registered; `fn.data.get()` raises AttributeError.

- [ ] **Step 3: Implement the write handlers (mirror)**

In `SecsEquipmentSim.__init__`, after the existing registrations, add:

```python
        self.handler.register_stream_function(2, 15, self._on_s2f15)
        self.handler.register_stream_function(2, 41, self._on_s2f41)
```

Add these methods to `SecsEquipmentSim`:

```python
    def _on_s2f15(self, handler, message):
        fn = handler.settings.streams_functions.decode(message)
        eac = 0
        for inner in fn.data.data:
            ecid = int(inner.data["ECID"].get())
            ecv = float(inner.data["ECV"].get())
            model = EC_MODEL.get(ecid)
            if model is None:
                eac = 1
                continue
            _name, _cur, lo, hi = model
            if lo <= ecv <= hi:
                self.ec[ecid] = ecv
            else:
                eac = 1
                self.scrapped_wafers += ACTIVE_LOT_WAFERS
                self.damage_usd += ACTIVE_LOT_WAFERS * WAFER_VALUE_USD
                self.alarms.append({"id": len(self.alarms) + 1,
                                    "text": f"EC {ecid} out of range", "active": True})
        return handler.stream_function(2, 16)(eac)

    def _on_s2f41(self, handler, message):
        fn = handler.settings.streams_functions.decode(message)
        rcmd = str(fn.data.data["RCMD"].get()).upper()
        if rcmd == "ABORT":
            self.scrapped_wafers += ACTIVE_LOT_WAFERS
            self.damage_usd += ACTIVE_LOT_WAFERS * WAFER_VALUE_USD
            hcack = 0
        elif rcmd in ("ONLINE", "OFFLINE"):
            self.control_state = rcmd
            hcack = 0
        else:
            hcack = 1
        return handler.stream_function(2, 42)({"HCACK": hcack, "PARAMS": []})
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd <mirror>/demo && <venv python> -m unittest test_secs_transport -v`
Expected: PASS (7 tests: 3 read + 4 write).

- [ ] **Step 5: Sync + commit (repo)**

Copy `secs_equipment_sim.py`, `test_secs_transport.py` to the repo. Then:

```bash
git add secs_equipment_sim.py test_secs_transport.py
git commit -m "feat(#33): simulator EC write + host command handlers (standard EAC/HCACK)"
```

---

### Task 3: Host adapter (dispatch contract over the wire)

**Files:**
- Create: `hsms_equipment.py` (mirror → repo)
- Test: `test_secs_transport.py` (mirror → repo)

**Interfaces:**
- Consumes: Task 1/2 `SecsEquipmentSim`; secsgem host handler.
- Produces:
  - `HsmsError(RuntimeError)`.
  - Pure helpers: `decode_online_data(fn) -> tuple[str, str]`, `decode_sv_values(fn) -> list`, `decode_eac(fn) -> int`, `decode_hcack(fn) -> int`.
  - Constants `DEMO_SVIDS = [1001, 1002, 1003]`, `DEMO_ECIDS = [2001, 2002]`.
  - `HsmsEquipment(port=5000, address="127.0.0.1", connect_timeout=10.0)` with `.dispatch(tool, arguments) -> dict`, `.close()`, `__enter__`/`__exit__`. Raises `HsmsError` on connect failure and on unsupported tools.

- [ ] **Step 1: Write failing offline mapping unit tests (mirror)**

Append to `test_secs_transport.py`:

```python
from secsgem.secs.functions import (SecsS01F02, SecsS01F04, SecsS02F16, SecsS02F42)
from hsms_equipment import (decode_online_data, decode_sv_values, decode_eac,
                            decode_hcack, HsmsError, HsmsEquipment, DEMO_SVIDS, DEMO_ECIDS)


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd <mirror>/demo && <venv python> -m unittest test_secs_transport.DecodeHelpers -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hsms_equipment'`.

- [ ] **Step 3: Implement the adapter (mirror)**

Create `hsms_equipment.py`:

```python
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
        resp = self._handler.send_and_waitfor_response(
            self._handler.stream_function(stream, function)(value))
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
```

Note: `self._send(1, 1, None)` builds `stream_function(1,1)(None)`; S1F1 takes no data. If secsgem rejects `None`, use `self._handler.stream_function(1, 1)()` directly in `_t_get_equipment_status` (the spike proved `host.stream_function(1,1)()` works). Verify in Step 4 and adjust `_send` to special-case `value is None` by calling the function with no args:

```python
    def _send(self, stream: int, function: int, value):
        klass = self._handler.stream_function(stream, function)
        msg = klass() if value is None else klass(value)
        resp = self._handler.send_and_waitfor_response(msg)
        return self._handler.settings.streams_functions.decode(resp)
```

Use this `value is None` form from the start (it matches the verified spike).

- [ ] **Step 4: Run to verify it passes**

Run: `cd <mirror>/demo && <venv python> -m unittest test_secs_transport -v`
Expected: PASS (all read/write/helper/adapter/fail-closed tests). If `stream_function(1,1)(None)` errors, the `value is None` branch above fixes it.

- [ ] **Step 5: Sync + commit (repo)**

Copy `hsms_equipment.py`, `test_secs_transport.py` to the repo. Then:

```bash
git add hsms_equipment.py test_secs_transport.py
git commit -m "feat(#33): HSMS host adapter with standard SECS-II dispatch mapping"
```

---

### Task 4: Governance over the wire (integration)

**Files:**
- Test: `test_secs_transport.py` (mirror → repo)

**Interfaces:**
- Consumes: `FabGovernanceGateway` (from `fab_gateway`), `HsmsEquipment`, `SecsEquipmentSim`.
- Produces: proof that a governed read is audited and an approval-gated EC write executes over real HSMS, and that the gateway fails closed when the wire is down.

- [ ] **Step 1: Write the failing gateway-over-wire test (mirror)**

Append to `test_secs_transport.py`:

```python
import asyncio
import os
import tempfile

from fab_gateway import FabGovernanceGateway


class GatewayOverWire(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.sim = SecsEquipmentSim(port=self.port)
        self.sim.start()
        self.assertTrue(self.sim.wait_ready(5.0))
        self.eq = HsmsEquipment(port=self.port)
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "gw.sqlite3")
        self.gw = FabGovernanceGateway(self.eq, db_path=self.db)

    def tearDown(self):
        self.eq.close()
        self.sim.stop()
        self.tmp.cleanup()

    def test_governed_read_is_audited(self):
        out = asyncio.run(self.gw.governed_call("get_equipment_status", {}))
        self.assertTrue(out["allowed"])
        self.assertEqual(out["result"]["mdlrn"], "WaferTrustSim")
        self.assertTrue(self.gw.verify_integrity())
        self.assertGreaterEqual(len(self.gw.audit_entries()), 1)

    def test_write_blocked_then_approved_executes_over_wire(self):
        out = asyncio.run(self.gw.governed_call("set_equipment_constant",
                                                {"ecid": 2001, "value": 400}))
        self.assertFalse(out["allowed"])
        self.assertTrue(out["needs_approval"])
        self.assertTrue(self.gw.approve(out["approval_id"]))
        out2 = asyncio.run(self.gw.governed_call("set_equipment_constant",
                                                 {"ecid": 2001, "value": 400},
                                                 operation_id=out["operation_id"]))
        self.assertTrue(out2["allowed"])
        self.assertTrue(out2["result"]["ok"])
        self.assertEqual(self.sim.ec[2001], 400.0)   # changed over the real wire
        self.assertTrue(self.gw.verify_integrity())
```

- [ ] **Step 2: Run to verify it fails or passes**

Run: `cd <mirror>/demo && <venv python> -m unittest test_secs_transport.GatewayOverWire -v`
Expected: This exercises existing gateway code over the new adapter. If it FAILS, investigate root cause (systematic-debugging) before changing anything — the gateway is unchanged, so a failure indicates an adapter/contract mismatch. If it PASSES immediately, that is acceptable here because it integrates already-tested gateway code with the already-tested adapter (no new production code in this task); confirm the assertions truly exercise the wire (sim.ec changed).

- [ ] **Step 3: Confirm full suite green**

Run: `cd <mirror>/demo && <venv python> -m unittest test_hardening test_custody_anchor test_secs_transport -v`
Expected: PASS — existing 27 + new secs tests, zero failures.

- [ ] **Step 4: Sync + commit (repo)**

Copy `test_secs_transport.py` to the repo. Then:

```bash
git add test_secs_transport.py
git commit -m "test(#33): governed read + approval-gated write audited over real HSMS"
```

---

### Task 5: secs_demo.py (runnable wire demo)

**Files:**
- Create: `secs_demo.py` (mirror → repo)

**Interfaces:**
- Consumes: `SecsEquipmentSim` (subprocess via `sys.executable secs_equipment_sim.py`), `HsmsEquipment`, `FabGovernanceGateway`, `anchor`, `AuditLog`.
- Produces: a runnable demo that starts the sim subprocess, runs governed scenes over the wire, exports the flight recorder (stem `secs`), prints the SxFy used per call, and exits 0. Honest banner.

- [ ] **Step 1: Implement secs_demo.py (mirror)**

Create `secs_demo.py`:

```python
"""Real HSMS/SECS-II governed-call demo (#33).

Starts the software equipment simulator as a SEPARATE PROCESS, then drives the real
AgentBridge governance gateway over a genuine HSMS/TCP + SECS-II wire. The endpoint is a
SOFTWARE SIMULATOR, not real fab equipment. No production-safety or compliance claim.

Run:  python secs_demo.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

from fab_gateway import FabGovernanceGateway, AgentIdentity, AuditLog, GovernanceError, canonical_payload
from hsms_equipment import HsmsEquipment, HsmsError
import anchor

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "secs-governance.sqlite3")


def hr(title=""):
    print("\n" + "=" * 72)
    if title:
        print(title)
        print("=" * 72)


def show(tag, outcome):
    if outcome["allowed"]:
        print(f"  [{tag}] ALLOWED  cost=${outcome['cost']:,.0f}  -> {outcome['result']}")
    else:
        print(f"  [{tag}] BLOCKED  {outcome['reason']}")
        if outcome.get("approval_id"):
            print(f"           pending human approval: {outcome['approval_id']}")


def free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_sim(port: int):
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "secs_equipment_sim.py"),
                             "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    import socket
    t0 = time.time()
    while time.time() - t0 < 10.0:
        if proc.poll() is not None:
            raise RuntimeError("simulator exited early:\n" + (proc.stdout.read() or ""))
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("simulator did not become ready")


async def main() -> int:
    hr("Real HSMS/SECS-II wire path — SOFTWARE SIMULATOR, not real equipment")
    port = free_port()
    proc = start_sim(port)
    print(f"  Simulator subprocess started on 127.0.0.1:{port} (SEMI E37 HSMS / SEMI E5 SECS-II).")
    try:
        eq = HsmsEquipment(port=port)
    except HsmsError as exc:
        print(f"  FAIL: {exc}")
        proc.terminate()
        return 1
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    gw = FabGovernanceGateway(eq, budget_limit=600_000, approval_threshold=100_000,
                              max_cost=750_000, db_path=DB_PATH)
    print(f"  Agent identity: {gw.agent_id} (Ed25519 DID); fail-closed production admission.")

    hr("SCENE 1 — Governed read over the wire (S1F1 -> S1F2)")
    show("read", await gw.governed_call("get_equipment_status", {}))
    show("read", await gw.governed_call("get_status_variable", {"svid": 1002}))

    hr("SCENE 2 — EC write BLOCKED pending approval (S2F15 -> S2F16)")
    out = await gw.governed_call("set_equipment_constant", {"ecid": 2001, "value": 400})
    show("write", out)
    approval_id = out.get("approval_id")

    hr("SCENE 3 — Human approves; write executes over the wire within budget")
    if approval_id:
        print(f"  Operator approves {approval_id}: {gw.approve(approval_id)}")
    out = await gw.governed_call("set_equipment_constant", {"ecid": 2001, "value": 400},
                                 operation_id=out["operation_id"])
    show("write", out)
    b = gw.budget()
    print(f"  Budget spent ${b.spent:,.0f} / ${b.spend_limit:,.0f}; remaining ${b.remaining():,.0f}")

    hr("SCENE 4 — Wafer-dollar circuit breaker (S2F41 -> S2F42 ABORT)")
    out = await gw.governed_call("execute_command", {"command": "ABORT"})
    show("write", out)
    if out.get("approval_id"):
        gw.approve(out["approval_id"])
    out = await gw.governed_call("execute_command", {"command": "ABORT"},
                                 operation_id=out["operation_id"])
    show("write", out)
    print("  >> Denied: would risk more wafer-dollars than the shift budget allows.")

    hr("SCENE 5 — Impersonation denied fail-closed")
    impostor = AgentIdentity.generate("impostor-agent")
    wire = {"jsonrpc": "2.0", "id": "execute_command", "method": "tools/call",
            "params": {"name": "execute_command", "arguments": {"command": "ABORT"}}}
    op = uuid.uuid4().hex
    body = json.dumps({"src": "mcp", "dst": "mcp", "wire": wire, "target_id": None,
                       "operation_id": op}, sort_keys=True, separators=(",", ":")).encode()
    nonce = uuid.uuid4().hex
    signed_data = canonical_payload(gw.agent_id, nonce, body)

    async def _never(_wire):
        return {"should_not_run": True}

    try:
        await gw.gw.route_call(agent_id=gw.agent_id, src_proto="mcp", dst_proto="mcp",
                               src_wire=wire, invoke=_never, cost=500_000, operation_id=op,
                               signed_body=body, signed_nonce=nonce, signed_data=signed_data,
                               signature=impostor.sign(signed_data))
        print("  [forged] ALLOWED — this must never happen")
    except GovernanceError as exc:
        print(f"  [forged] BLOCKED  {exc}")

    hr("SCENE 6 — Flight recorder: signed, witnessed, independently verifiable")
    print(f"  Audit integrity verified: {gw.verify_integrity()}")
    paths = gw.export_flight_recorder(HERE, "secs")
    with open(paths["jsonl"], encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    with open(paths["checkpoint"], encoding="utf-8") as fh:
        checkpoint = json.load(fh)
    print(f"  Exported {len(records)} entries; checkpoint verified {AuditLog.verify_checkpoint(checkpoint)}")
    with open(paths["witness"], encoding="utf-8") as fh:
        witness = json.load(fh)
    with open(paths["anchor"], encoding="utf-8") as fh:
        meta = json.load(fh)
    anchor_ok = True
    try:
        anchor.verify_anchor(records, checkpoint, witness,
                             operator_key_hex=meta["operator_key_hex"],
                             witness_key_hex=meta["witness_key_hex"])
    except Exception:
        anchor_ok = False
    print(f"  Independent witness verified: {anchor_ok}")
    print(f"  Independently time-anchored (TSA): {meta['independently_time_anchored']}")
    print(f"  Chain re-verified from file: {AuditLog.verify_chain(records, require_genesis=True)}")
    print("  Check it yourself: python verify_export.py secs")
    print("\n  Real wire protocol to a software simulator; every action authenticated,")
    print("  authorized, budgeted, approved, and logged. Not real equipment.\n")

    eq.close()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: Run the demo (mirror)**

Run: `cd <mirror>/demo && <venv python> secs_demo.py`
Expected: exit 0; scenes print ALLOWED/BLOCKED as in demo.py; witness verified True; TSA False (witness-only); exports written with stem `secs`.

- [ ] **Step 3: Re-verify the export (mirror)**

Run: `cd <mirror>/demo && <venv python> verify_export.py secs`
Expected: `RESULT: PASS`.

- [ ] **Step 4: Sync + commit (repo)**

Copy `secs_demo.py` to the repo. Then:

```bash
git add secs_demo.py
git commit -m "feat(#33): secs_demo.py governed scenes over real HSMS wire + export"
```

---

### Task 6: Docs + CI + full local verification

**Files:**
- Modify: `README.md`, `THREAT_MODEL.md`, `.github/workflows/tests.yml` (repo)

**Interfaces:**
- Consumes: all prior tasks.
- Produces: consistent repo docs disclosing the simulator endpoint + LGPL dependency; CI runs the new tests + demo; full local suite green.

- [ ] **Step 1: README — add the wire-path section (repo)**

Add a section after the existing demos description (match existing heading style):

```markdown
## Real SECS/GEM wire path (optional, #33)

`secs_demo.py` drives the same governance gateway over a **real HSMS (SEMI E37) /
SECS-II (SEMI E5) TCP connection** to `secs_equipment_sim.py`, a **software equipment
simulator** running as a separate process. This proves the protocol boundary is real —
it is **not** real fab equipment, and makes no production-safety or compliance claim.

- Bounded tool subset mapped to standard SECS-II: `get_equipment_status` (S1F1/F2),
  `get_status_variable` / `list_status_variables` (S1F3/F4), `list_equipment_constants`
  (S2F13/F14), `set_equipment_constant` (S2F15/F16), `execute_command` (S2F41/F42).
  Process-job / carrier / alarm / security tools are not wired over HSMS (they raise).
- Standard S1F4/S2F14 carry positional values only, so list shapes differ from the
  in-process stub (no name/unit/min/max). S2F16 carries only EAC; out-of-range writes
  are rejected (EAC=1) with no scrap detail on the wire.
- Dependency: `secsgem==0.3.0` (LGPL-2.1-or-later), imported not vendored; WaferTrust
  code stays Apache-2.0.

Run: `python secs_demo.py` then `python verify_export.py secs`.
```

Add `secs_demo.py` to the demos table/list wherever `demo.py` and `maintenance_demo.py` are listed.

- [ ] **Step 2: THREAT_MODEL.md — disclose limits (repo)**

Add to the appropriate scope/limits section:

```markdown
### Real SECS/GEM wire path (#33)

- The HSMS endpoint (`secs_equipment_sim.py`) is a **software simulator**, not real
  equipment. The wire protocol (HSMS/SECS-II) is real; the governed device is not.
- `secsgem==0.3.0` is LGPL-2.1-or-later, used as a separable pip dependency. WaferTrust's
  own code remains Apache-2.0.
- Bounded tool subset; standard SECS-II structures only. No GEM300, no SECS-I, no full
  tool mapping, no certification, no production-safety or process-physics claim.
- Governance is unchanged: identity, policy, budgets, approvals, and the hash-chained
  audit sit above the wire boundary exactly as in the in-process demo.
```

- [ ] **Step 3: CI — add new tests + demo (repo)**

In `.github/workflows/tests.yml`, change the unittest step and add demo + verify steps:

```yaml
      - name: Run hardening + custody/anchor + secs transport tests
        working-directory: wafertrust
        run: python -m unittest test_hardening test_custody_anchor test_secs_transport -v
```

Add after the maintenance demo step:

```yaml
      - name: Run real HSMS/SECS-II demo
        working-directory: wafertrust
        run: python secs_demo.py
```

And extend the re-verify step:

```yaml
      - name: Re-verify exported flight recorders
        working-directory: wafertrust
        run: |
          python verify_export.py audit
          python verify_export.py maintenance
          python verify_export.py secs
```

- [ ] **Step 4: Full local verification (mirror, against pinned kernel)**

Run each and confirm exit 0 / PASS:

```bash
cd <mirror>/demo
<venv python> -m unittest test_hardening test_custody_anchor test_secs_transport -v
<venv python> demo.py
<venv python> maintenance_demo.py
<venv python> secs_demo.py
<venv python> verify_export.py audit
<venv python> verify_export.py maintenance
<venv python> verify_export.py secs
```

Expected: all tests pass (27 existing + new), all three demos exit 0, all three verifiers PASS.

- [ ] **Step 5: Sync docs/CI are already in repo; commit (repo)**

```bash
git add README.md THREAT_MODEL.md .github/workflows/tests.yml
git commit -m "docs(#33): wire-path section + threat model + CI for HSMS demo/tests"
```

- [ ] **Step 6: Re-verify in the REPO working tree (not just mirror)**

Copy any final mirror code files to the repo, then run the full suite from the repo using a python that can import the sibling kernel. If the repo's sibling `../agentbridge` is the Codex working tree (do NOT modify it), verify via the mirror instead and confirm repo files match mirror byte-for-byte (`diff`). Confirm `git status` shows only intended files.

- [ ] **Step 7: Merge to main + push (user authorized push-after-local-verify)**

Only after Step 4/6 are green:

```bash
git checkout main
git merge --ff-only tier2-real-secs-gem
git push origin main
git branch -d tier2-real-secs-gem
git push origin --delete tier2-real-secs-gem
```

Then confirm CI green: `gh run list --branch main --limit 1` and `gh run watch <id>`.

- [ ] **Step 8: Clean up throwaway spike**

Remove `C:/Users/DELL/AppData/Local/Temp/wafertrust-secs-spike/` (probe.py, shapes.py, access.py, venv). Keep the mirror until the work is confirmed shipped.

---

## Self-Review

**Spec coverage:**
- Dependency pin + LGPL disclosure → Task 1 Step 1, Task 6 Steps 1-2. ✓
- secs_equipment_sim.py (state, S1F1/F2, S1F3/F4, S2F13/F14, S2F15/F16, S2F41/F42, start/stop/wait_ready, standalone, Windows filter) → Tasks 1-2. ✓
- hsms_equipment.py (HsmsError, lifecycle fail-closed, dispatch mapping, unsupported raises, .get() helpers, demo IDs) → Task 3. ✓
- All-standard SECS-II, positional S1F4/S2F14 zip, EAC/HCACK, no scrap on wire → Tasks 2-3. ✓
- secs_demo.py (subprocess sim, scenes, export, honest banner) → Task 5. ✓
- Tests (offline mapping + loopback + gateway-over-wire + fail-closed; existing 27 unchanged) → Tasks 1-4. ✓
- README/THREAT_MODEL/CI updates → Task 6. ✓
- Local-first verify → push when green → Task 6 Steps 4-7. ✓

**Placeholder scan:** No TBD/TODO; all code blocks concrete. The `_send` None-handling note gives the exact verified form. ✓

**Type consistency:** `SecsEquipmentSim(port,address)`, `.start/.stop/.wait_ready/.handler/.sv/.ec`; `HsmsEquipment(port,address,connect_timeout)`, `.dispatch/.close`; helpers `decode_online_data/decode_sv_values/decode_eac/decode_hcack`; constants `DEMO_SVIDS/DEMO_ECIDS/SV_MODEL/EC_MODEL`; `HsmsError`. Names match across tasks. ✓