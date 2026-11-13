"""Maintenance/analytics system stub — the agent fabs run TODAY.

This models the felt pain from customer research: Intel and others already run
agentic maintenance (e.g. ultrapure-water pump / compressor upkeep) that reads
sensor trends and generates work-order recommendations "with human oversight at
every step." The gap is that there is no neutral, tamper-evident record of who
recommended what, who approved it, and what the blast radius was.

Recommendations are free (the agent may suggest); DISPATCHING a work order takes
a tool offline and risks wafer starts, so it is approval-gated and risk-budgeted.
"""

from __future__ import annotations

WAFER_VALUE_USD = 20_000
TOOL_DOWNTIME_LOTS = 10


class MaintenanceSystem:
    def __init__(self) -> None:
        self.assets = {
            "UPW-PUMP-01": {"health": 71, "vibration_mm_s": 4.8, "trend": "rising", "status": "RUNNING"},
            "COMPRESSOR-02": {"health": 88, "vibration_mm_s": 2.1, "trend": "flat", "status": "RUNNING"},
            "ETCH-CHAMBER-03": {"health": 64, "vibration_mm_s": 5.5, "trend": "rising", "status": "RUNNING"},
        }
        self.work_orders: dict[str, dict] = {}
        self.recommendations: list[dict] = []
        self.offline_tools: list[str] = []
        self.action_log: list[dict] = []

    # --- read / recommend (audited, no actuation) ---
    def read_sensor_trends(self, asset_id: str) -> dict:
        a = self.assets.get(asset_id, {})
        return {"assetId": asset_id, "vibration_mm_s": a.get("vibration_mm_s"),
                "trend": a.get("trend"), "health": a.get("health")}

    def get_asset_health(self, asset_id: str) -> dict:
        return {"assetId": asset_id, **self.assets.get(asset_id, {})}

    def list_pending_work_orders(self) -> dict:
        return {"workOrders": list(self.work_orders.values())}

    def recommend_work_order(self, asset_id: str, issue: str, priority: str = "medium") -> dict:
        wo_id = f"WO-{len(self.recommendations) + 1:03d}"
        rec = {"workOrderId": wo_id, "assetId": asset_id, "issue": issue,
               "priority": priority, "status": "recommended"}
        self.recommendations.append(rec)
        self.work_orders[wo_id] = rec
        self.action_log.append({"tool": "recommend_work_order", "workOrderId": wo_id, "assetId": asset_id})
        return {"ok": True, **rec}

    # --- write: dispatch takes a tool offline (wafer-risk) ---
    def dispatch_work_order(self, work_order_id: str, window: str = "next-shift") -> dict:
        wo = self.work_orders.get(work_order_id)
        if wo is None:
            return {"ok": False, "error": f"unknown work order {work_order_id}"}
        asset_id = wo["assetId"]
        self.assets[asset_id]["status"] = "MAINTENANCE"
        self.offline_tools.append(asset_id)
        wo["status"] = "dispatched"
        wo["window"] = window
        risk = TOOL_DOWNTIME_LOTS * WAFER_VALUE_USD
        self.action_log.append({"tool": "dispatch_work_order", "workOrderId": work_order_id,
                                "assetId": asset_id, "riskUsd": risk})
        return {"ok": True, "workOrderId": work_order_id, "assetId": asset_id,
                "toolOffline": True, "waferRiskUsd": risk}

    def dispatch(self, tool: str, arguments: dict) -> dict:
        fn = getattr(self, tool, None)
        if fn is None:
            return {"ok": False, "error": f"unknown tool {tool}"}
        return fn(**arguments)