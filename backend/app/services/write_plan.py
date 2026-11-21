"""写入计划领域服务：管理编排按列归属签出的正式/只读写入计划及血缘登记状态。

上游：column_attribution + template_instance 完成权限核对 → 本模块保存计划
消费：lineage_graph 按正式计划登记净额列的源列与实例血缘
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class WritePlanService(BaseModuleService):
    MODULE = "write_plan"
    ENTITY = "写入计划"
    OPERATION_TERM = "签出"
    LIST_FIELDS = [
        "运行标识", "目标表", "目标列", "签出实例", "模板版本",
        "计算表达式", "实际源列", "权限判定", "血缘登记",
    ]
    REQUIRED_FIELDS = ["运行标识", "目标表", "目标列", "签出实例"]
    STATUS_ORDER = ["待核实", "正式计划", "留待核对", "历史归档"]
    ACTION_RULES = {
        "签出计划": "待核实",
        "留待核对": "待核实",
        "归档计划": "正式计划",
    }
    NEGATIVE_ACTIONS = ["留待核对"]

    def query_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """按运行标识复查写入计划（模板换版后旧运行仍可追溯源输入）。"""
        return [
            dict(row) for row in store.rows(self.MODULE)
            if str(row.get("运行标识", "")) == run_id
        ]

    def formal_plans(self, target_table: str) -> list[dict[str, Any]]:
        """返回目标表已授权的正式写入计划，供血缘登记与下游核对。"""
        return [
            dict(row) for row in store.rows(self.MODULE)
            if str(row.get("目标表", "")) == target_table
            and row.get("status") == "正式计划"
        ]

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry, msg = super().run_action(entry_id, action)
        if entry:
            entry["last_operated_at"] = datetime.now().isoformat()
        return entry, msg
