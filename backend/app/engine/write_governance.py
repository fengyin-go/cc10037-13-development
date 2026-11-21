"""写入编排治理引擎：模板实例 Schema 版本、列归属、写入权限、写入计划与字段血缘。

核心概念
--------
- 模板实例（TemplateInstance）：模板换版后会产生新实例，实例锁定当时的输入/输出
  Schema 版本、输出字段映射和计算表达式。旧运行仍引用旧实例，可复查不可改写。
- 列归属（ColumnAttribution）：目标表每个输出列的归属数据，标明哪个模板实例可以
  给该列写值、使用哪条计算表达式、依赖哪些源列。
- 写入候选（WriteCandidate）：编排解析输出字段映射后得到的候选写入声明。归属待
  核实时候选只读，不能直接当成写入计划。
- 写入计划（WritePlan）：编排按列归属数据签出的正式计划。每个正式输出列的写入
  权限都要追到实例及其源列；缺失公式或来源权限不足的实例不得产生正式写入。
- 净额表达式（NetExpression）：目标列的正式加工口径（如净额=订单金额-退款金额），
  未补齐时该列只能留在待核对范围。
- 字段血缘（FieldLineage）：正式写入计划入库后登记的净额列源列与实例血缘。

权限判定规则（每个候选逐条核对，可复查）
----------------------------------------
1. 实例状态必须为「已激活」，弃用实例只能出现在历史运行里；
2. 实例锁定的输入/输出 Schema 版本必须与编排声明的版本一致（模板换版后旧版本
   实例不得继续产生正式写入）；
3. 声明的目标列必须出现在实例的输出字段映射里；
4. 表达式引用的每个源列都必须在实例输入 Schema 已授权源列范围内（来源权限）；
5. 必须存在计算表达式；目标列若登记了正式净额表达式，实例表达式必须与之一致；
6. 同一目标列存在多个写入实例时，若不能共同满足正式净额表达式，整列留待核对，
   任何候选都不得单独签出为写入计划。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AttributionStatus(str, Enum):
    """列归属核实状态。"""

    PENDING = "归属待核实"
    VERIFIED = "归属已核实"
    HELD = "留待核对"


class CandidateVerdict(str, Enum):
    """写入候选的权限判定结论。"""

    READONLY = "只读候选"          # 归属待核实，可展开查看但不能签出
    APPROVED = "允许写入"          # 权限齐备，可签出写入计划
    REJECTED = "权限不足"          # 缺公式 / 来源权限不足 / 版本失配等


class PlanStatus(str, Enum):
    """写入计划状态。"""

    DRAFT = "待核实"
    FORMAL = "正式计划"
    HELD = "留待核对"
    ARCHIVED = "历史归档"          # 模板换版后旧运行的计划，只读复查


@dataclass
class SchemaVersion:
    """模板实例锁定的输入/输出 Schema 版本。"""

    input_version: str
    output_version: str
    input_columns: list[str] = field(default_factory=list)
    output_columns: list[str] = field(default_factory=list)


@dataclass
class FieldMapping:
    """模板实例的一条输出字段映射：目标列 ← 表达式(源列...)。"""

    target_column: str
    expression: str                       # 计算表达式，空串表示缺失公式
    source_columns: list[str] = field(default_factory=list)


@dataclass
class TemplateInstance:
    """模板实例：一次模板实例化的不可变快照（含 Schema 版本与字段映射）。"""

    instance_id: str
    template_name: str
    template_version: str
    schema: SchemaVersion
    mappings: list[FieldMapping]
    active: bool = True                   # 弃用模板的实例置为 False
    created_at: str = ""

    def mapping_for(self, target_column: str) -> FieldMapping | None:
        for mapping in self.mappings:
            if mapping.target_column == target_column:
                return mapping
        return None


@dataclass
class NetExpression:
    """目标列的正式加工口径（净额表达式）。"""

    target_table: str
    target_column: str
    expression: str                       # 正式表达式；空串表示尚未补齐
    required_source_columns: list[str] = field(default_factory=list)
    registered: bool = False              # 是否已登记为正式口径


@dataclass
class ColumnAttribution:
    """目标列归属数据：谁可以写、用哪条表达式、依赖哪些源列。"""

    target_table: str
    target_column: str
    owner_instance_id: str                # 归属的模板实例
    expression: str
    source_columns: list[str] = field(default_factory=list)
    status: AttributionStatus = AttributionStatus.PENDING
    resolution: str = ""                  # 核实结论 / 留待核对原因


@dataclass
class WriteCandidate:
    """编排解析输出字段映射得到的写入候选声明。"""

    candidate_id: str
    target_table: str
    target_column: str
    instance_id: str
    declared_output_version: str
    expression: str
    source_columns: list[str] = field(default_factory=list)
    verdict: CandidateVerdict = CandidateVerdict.READONLY
    readonly: bool = True                 # 归属待核实时一律只读
    check_reasons: list[str] = field(default_factory=list)


@dataclass
class WritePlanItem:
    """写入计划中的一个正式输出列条目。"""

    target_table: str
    target_column: str
    instance_id: str
    template_version: str
    expression: str
    source_columns: list[str] = field(default_factory=list)
    authorized: bool = False
    block_reasons: list[str] = field(default_factory=list)


@dataclass
class FieldLineage:
    """正式血缘登记：净额列采用的源列与实例。"""

    target_table: str
    target_column: str
    instance_id: str
    expression: str
    source_columns: list[str] = field(default_factory=list)
    registered_at: str = ""
    run_id: str = ""


@dataclass
class SubmissionResult:
    """一次编排提交的完整治理结果。"""

    run_id: str
    target_table: str
    plan_status: PlanStatus
    candidates: list[WriteCandidate]
    plan_items: list[WritePlanItem]
    attributions: list[ColumnAttribution]
    lineage: list[FieldLineage]
    held_columns: list[str]
    warnings: list[str]
    submitted_at: str


def _now() -> str:
    return datetime.now().isoformat()


class WriteGovernanceEngine:
    """写入编排治理引擎。

    用法:
        eng = WriteGovernanceEngine()
        eng.register_instance(instance)
        eng.register_net_expression(net)
        result = eng.submit_orchestration(run_id, target_table, declarations)
    """

    def __init__(self) -> None:
        self._instances: dict[str, TemplateInstance] = {}
        self._net_expr: dict[tuple[str, str], NetExpression] = {}
        self._attributions: dict[tuple[str, str], ColumnAttribution] = {}
        self._runs: dict[str, SubmissionResult] = {}
        self._lineage: list[FieldLineage] = []

    # ---- 注册 ----

    def register_instance(self, instance: TemplateInstance) -> None:
        self._instances[instance.instance_id] = instance

    def get_instance(self, instance_id: str) -> TemplateInstance | None:
        return self._instances.get(instance_id)

    def register_net_expression(self, net: NetExpression) -> None:
        net.registered = bool(net.expression.strip())
        self._net_expr[(net.target_table, net.target_column)] = net

    def get_net_expression(self, table: str, column: str) -> NetExpression | None:
        return self._net_expr.get((table, column))

    def register_attribution(self, attribution: ColumnAttribution) -> None:
        self._attributions[(attribution.target_table, attribution.target_column)] = attribution

    def get_attribution(self, table: str, column: str) -> ColumnAttribution | None:
        return self._attributions.get((table, column))

    @property
    def runs(self) -> dict[str, SubmissionResult]:
        return self._runs

    @property
    def lineage(self) -> list[FieldLineage]:
        return list(self._lineage)

    # ---- 单候选权限判定（追到实例及其源列） ----

    def evaluate_candidate(
        self, declaration: dict[str, Any]
    ) -> tuple[WriteCandidate, TemplateInstance | None]:
        """对一条写入声明做完整权限判定。

        declaration 字段：candidate_id, target_table, target_column,
        instance_id, declared_output_version, expression, source_columns
        """
        candidate = WriteCandidate(
            candidate_id=declaration["candidate_id"],
            target_table=declaration["target_table"],
            target_column=declaration["target_column"],
            instance_id=declaration["instance_id"],
            declared_output_version=declaration.get("declared_output_version", ""),
            expression=str(declaration.get("expression", "") or ""),
            source_columns=list(declaration.get("source_columns", [])),
        )

        instance = self._instances.get(candidate.instance_id)
        reasons: list[str] = []

        # 规则1：实例必须存在且已激活
        if instance is None:
            reasons.append(f"实例 {candidate.instance_id} 不存在，无法追溯写入来源")
        elif not instance.active:
            reasons.append(f"实例 {candidate.instance_id} 已随模板弃用，不得产生正式写入")

        if instance is not None and instance.active:
            # 规则2：Schema 版本必须与编排声明一致（模板换版后旧版本只读）
            locked_out = instance.schema.output_version
            if candidate.declared_output_version and locked_out != candidate.declared_output_version:
                reasons.append(
                    f"输出Schema版本失配：实例锁定 {locked_out}，编排声明 "
                    f"{candidate.declared_output_version}（模板可能已换版）"
                )

            # 规则3：目标列必须在实例输出字段映射里
            mapping = instance.mapping_for(candidate.target_column)
            if mapping is None:
                reasons.append(
                    f"实例输出字段映射中不存在目标列 {candidate.target_column}，无写入权限"
                )
            else:
                # 以实例登记的映射为准，回填真实表达式与源列用于核查
                candidate.expression = mapping.expression
                candidate.source_columns = list(mapping.source_columns)

                # 规则4：来源权限——表达式源列必须在实例输入 Schema 授权范围内
                authorized = set(instance.schema.input_columns)
                unauthorized = [
                    col for col in mapping.source_columns if col not in authorized
                ]
                if unauthorized:
                    reasons.append(
                        "来源权限不足：源列 "
                        f"{'、'.join(unauthorized)} 不在实例输入Schema授权范围"
                    )

                # 规则5a：缺失公式不得产生正式写入
                if not mapping.expression.strip():
                    reasons.append("缺失计算表达式，不得产生正式写入")

        # 正式净额表达式的口径核对在列级别完成：
        # - 单实例写整列时，实例表达式必须与正式表达式逐字一致；
        # - 多实例共同加工时，各实例只承担自己的来源表达式，由列级别核对
        #   全部实例的源列能否覆盖净额表达式所需源列。

        # 归属状态决定只读与否
        attribution = self._attributions.get(
            (candidate.target_table, candidate.target_column)
        )
        attribution_pending = (
            attribution is None
            or attribution.status == AttributionStatus.PENDING
        )

        candidate.check_reasons = reasons
        if reasons:
            candidate.verdict = CandidateVerdict.REJECTED
            candidate.readonly = True
        elif attribution_pending:
            candidate.verdict = CandidateVerdict.READONLY
            candidate.readonly = True
            candidate.check_reasons.append("列归属待核实，候选保持只读，不能直接签出写入计划")
        else:
            candidate.verdict = CandidateVerdict.APPROVED
            candidate.readonly = False

        return candidate, instance

    # ---- 编排提交：解析候选 → 列归属 → 签出写入计划 → 登记血缘 ----

    def submit_orchestration(
        self,
        run_id: str,
        target_table: str,
        declarations: list[dict[str, Any]],
    ) -> SubmissionResult:
        """提交一次编排，返回候选、列归属、写入计划与血缘的完整结论。"""
        candidates: list[WriteCandidate] = []
        instances_by_candidate: dict[str, TemplateInstance | None] = {}
        for declaration in declarations:
            candidate, instance = self.evaluate_candidate(declaration)
            candidates.append(candidate)
            instances_by_candidate[candidate.candidate_id] = instance

        # 按目标列汇总候选
        columns: dict[str, list[WriteCandidate]] = {}
        for candidate in candidates:
            columns.setdefault(candidate.target_column, []).append(candidate)

        plan_items: list[WritePlanItem] = []
        attributions: list[ColumnAttribution] = []
        lineage: list[FieldLineage] = []
        held_columns: list[str] = []
        warnings: list[str] = []
        any_formal = False

        for column, col_candidates in columns.items():
            net = self._net_expr.get((target_table, column))
            approved = [c for c in col_candidates if c.verdict == CandidateVerdict.APPROVED]
            rejected = [c for c in col_candidates if c.verdict == CandidateVerdict.REJECTED]

            # 规则6：多实例写同一列时，必须能共同满足正式净额表达式
            multi_writers = len({c.instance_id for c in col_candidates}) > 1
            block_reasons: list[str] = []
            if rejected:
                for cand in rejected:
                    block_reasons.extend(
                        f"[候选 {cand.candidate_id}/{cand.instance_id}] {reason}"
                        for reason in cand.check_reasons
                    )

            formal_ready = True
            if net is None or not net.registered:
                formal_ready = False
                block_reasons.append(
                    f"目标列 {column} 尚未补齐正式净额表达式，留在待核对范围"
                )
            elif not multi_writers:
                # 单实例写整列：实例表达式必须与正式净额表达式逐字一致
                sole = col_candidates[0]
                if sole.expression.strip() != net.expression.strip():
                    formal_ready = False
                    block_reasons.append(
                        f"表达式与正式净额口径不一致：登记「{net.expression}」，实例「{sole.expression}」"
                    )
            else:
                # 多实例共同加工：净额表达式要求的源列必须由全部候选实例共同
                # 覆盖，且每个候选实例来源权限齐备（无被拒绝候选）
                covered: set[str] = set()
                for cand in approved:
                    covered.update(cand.source_columns)
                missing = [
                    col for col in net.required_source_columns if col not in covered
                ]
                if missing or len(approved) != len(col_candidates):
                    formal_ready = False
                    detail = (
                        f"净额表达式「{net.expression}」所需源列未被全部候选实例覆盖"
                        f"（缺：{'、'.join(missing) or '存在未授权候选'}）"
                    )
                    block_reasons.append(detail)

            if formal_ready and approved and not block_reasons:
                # 签出正式写入计划：每个允许写入的实例一条
                for cand in approved:
                    instance = instances_by_candidate[cand.candidate_id]
                    item = WritePlanItem(
                        target_table=target_table,
                        target_column=column,
                        instance_id=cand.instance_id,
                        template_version=instance.template_version if instance else "",
                        expression=cand.expression,
                        source_columns=list(cand.source_columns),
                        authorized=True,
                    )
                    plan_items.append(item)
                    # 登记正式血缘：净额列采用的源列与实例
                    record = FieldLineage(
                        target_table=target_table,
                        target_column=column,
                        instance_id=cand.instance_id,
                        expression=cand.expression,
                        source_columns=list(cand.source_columns),
                        registered_at=_now(),
                        run_id=run_id,
                    )
                    lineage.append(record)
                    self._lineage.append(record)

                # 落定列归属
                owner = approved[0]
                attribution = ColumnAttribution(
                    target_table=target_table,
                    target_column=column,
                    owner_instance_id=owner.instance_id,
                    expression=net.expression if net else owner.expression,
                    source_columns=sorted(
                        {col for cand in approved for col in cand.source_columns}
                    ),
                    status=AttributionStatus.VERIFIED,
                    resolution=(
                        f"{len(approved)} 个实例按正式净额表达式「"
                        f"{net.expression if net else owner.expression}」共同写入"
                        if multi_writers
                        else f"实例 {owner.instance_id} 经源列权限与公式核对后单独写入"
                    ),
                )
                self._attributions[(target_table, column)] = attribution
                attributions.append(attribution)
                any_formal = True
            else:
                # 留待核对：候选只读，不产生正式写入计划与血缘
                held_columns.append(column)
                attribution = ColumnAttribution(
                    target_table=target_table,
                    target_column=column,
                    owner_instance_id="",
                    expression=net.expression if net and net.registered else "",
                    source_columns=sorted(
                        {col for cand in col_candidates for col in cand.source_columns}
                    ),
                    status=AttributionStatus.HELD,
                    resolution="；".join(block_reasons) or "归属待核实",
                )
                self._attributions[(target_table, column)] = attribution
                attributions.append(attribution)
                warnings.append(f"目标列 {column} 留待核对，{len(col_candidates)} 个候选均未签出写入计划")

                # 即便留待核对，也产出只读的计划草稿（authorized=False）供展开复查
                for cand in col_candidates:
                    instance = instances_by_candidate[cand.candidate_id]
                    plan_items.append(WritePlanItem(
                        target_table=target_table,
                        target_column=column,
                        instance_id=cand.instance_id,
                        template_version=instance.template_version if instance else "",
                        expression=cand.expression,
                        source_columns=list(cand.source_columns),
                        authorized=False,
                        block_reasons=list(cand.check_reasons) or ["列归属待核实"],
                    ))

        plan_status = PlanStatus.FORMAL if any_formal and not held_columns else (
            PlanStatus.HELD if held_columns and not any_formal else PlanStatus.DRAFT
        )

        result = SubmissionResult(
            run_id=run_id,
            target_table=target_table,
            plan_status=plan_status,
            candidates=candidates,
            plan_items=plan_items,
            attributions=attributions,
            lineage=lineage,
            held_columns=held_columns,
            warnings=warnings,
            submitted_at=_now(),
        )
        self._runs[run_id] = result
        return result

    # ---- 复查：模板换版后旧运行的写入计划与源输入仍可查 ----

    def get_run(self, run_id: str) -> SubmissionResult | None:
        return self._runs.get(run_id)

    def lineage_for_column(self, table: str, column: str) -> list[FieldLineage]:
        return [
            item for item in self._lineage
            if item.target_table == table and item.target_column == column
        ]

    def snapshot(self) -> dict[str, Any]:
        """引擎当前状态快照，供列表/概览消费。"""
        return {
            "instances": [
                {
                    "instance_id": inst.instance_id,
                    "template_name": inst.template_name,
                    "template_version": inst.template_version,
                    "input_version": inst.schema.input_version,
                    "output_version": inst.schema.output_version,
                    "input_columns": inst.schema.input_columns,
                    "output_columns": inst.schema.output_columns,
                    "mappings": [
                        {
                            "target_column": m.target_column,
                            "expression": m.expression,
                            "source_columns": m.source_columns,
                        }
                        for m in inst.mappings
                    ],
                    "active": inst.active,
                    "created_at": inst.created_at,
                }
                for inst in self._instances.values()
            ],
            "net_expressions": [
                {
                    "target_table": net.target_table,
                    "target_column": net.target_column,
                    "expression": net.expression,
                    "required_source_columns": net.required_source_columns,
                    "registered": net.registered,
                }
                for net in self._net_expr.values()
            ],
            "attributions": [
                {
                    "target_table": attr.target_table,
                    "target_column": attr.target_column,
                    "owner_instance_id": attr.owner_instance_id,
                    "expression": attr.expression,
                    "source_columns": attr.source_columns,
                    "status": attr.status.value,
                    "resolution": attr.resolution,
                }
                for attr in self._attributions.values()
            ],
            "runs": [
                {
                    "run_id": run.run_id,
                    "target_table": run.target_table,
                    "plan_status": run.plan_status.value,
                    "held_columns": run.held_columns,
                    "submitted_at": run.submitted_at,
                    "formal_items": [
                        {
                            "column": item.target_column,
                            "instance_id": item.instance_id,
                            "template_version": item.template_version,
                            "expression": item.expression,
                            "source_columns": item.source_columns,
                        }
                        for item in run.plan_items if item.authorized
                    ],
                }
                for run in self._runs.values()
            ],
            "lineage": [
                {
                    "target_table": item.target_table,
                    "target_column": item.target_column,
                    "instance_id": item.instance_id,
                    "expression": item.expression,
                    "source_columns": item.source_columns,
                    "run_id": item.run_id,
                    "registered_at": item.registered_at,
                }
                for item in self._lineage
            ],
        }
