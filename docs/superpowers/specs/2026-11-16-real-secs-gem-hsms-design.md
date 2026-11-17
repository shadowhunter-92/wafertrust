# Design: Real SECS/GEM wire path (#33)

Date: 2026-11-16
Status: approved design, pre-implementation
Scope: WaferTrust demo repo only (`fab-governance-demo`). No AgentBridge kernel changes.
Kernel: public `shadowhunter-92/agentbridge` @ `f309a35cb5c3ec4164acea5ba2622dc04be6807c`.

## Problem

Today the equipment boundary is an in-process Python stub: `fab_gateway.py` calls
`self.equipment.dispatch(tool, arguments)` directly on a `SecsGemEquipment` object
(`equipment.py`). There is no wire protocol — no HSMS handshake, no SECS-II item
encoding, no SxFy messages. The README is honest that this is a library demo, but the
"SECS/GEM" boundary is simulated at the function-call level, not the protocol level.

This design adds a **real HSMS / SECS-II transport** for a bounded subset of tools, so a
governed call actually crosses a TCP connection speaking SEMI E37 (HSMS) and SEMI E5
(SECS-II) to a software equipment simulator running as a separate process. The governance
layer (identity, policy, budgets, approvals, audit, signing) is unchanged.

## Honesty boundary (non-negotiable)

- The endpoint is a **software simulator**, not real fab equipment. No hardware exists.
- This demonstrates the **wire protocol is real**, not that any real equipment is governed.
- No production-safety, compliance, certification, or process-physics claim.
- No GEM300, no SECS-I (serial), no full 10-tool mapping. Bounded subset only.
- The third-party dependency is disclosed (LGPL, below).

## Dependency

- `secsgem==0.3.0` (PyPI), license **LGPL-2.1-or-later**. Used as a separable pip
  dependency (imported, not vendored). Apache-2.0 is compatible with LGPL-2.1 for a
  combined work where the LGPL library remains separable; WaferTrust's own code stays
  Apache-2.0. Disclosed in README and `requirements.txt`.
- Feasibility proven by a throwaway spike (2026-11-16): HSMS link reached
  `CONNECTED_SELECTED`; S1F1→S1F2 read returned real SECS-II data; S2F15→S2F16 write
  acknowledged (EAC 0) and changed the equipment constant over the wire.
- Known third-party issue: secsgem 0.3.0 calls `shutdown()` on the listening socket after
  accept, which raises `OSError WinError 10057` on Windows in the server cleanup thread.
  It is cosmetic (the accepted connection works). Absent on Linux/CI. Contained in the
  simulator process; the sim filters this specific harmless exception (documented).

## Architecture

The gateway already injects an equipment object and calls `.dispatch(tool, arguments)`.
We add a second implementation of that contract that speaks HSMS/SECS-II. Nothing above
the boundary changes.

```
demo agent → GovernanceGateway (UNCHANGED) → HsmsEquipment.dispatch(tool, args)
                                                  │  HSMS host (secsgem), TCP loopback
                                                  ▼
                                         secs_equipment_sim.py (separate process)
                                         HSMS equipment server; holds SV/EC state
```

Two transport modes, selected by which equipment object is injected:
- **in-process stub** (`equipment.SecsGemEquipment`) — today's default, zero new deps for
  the existing demos. Unchanged.
- **HSMS wire** (`hsms_equipment.HsmsEquipment`) — new, optional, real protocol.

## Components

### `secs_equipment_sim.py` (new)

Standalone HSMS equipment server (SEMI E37 passive / EQUIPMENT). Holds the same SV/EC
data model as `equipment.py` so the demo narrative is consistent.

- State: SV `{1001 WaferCount, 1002 ChamberTemp, 1003 ChamberPressure}`;
  EC `{2001 ChamberTempSetpoint (min 200, max 450), 2002 PressureLimit (min 50, max 200)}`.
- SECS-II handlers (registered via `SecsHandler.register_stream_function`):
  - **S1F1 → S1F2** (Are You There / On Line Data): returns `[MDLN="WaferTrustSim",
    SOFTREV="1.0"]`.
  - **S1F3 → S1F4** (Selected Equipment Status Request / Data): returns the requested
    SVIDs' values as a positional list in request order (standard S1F4 carries values only).
    An empty request list returns all SVs in ascending SVID order.
  - **S2F13 → S2F14** (Equipment Constant Request / Data): returns the requested ECIDs'
    values as a positional list in request order. Empty list returns all in ascending order.
  - **S2F15 → S2F16** (New Equipment Constant Send / Ack): for each `{ECID, ECV}`, if
    within `[min,max]` set the value and ack `EAC=0`; if out of range, do not change the
    value, record an alarm + scrap internally, ack `EAC=1`. S2F16 is the standard single
    `EAC` byte (no scrap detail on the wire).
  - **S2F41 → S2F42** (Host Command Send / Ack): `RCMD` in {ABORT, ONLINE, OFFLINE}.
    ABORT records scrap; ONLINE/OFFLINE set control state. Ack top-level `HCACK=0`
    (accepted) or `HCACK=1` (rejected, unknown command); empty PARAMS list.
- API:
  - `SecsEquipmentSim(port=5000, address="127.0.0.1")` — construct.
  - `.start()` — enable the HSMS server (background threads). `.stop()` — disable.
  - `.wait_ready(timeout)` — block until the server is listening.
  - Runnable as `python secs_equipment_sim.py [--port N] [--address A]` (separate process).
  - Importable so tests can run it in a thread on loopback.
- Filters the harmless Windows `WinError 10057` cleanup exception via a targeted
  `threading.excepthook` (documented; does not mask other errors).

### `hsms_equipment.py` (new)

Host-side adapter (SEMI E37 active / HOST) implementing the same `.dispatch(tool, args)`
contract as the stub.

- `HsmsEquipment(port=5000, address="127.0.0.1", connect_timeout=10.0)`:
  - On construction, enable the HSMS host and wait for `CONNECTED_SELECTED`. On timeout or
    failure raise `HsmsError` (fail-closed; never silently fall back to the stub).
  - `.close()` / context-manager (`__enter__`/`__exit__`) to disable the connection.
- `.dispatch(tool, arguments) -> dict` maps the supported tools to SECS-II and back:
  - `get_equipment_status` → S1F1/F2 → `{communicationState, mdlrn, softrev}` where
    `communicationState` is the HSMS link state (`CONNECTED_SELECTED` ⇒ `COMMUNICATING`)
    and `mdlrn`/`softrev` come from S1F2. Note: S1F1/F2 does **not** carry GEM
    control/transport state, so this shape differs from the stub's
    `{communicationState, controlState, transportState}`; documented, not hidden.
  - `get_status_variable(svid)` → S1F3 `[svid]` / F4 → `{svid, value}`.
  - `list_status_variables()` → S1F3 `[1001,1002,1003]` / F4 → `[{svid, value}, ...]`.
  - `list_equipment_constants()` → S2F13 `[2001,2002]` / F14 → `[{ecid, value}, ...]`.
    S1F4/S2F14 carry **positional value lists** (SEMI E5: no IDs, names, or units in the
    reply), so the adapter requests explicit IDs and zips them with the returned values.
    The demo SVID/ECID set is a documented demo-data-model constant in the adapter; a real
    host discovers IDs via S1F11/S2F29 name lists (out of scope). Returned shapes therefore
    differ from the stub (no `name`/`unit`/`min`/`max`); documented, not hidden.
  - `set_equipment_constant(ecid, value)` → S2F15 `[{ECID, ECV}]` / F16 → `EAC=0` ⇒
    `{ok:True, ecid, value}`; `EAC!=0` ⇒ `{ok:False, ecid, reason}`.
  - `execute_command(command, params)` → S2F41 `{RCMD, PARAMS}` / F42 → top-level `HCACK=0`
    ⇒ `{ok:True, command}`; else `{ok:False, command, reason}`. (S2F42's top-level ack is
    HCACK; per-parameter CPACK is not used by this bounded slice.)
  - `manage_process_job`, `manage_carrier`, `get_security_status`, `list_alarms` →
    **not wired** in HSMS mode: raise `HsmsError("tool not supported over HSMS: ...")`.
    Documented bounded scope.
- Value extraction uses the secsgem SecsVar tree with the uniform scalar accessor
  `var.get()` (ASCII → str, numeric → int/float; verified offline). Note `.value` is a
  string for ASCII but a list for numerics, so `.get()` is used everywhere to avoid
  first-character bugs. Encapsulated in small private helpers so the mapping is unit-testable.

### Data mapping note (all-standard SECS-II)

Every mapping uses the **standard** secsgem function structures — no private wire
extensions. Standard S2F16 carries only `EAC` (one byte), so an out-of-range EC write is
reported as `{ok:False, reason}` with **no** scrap numbers over the wire; the sim tracks
scrapped wafers / damage internally for its own state, but the adapter does not claim them.
This is honest: the wafer-dollar blast-radius narrative lives in the in-process stub demo
and in the governance budget; the HSMS slice proves the protocol + governance, and
governance blocks out-of-range writes (budget/approval) before they reach the wire anyway.
secsgem validates each reply against its `_data_format`, which is why a private S2F16 list
extension was rejected in design.

### `secs_demo.py` (new)

Demonstrates a governed call crossing the real wire.

1. Start `secs_equipment_sim.py` as a **subprocess** on a free port; wait ready.
2. Build the real `GovernanceGateway` (`require_verified=True`) with `HsmsEquipment` as the
   equipment object; reuse the existing identity/budget/approval/export helpers.
3. Scenes (mirror `demo.py`, over HSMS): governed read logged → approval-gated EC write
   BLOCKED → human approves → write executes over S2F15/F16 within budget → budget circuit
   breaker denies a second write → impostor forged call denied fail-closed → export flight
   recorder + signed checkpoint + witness anchor (reuse `export_flight_recorder`).
4. Print the SECS-II stream/function actually used per call (e.g. `S2F15→S2F16 EAC=0`) so
   the wire path is visible. Stop the sim subprocess.
5. Honest banner: "Real HSMS/SECS-II to a software simulator — not real equipment."

### Tests (`test_secs_transport.py`, new)

- **Mapping unit tests** (no network): tool→(stream,function) selection; SecsVar
  encode/decode round-trip for EC write and SV read; S2F16 EAC parsing; S2F42 HCACK parsing;
  unsupported tool raises `HsmsError`.
- **Loopback integration tests** (sim in a thread + `HsmsEquipment` host on a free port):
  - governed read returns expected SV/EC data over the wire;
  - in-range EC write acks `EAC=0` and changes sim state;
  - out-of-range EC write acks `EAC=1` (reject; no scrap detail on the wire);
  - host command ABORT/ONLINE acks `HCACK=0`;
  - connection failure (no sim) raises `HsmsError` fail-closed;
  - a full gateway governed read+approve+write over the wire is audited (reuse kernel).
- Existing 27 tests (`test_hardening`, `test_custody_anchor`) stay green and unchanged.
- Tests pick a free TCP port to avoid collisions; CI runs on Ubuntu (no Windows noise).

## Files touched

- Create: `secs_equipment_sim.py`, `hsms_equipment.py`, `secs_demo.py`,
  `test_secs_transport.py`.
- Modify: `requirements.txt` (add `secsgem==0.3.0` + license comment), `README.md` (new
  "Real SECS/GEM wire path (optional)" section + demos table rows + honesty note),
  `THREAT_MODEL.md` (simulator endpoint + LGPL dependency + non-goals),
  `.github/workflows/tests.yml` (add `test_secs_transport` to the unittest list; add a
  `secs_demo.py` run step).
- Unchanged: `fab_gateway.py` governance logic, kernel, `equipment.py`, existing demos'
  default behavior, `keystore.py`, `anchor.py`, `tsa.py`, `verify_export.py`.

## Testing / verification plan

- `python -m unittest test_hardening test_custody_anchor test_secs_transport -v` all green.
- `python demo.py`, `python maintenance_demo.py` exit 0 (unchanged).
- `python secs_demo.py` exit 0; prints real SxFy exchanges; exports re-verify.
- `python verify_export.py audit` / `maintenance` PASS.
- Verify in the isolated temp mirror against the pinned kernel before any push.

## Non-goals

No real equipment; no GEM300; no SECS-I; no full tool mapping; no production-safety or
compliance claim; no certification; no change to the governance/trust kernel. The wire path
proves the protocol boundary is real to a software simulator, nothing more.