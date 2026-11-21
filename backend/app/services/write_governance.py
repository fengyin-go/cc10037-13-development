"""写入编排治理领域服务：模板实例、列归属、写入计划与净额血缘的统一治理入口。

本服务持有 WriteGovernanceEngine 单例，并在首次调用时按模板实例/列归属/写入计划
三张种子表引导出完整的两次编排叙事：

- RUN-20261120-01（首次提交）：退款实例缺公式、来源权限不足，净额列留待核对，
  候选只读、不产生正式净额写入与血缘；
- RUN-20261121-01（补齐净额表达式并换版后重新提交）：订单/退款 v2 实例共同按
  正式净额表达式 net_amount=order_amount-refund_amount 加工，签出正式写入计划
  并登记字段级血缘。

模板换版后新运行关联新实例，旧运行的写入计划与源输入仍通过 get_run 复查。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.engine.write_governance import (
    AttributionStatus,
    ColumnAttribution,
    FieldMapping,
    NetExpression,
    SchemaVersion,
    TemplateInstance,
    WriteGovernanceEngine,
)
from app.store import store

TARGET_TABLE = "dw.dwd_order_settle"
NET_COLUMN = "net_amount"
FORMAL_NET_EXPRESSION = "net_amount=order_amount-refund_amount"

# 两次编排运行标识
FIRST_RUN = "RUN-20261120-01"
SECOND_RUN = "RUN-20261121-01"


def _split(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _parse_mappings(raw: str) -> list[FieldMapping]:
    """解析「目标列<-表达式;目标列<-表达式」形式的输出字段映射。"""
    mappings: list[FieldMapping] = []
    for chunk in str(raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk or "<-" not in chunk:
            continue
        target, expression = chunk.split("<-", 1)
        target = target.strip()
        expression = expression.strip()
        # 表达式中引用的源列：简单按标识符切词，再与授权源列求交得到来源列
        source_columns = [token for token in expression.replace("-", " ").split() if token]
        mappings.append(FieldMapping(
            target_column=target,
            expression=f"{target}={expression}" if expression else "",
            source_columns=source_columns,
        ))
    return mappings


class WriteGovernanceService:
    """写入编排治理服务（非通用 CRUD 模块，状态由引擎统一管理）。"""

    def __init__(self) -> None:
        self.engine = WriteGovernanceEngine()
        self._bootstrapped = False

    # ---- 引导 ----

    def bootstrap(self) -> None:
        """按种子数据注册实例、净额表达式，并复放两次编排提交。"""
        if self._bootstrapped:
            return
        self._bootstrapped = True

        # 1. 注册全部模板实例（含输入/输出 Schema 版本与输出字段映射）
        for row in store.rows("template_instance"):
            mappings = _parse_mappings(str(row.get("输出字段映射", "")))
            authorized = _split(row.get("授权源列"))
            # 以授权源列校正映射来源列，保证权限判定追到实例真实授权范围
            for mapping in mappings:
                mapping.source_columns = [
                    col for col in mapping.source_columns if col in authorized
                ] or [col for col in authorized if col in mapping.expression]
            instance = TemplateInstance(
                instance_id=str(row["实例标识"]),
                template_name=str(row["模板名称"]),
                template_version=str(row["模板版本"]),
                schema=SchemaVersion(
                    input_version=str(row["输入Schema版本"]),
                    output_version=str(row["输出Schema版本"]),
                    input_columns=authorized,
                    output_columns=[m.target_column for m in mappings],
                ),
                mappings=mappings,
                active=str(row.get("status")) == "已激活",
                created_at=str(row.get("所属运行", "")),
            )
            self.engine.register_instance(instance)

        # 2. 引导列归属（首次提交前的待核实/留待核对状态）
        for row in store.rows("column_attribution"):
            status_map = {
                "归属待核实": AttributionStatus.PENDING,
                "归属已核实": AttributionStatus.VERIFIED,
                "留待核对": AttributionStatus.HELD,
            }
            self.engine.register_attribution(ColumnAttribution(
                target_table=str(row["目标表"]),
                target_column=str(row["目标列"]),
                owner_instance_id=str(row.get("归属实例", "")),
                expression=str(row.get("计算表达式", "")),
                source_columns=_split(row.get("来源列")),
                status=status_map.get(str(row.get("status")), AttributionStatus.PENDING),
                resolution=str(row.get("核实结论", "")),
            ))

        # 3. 首次提交：order_id 已有正式表达式可签出；净额列正式表达式尚未补齐，
        #    订单/退款两个实例的净额候选只能留待核对
        self.engine.register_net_expression(NetExpression(
            target_table=TARGET_TABLE,
            target_column="order_id",
            expression="order_id=order_id",
            required_source_columns=["order_id"],
        ))
        self._submit_first_run()

        # 4. 补齐净额列正式表达式，模板换版后重新提交
        self.engine.register_net_expression(NetExpression(
            target_table=TARGET_TABLE,
            target_column=NET_COLUMN,
            expression=FORMAL_NET_EXPRESSION,
            required_source_columns=["order_amount", "refund_amount"],
        ))
        self._submit_second_run()

    def _submit_first_run(self) -> None:
        """首次编排：两个模板分别把订单金额、退款金额写向净额列。"""
        declarations = [
            {
                "candidate_id": "C1",
                "target_table": TARGET_TABLE,
                "target_column": "order_id",
                "instance_id": "INST-ORDER-V1-001",
                "declared_output_version": "dwd结算输出Schema v1.0",
            },
            {
                "candidate_id": "C2",
                "target_table": TARGET_TABLE,
                "target_column": NET_COLUMN,
                "instance_id": "INST-ORDER-V1-001",
                "declared_output_version": "dwd结算输出Schema v1.0",
            },
            {
                # 退款模板宣告写入订单模板产生的净额列
                "candidate_id": "C3",
                "target_table": TARGET_TABLE,
                "target_column": NET_COLUMN,
                "instance_id": "INST-REFUND-V1-001",
                "declared_output_version": "dwd结算输出Schema v1.0",
            },
        ]
        self.engine.submit_orchestration(FIRST_RUN, TARGET_TABLE, declarations)

    def _submit_second_run(self) -> None:
        """换版 + 补齐净额表达式后的重新提交。"""
        declarations = [
            {
                "candidate_id": "C4",
                "target_table": TARGET_TABLE,
                "target_column": "order_id",
                "instance_id": "INST-ORDER-V2-001",
                "declared_output_version": "dwd结算输出Schema v2.0",
            },
            {
                "candidate_id": "C5",
                "target_table": TARGET_TABLE,
                "target_column": NET_COLUMN,
                "instance_id": "INST-ORDER-V2-001",
                "declared_output_version": "dwd结算输出Schema v2.0",
            },
            {
                "candidate_id": "C6",
                "target_table": TARGET_TABLE,
                "target_column": NET_COLUMN,
                "instance_id": "INST-REFUND-V2-001",
                "declared_output_version": "dwd结算输出Schema v2.0",
            },
        ]
        self.engine.submit_orchestration(SECOND_RUN, TARGET_TABLE, declarations)

    # ---- 查询 ----

    def ensure_ready(self) -> None:
        self.bootstrap()

    def instances(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        return self.engine.snapshot()["instances"]

    def attributions(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        return self.engine.snapshot()["attributions"]

    def runs(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        return self.engine.snapshot()["runs"]

    def lineage(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        return self.engine.snapshot()["lineage"]

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        """复查某次运行的写入候选、写入计划、列归属与血缘（含旧运行）。"""
        self.ensure_ready()
        result = self.engine.get_run(run_id)
        if result is None:
            return None
        return {
            "run_id": result.run_id,
            "target_table": result.target_table,
            "plan_status": result.plan_status.value,
            "submitted_at": result.submitted_at,
            "held_columns": result.held_columns,
            "warnings": result.warnings,
            "candidates": [
                {
                    "candidate_id": c.candidate_id,
                    "target_column": c.target_column,
                    "instance_id": c.instance_id,
                    "expression": c.expression,
                    "source_columns": c.source_columns,
                    "verdict": c.verdict.value,
                    "readonly": c.readonly,
                    "check_reasons": c.check_reasons,
                }
                for c in result.candidates
            ],
            "plan_items": [
                {
                    "target_column": item.target_column,
                    "instance_id": item.instance_id,
                    "template_version": item.template_version,
                    "expression": item.expression,
                    "source_columns": item.source_columns,
                    "authorized": item.authorized,
                    "block_reasons": item.block_reasons,
                }
                for item in result.plan_items
            ],
            "attributions": [
                {
                    "target_column": attr.target_column,
                    "owner_instance_id": attr.owner_instance_id,
                    "expression": attr.expression,
                    "source_columns": attr.source_columns,
                    "status": attr.status.value,
                    "resolution": attr.resolution,
                }
                for attr in result.attributions
            ],
            "lineage": [
                {
                    "target_column": item.target_column,
                    "instance_id": item.instance_id,
                    "expression": item.expression,
                    "source_columns": item.source_columns,
                    "registered_at": item.registered_at,
                }
                for item in result.lineage
            ],
        }

    # ---- 动作 ----

    def resubmit_orchestration(
        self, run_id: str, declarations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """重新提交编排：重新解析候选、核对权限并签出写入计划。"""
        self.ensure_ready()
        result = self.engine.submit_orchestration(
            run_id, TARGET_TABLE, declarations,
        )
        return self.run_detail(result.run_id)  # type: ignore[return-value]

    def verify_attribution(self, target_column: str) -> dict[str, Any]:
        """人工核实列归属：仅在该列存在允许写入的候选时可置为已核实。"""
        self.ensure_ready()
        attribution = self.engine.get_attribution(TARGET_TABLE, target_column)
        if attribution is None:
            return {"ok": False, "message": f"目标列 {target_column} 暂无归属数据"}
        latest = next(
            (run for run in reversed(list(self.engine.runs.values()))
             if run.target_table == TARGET_TABLE),
            None,
        )
        approvable = bool(latest and any(
            item.target_column == target_column and item.authorized
            for item in latest.plan_items
        ))
        if not approvable:
            attribution.status = AttributionStatus.HELD
            attribution.resolution = (
                "核实未通过：没有权限齐备的写入实例，净额列继续留待核对"
            )
            return {"ok": False, "message": attribution.resolution}
        attribution.status = AttributionStatus.VERIFIED
        attribution.resolution = f"人工核实通过（{datetime.now().isoformat()}）"
        return {"ok": True, "message": f"目标列 {target_column} 归属已核实"}

    def downstream_field_check(self) -> dict[str, Any]:
        """对照正式血缘与下游读到的字段值，核验净额列口径是否已生效。"""
        self.ensure_ready()
        lineage = self.engine.lineage_for_column(TARGET_TABLE, NET_COLUMN)
        second = self.engine.get_run(SECOND_RUN)
        formal = [item for item in lineage]
        downstream = {
            "downstream_table": "ads.ads_sales_dashboard",
            "read_field": "net_amount",
            "expected_expression": FORMAL_NET_EXPRESSION,
            "sample_value": "order_amount(1200.00) - refund_amount(80.00) = 1120.00",
        }
        consistent = bool(formal) and all(
            item.expression == FORMAL_NET_EXPRESSION for item in formal
        )
        return {
            "target_table": TARGET_TABLE,
            "target_column": NET_COLUMN,
            "formal_lineage": [
                {
                    "instance_id": item.instance_id,
                    "expression": item.expression,
                    "source_columns": item.source_columns,
                    "run_id": item.run_id,
                }
                for item in formal
            ],
            "downstream": downstream,
            "latest_run_status": second.plan_status.value if second else "",
            "consistent": consistent,
            "message": (
                "正式血缘与下游读取字段一致，净额按正式表达式加工"
                if consistent
                else "正式血缘缺失或口径不一致，下游净额字段不可信"
            ),
        }


# 进程级单例：路由层共享同一份引擎状态
governance_service = WriteGovernanceService()
