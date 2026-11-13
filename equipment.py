"""In-process SECS/GEM equipment simulator.

Stands in for go-factory-io (which needs Go) so the whole demo runs on a laptop
with Python only. It mirrors the go-factory-io REST data model that
secsgem-mcp-server wraps: status variables (SV), equipment constants (EC),
alarms, process jobs, carriers, and a SEMI E191 security report.

In production the gateway's `invoke` would call the real secsgem-mcp-server ->
go-factory-io REST API instead of this stub. The governance layer is unchanged.
"""

from __future__ import annotations

WAFER_VALUE_USD = 20_000
ACTIVE_LOT_WAFERS = 25


class SecsGemEquipment:
    def __init__(self) -> None:
        self.control_state = "ONLINE"
        self.communication_state = "COMMUNICATING"
        self.transport_state = "READY"
        self.sv = {
            1001: {"name": "WaferCount", "value": 1250, "unit": "wafers"},
            1002: {"name": "ChamberTemp", "value": 350, "unit": "C"},
            1003: {"name": "ChamberPressure", "value": 100, "unit": "mTorr"},
        }
        self.ec = {
            2001: {"name": "ChamberTempSetpoint", "value": 350, "unit": "C", "min": 200, "max": 450},
            2002: {"name": "PressureLimit", "value": 100, "unit": "mTorr", "min": 50, "max": 200},
        }
        self.alarms: list[dict] = []
        self.process_jobs: dict[str, dict] = {}
        self.carriers: dict[str, dict] = {}
        self.scrapped_wafers = 0
        self.damage_usd = 0
        self.action_log: list[dict] = []

    # --- read tools (SEMI E30 GEM) ---
    def get_equipment_status(self) -> dict:
        return {
            "communicationState": self.communication_state,
            "controlState": self.control_state,
            "transportState": self.transport_state,
        }

    def list_status_variables(self) -> dict:
        return {"statusVariables": [{"svid": k, **v} for k, v in self.sv.items()]}

    def get_status_variable(self, svid: int) -> dict:
        return {"svid": svid, **self.sv.get(int(svid), {})}

    def list_alarms(self, active_only: bool = False) -> dict:
        alarms = [a for a in self.alarms if a["active"]] if active_only else self.alarms
        return {"alarms": alarms}

    def list_equipment_constants(self) -> dict:
        return {"equipmentConstants": [{"ecid": k, **v} for k, v in self.ec.items()]}

    def get_security_status(self) -> dict:
        # SEMI E191 cybersecurity status report. Note: audit is "none" — the
        # equipment itself has no record of who changed what. That is the gap.
        return {
            "standard": "SEMI E191",
            "tls": "enabled",
            "rbac": "baseline",
            "agentAudit": "none",
            "posture": "equipment-only; no agent identity/approval/audit",
        }

    # --- write tools ---
    def set_equipment_constant(self, ecid: int, value) -> dict:
        ecid = int(ecid)
        ec = self.ec.get(ecid)
        if ec is None:
            return {"ok": False, "error": f"unknown ECID {ecid}"}
        value = float(value)
        if value < ec["min"] or value > ec["max"]:
            # Out-of-range setpoint scraps the active lot. This is the blast radius.
            self.scrapped_wafers += ACTIVE_LOT_WAFERS
            self.damage_usd += ACTIVE_LOT_WAFERS * WAFER_VALUE_USD
            self.alarms.append({"id": len(self.alarms) + 1, "text": f"EC {ecid} out of range", "active": True})
            self.action_log.append({"tool": "set_equipment_constant", "ecid": ecid, "value": value, "scrapped": ACTIVE_LOT_WAFERS})
            return {"ok": False, "scrappedWafers": ACTIVE_LOT_WAFERS,
                    "damageUsd": ACTIVE_LOT_WAFERS * WAFER_VALUE_USD,
                    "reason": f"{value} outside [{ec['min']},{ec['max']}]"}
        ec["value"] = value
        self.action_log.append({"tool": "set_equipment_constant", "ecid": ecid, "value": value, "scrapped": 0})
        return {"ok": True, "ecid": ecid, "value": value}

    def execute_command(self, command: str, params: dict | None = None) -> dict:
        command = command.upper()
        if command == "ABORT":
            self.scrapped_wafers += ACTIVE_LOT_WAFERS
            self.damage_usd += ACTIVE_LOT_WAFERS * WAFER_VALUE_USD
            self.action_log.append({"tool": "execute_command", "command": command, "scrapped": ACTIVE_LOT_WAFERS})
            return {"ok": True, "command": command, "scrappedWafers": ACTIVE_LOT_WAFERS}
        if command in ("ONLINE", "OFFLINE"):
            self.control_state = command
        self.action_log.append({"tool": "execute_command", "command": command, "scrapped": 0})
        return {"ok": True, "command": command, "controlState": self.control_state}

    def manage_process_job(self, action: str, job_id: str, recipe: str | None = None,
                           carrier_id: str | None = None, slots: list | None = None) -> dict:
        if action == "status":
            return {"ok": True, "jobs": self.process_jobs}
        self.process_jobs[job_id] = {"action": action, "recipe": recipe, "carrierId": carrier_id, "slots": slots}
        self.action_log.append({"tool": "manage_process_job", "action": action, "jobId": job_id})
        return {"ok": True, "action": action, "jobId": job_id}

    def manage_carrier(self, action: str, carrier_id: str, port: int | None = None) -> dict:
        self.carriers[carrier_id] = {"action": action, "port": port}
        self.action_log.append({"tool": "manage_carrier", "action": action, "carrierId": carrier_id})
        return {"ok": True, "action": action, "carrierId": carrier_id}

    # --- router used by the gateway invoke ---
    def dispatch(self, tool: str, arguments: dict) -> dict:
        fn = getattr(self, tool, None)
        if fn is None:
            return {"ok": False, "error": f"unknown tool {tool}"}
        return fn(**arguments)