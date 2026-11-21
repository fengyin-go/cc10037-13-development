"""写入编排治理端到端核查脚本（只读核查 + 一次重提交，断言全部叙事约束）。

用法：
  python3 scripts/verify_write_governance.py            # 默认 http://127.0.0.1:8000
  BASE_URL=http://host:port python3 scripts/verify_write_governance.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TARGET_TABLE = "dw.dwd_order_settle"
NET_COLUMN = "net_amount"
FORMAL = "net_amount=order_amount-refund_amount"
FIRST_RUN = "RUN-20261120-01"
SECOND_RUN = "RUN-20261121-01"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("✓ " if condition else "✗ ") + message)
    if not condition:
        failures.append(message)


def get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode())


def post(path: str, payload: dict):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


snapshot = get("/api/write-governance/snapshot")

# 1. 模板实例带 Schema 版本，换版后新旧实例并存
versions = {(i["instance_id"], i["output_version"]) for i in snapshot["instances"]}
check(
    ("INST-ORDER-V1-001", "dwd结算输出Schema v1.0") in versions
    and ("INST-ORDER-V2-001", "dwd结算输出Schema v2.0") in versions,
    "模板换版后 v1/v2 实例并存，各自锁定输入/输出 Schema 版本",
)

# 2. 首次运行：退款实例缺公式 → 权限不足；订单实例净额候选只读；净额列留待核对
run1 = get(f"/api/write-governance/runs/{FIRST_RUN}")
cands = {c["candidate_id"]: c for c in run1["candidates"]}
check(run1["plan_status"] in ("待核实", "留待核对"), "首次运行净额列未产生正式计划")
check(NET_COLUMN in run1["held_columns"], "首次运行净额列留在待核对范围")
check(cands["C3"]["verdict"] == "权限不足", "退款实例缺失净额公式 → 权限不足")
check(
    any("缺失计算表达式" in r for r in cands["C3"]["check_reasons"]),
    "缺失公式的实例不得产生正式净额",
)
check(cands["C2"]["readonly"] and cands["C2"]["verdict"] == "只读候选",
      "归属待核实时订单实例候选只读，不能直接当成写入计划")
check(not [l for l in run1["lineage"] if l["target_column"] == NET_COLUMN],
      "首次运行未登记净额列正式血缘（其他正式列血缘不受影响）")

# 3. 旧运行写入计划与源输入仍可复查
check(any(i["target_column"] == "order_id" and i["authorized"] for i in run1["plan_items"]),
      "旧运行已授权的 order_id 写入计划仍可复查")

# 4. 补齐净额表达式 + 换版后重提：两个 v2 实例共同按正式表达式加工
run2 = get(f"/api/write-governance/runs/{SECOND_RUN}")
check(run2["plan_status"] == "正式计划" and not run2["held_columns"],
      "补齐净额表达式重新提交后签出正式写入计划")
net_plans = [i for i in run2["plan_items"] if i["target_column"] == NET_COLUMN]
check(len(net_plans) == 2 and all(i["authorized"] for i in net_plans),
      "订单/退款两个 v2 实例均获得净额列正式写入授权")
check(all(set(i["source_columns"]) == {"order_amount", "refund_amount"} for i in net_plans),
      "写入计划实际源列覆盖 order_amount 与 refund_amount")
check(
    {l["instance_id"] for l in run2["lineage"] if l["target_column"] == NET_COLUMN}
    == {"INST-ORDER-V2-001", "INST-REFUND-V2-001"},
    "正式血缘登记净额列采用的源列与实例",
)
check(all(l["expression"] == FORMAL for l in run2["lineage"] if l["target_column"] == NET_COLUMN),
      "血缘表达式与正式净额表达式一致")

# 5. 下游读到的字段值与正式血缘对照
downstream = get("/api/write-governance/downstream-check")
check(downstream["consistent"], "正式血缘与下游读取字段值一致")

# 6. 权限规则：版本失配 / 来源权限不足的重提交必须被拦截
blocked = post("/api/write-governance/submit", {
    "run_id": "RUN-CHECK-VERSION",
    "declarations": [{
        "candidate_id": "B1", "target_table": TARGET_TABLE, "target_column": NET_COLUMN,
        "instance_id": "INST-ORDER-V2-001",
        "declared_output_version": "dwd结算输出Schema v1.0",
    }],
})
check(
    blocked["candidates"][0]["verdict"] == "权限不足"
    and any("版本失配" in r for r in blocked["candidates"][0]["check_reasons"]),
    "模板换版后旧 Schema 版本声明被拦截",
)

# 7. 通用资源路由：三张治理表可查询、动作可流转
plans = get("/api/write_plan?size=20")
check(plans["total"] >= 3, "写入计划模块可通过通用资源路由查询")
instances = get("/api/template_instance?size=20")
check(instances["total"] >= 4, "模板实例模块可通过通用资源路由查询")

print()
if failures:
    print(f"核查未通过：{len(failures)} 项")
    sys.exit(1)
print("全部核查通过")
