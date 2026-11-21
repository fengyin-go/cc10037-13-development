"""列归属领域服务：维护目标表输出列的归属实例、计算表达式与核实状态。

上游：template_instance 提供可写实例与字段映射 → 本模块落定列归属
消费：write_governance 按列归属签出写入计划，归属待核实时候选只读
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ColumnAttributionService(BaseModuleService):
    MODULE = "column_attribution"
    ENTITY = "列归属"
    OPERATION_TERM = "核实"
    LIST_FIELDS = [
        "目标表", "目标列", "归属实例", "计算表达式", "来源列", "核实结论",
    ]
    REQUIRED_FIELDS = ["目标表", "目标列"]
    STATUS_ORDER = ["归属待核实", "归属已核实", "留待核对"]
    ACTION_RULES = {"核实通过": "归属待核实", "退回核对": "归属已核实"}
    NEGATIVE_ACTIONS = ["退回核对"]

    def query_by_target_table(self, target_table: str) -> list[dict[str, Any]]:
        """查询目标表的全部列归属数据，供编排按列签出写入计划。"""
        return [
            dict(row) for row in store.rows(self.MODULE)
            if target_table.casefold() in str(row.get("目标表", "")).casefold()
        ]

    def pending_columns(self, target_table: str) -> list[dict[str, Any]]:
        """列出归属待核实/留待核对的目标列，这些列的候选必须保持只读。"""
        return [
            dict(row) for row in store.rows(self.MODULE)
            if str(row.get("目标表", "")) == target_table
            and row.get("status") in ("归属待核实", "留待核对")
        ]

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry, msg = super().run_action(entry_id, action)
        if entry:
            entry["last_operated_at"] = datetime.now().isoformat()
        return entry, msg
