"""写入编排治理 API：模板实例 Schema 版本、列归属、写入权限、写入计划与净额血缘。

与通用资源路由（/api/{module}）互补：通用路由负责三张治理表的 CRUD/动作，
本路由负责跨表的编排治理动作——提交编排、复查运行、核实归属、下游核对。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.write_governance import (
    FIRST_RUN,
    SECOND_RUN,
    governance_service,
)

router = APIRouter(prefix="/api/write-governance", tags=["写入编排治理"])


@router.get("/snapshot")
def governance_snapshot() -> dict[str, Any]:
    """治理总览：实例（含 Schema 版本/字段映射）、净额表达式、列归属、运行与血缘。"""
    governance_service.ensure_ready()
    snapshot = governance_service.engine.snapshot()
    snapshot["first_run_id"] = FIRST_RUN
    snapshot["second_run_id"] = SECOND_RUN
    return snapshot


@router.get("/instances")
def list_instances() -> dict[str, Any]:
    """模板实例清单：标明输入/输出 Schema 版本、授权源列与输出字段映射。"""
    return {"items": governance_service.instances()}


@router.get("/attributions")
def list_attributions() -> dict[str, Any]:
    """列归属数据：哪个实例可以给目标列写值、用哪条表达式、来源列与核实状态。"""
    return {"items": governance_service.attributions()}


@router.get("/runs")
def list_runs() -> dict[str, Any]:
    """历次编排运行摘要（模板换版后旧运行仍在列，可复查）。"""
    return {"items": governance_service.runs()}


@router.get("/lineage")
def list_lineage() -> dict[str, Any]:
    """正式字段血缘：净额列采用的源列与实例。"""
    return {"items": governance_service.lineage()}


@router.get("/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    """复查某次运行的候选判定、写入计划、列归属与血缘（旧运行只读可查）。"""
    detail = governance_service.run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"编排运行 {run_id} 不存在")
    return detail


@router.post("/submit")
def submit_orchestration(body: dict[str, Any]) -> dict[str, Any]:
    """提交/重新提交编排。

    body:
      run_id: 运行标识（换版重提使用新标识，旧运行保留）
      declarations: [{candidate_id, target_table, target_column,
                      instance_id, declared_output_version}]
    """
    run_id = str(body.get("run_id", "")).strip()
    declarations = body.get("declarations", [])
    if not run_id:
        raise HTTPException(status_code=400, detail="缺少 run_id")
    if not declarations:
        raise HTTPException(status_code=400, detail="declarations 不能为空")
    detail = governance_service.resubmit_orchestration(run_id, declarations)
    return detail


@router.post("/attributions/verify")
def verify_attribution(body: dict[str, Any]) -> dict[str, Any]:
    """人工核实列归属；无权限齐备实例时退回留待核对。"""
    target_column = str(body.get("target_column", "")).strip()
    if not target_column:
        raise HTTPException(status_code=400, detail="缺少 target_column")
    return governance_service.verify_attribution(target_column)


@router.get("/downstream-check")
def downstream_check() -> dict[str, Any]:
    """对照正式血缘与下游读到的字段值，核验净额口径是否生效。"""
    return governance_service.downstream_field_check()
