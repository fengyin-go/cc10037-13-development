"""模板实例领域服务：管理模板实例化后锁定的输入/输出 Schema 版本与字段映射。

上游：template_store 提供模板版本 → 实例化时快照 Schema 与映射
消费：write_governance 依据实例的授权源列与表达式做写入权限判定
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class TemplateInstanceService(BaseModuleService):
    MODULE = "template_instance"
    ENTITY = "模板实例"
    OPERATION_TERM = "激活"
    LIST_FIELDS = [
        "实例标识", "模板名称", "模板版本", "输入Schema版本", "输出Schema版本",
        "授权源列", "输出字段映射", "计算表达式", "所属运行",
    ]
    REQUIRED_FIELDS = ["实例标识", "模板名称", "模板版本", "输入Schema版本", "输出Schema版本"]
    STATUS_ORDER = ["待激活", "已激活", "已停用"]
    ACTION_RULES = {"激活实例": "待激活", "停用实例": "已激活"}
    NEGATIVE_ACTIONS = ["停用实例"]

    def query_by_template(self, template_name: str) -> list[dict[str, Any]]:
        """按模板名称查询其全部版本实例，供换版后关联新实例、复查旧实例。"""
        result: list[dict[str, Any]] = []
        for row in store.rows(self.MODULE):
            if template_name.casefold() in str(row.get("模板名称", "")).casefold():
                result.append(dict(row))
        return result

    def query_active_versions(self) -> list[dict[str, Any]]:
        """汇总每个模板当前激活实例使用的 Schema 版本。"""
        seen: dict[str, dict[str, Any]] = {}
        for row in store.rows(self.MODULE):
            if row.get("status") != "已激活":
                continue
            name = str(row.get("模板名称", ""))
            seen[name] = {
                "template": name,
                "template_version": row.get("模板版本"),
                "input_schema_version": row.get("输入Schema版本"),
                "output_schema_version": row.get("输出Schema版本"),
                "instance_id": row.get("实例标识"),
            }
        return list(seen.values())

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry, msg = super().run_action(entry_id, action)
        if entry:
            entry["last_operated_at"] = datetime.now().isoformat()
        return entry, msg
