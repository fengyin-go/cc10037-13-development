# ETL编排与数据质量中心

面向数据仓库ETL作业场景，提供流水线编排、质量规则、依赖调度和回刷补偿的ETL治理平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/views/WriteGovernanceView.vue 写入编排治理工作台（候选/计划/血缘）
│   ├── src/data/modules.ts              21个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/routers/write_governance.py 写入编排治理接口（提交/复查/核实/下游核对）
│   ├── app/engine/write_governance.py  Schema版本/列归属/写入权限/写入计划/净额血缘引擎
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── scripts/
│   └── verify_write_governance.py  写入编排治理端到端核查脚本
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 流水线定义 | `pipeline_def` | ETL流水线 | 流水线名称、处理阶段、输入源表 |
| 任务节点 | `task_node` | 处理节点 | 节点名称、所属管线、节点类型 |
| 质量规则 | `quality_rule` | 校验规则 | 规则名称、目标表、校验字段 |
| 质量执行 | `validation_run` | 校验批次 | 批次标识、目标表、校验分区 |
| 依赖调度 | `depend_scheduler` | 调度配置 | 配置名称、目标管线、触发方式 |
| 滑动窗口 | `sliding_window` | 窗口配置 | 窗口名称、目标表、窗口字段 |
| 回刷补偿 | `rerun_compensation` | 重跑任务 | 任务名称、目标管线、重跑范围 |
| 水位追踪 | `watermark_tracker` | 水位记录 | 管线标识、分区字段、当前水位 |
| 资源池 | `resource_pool` | 计算资源 | 池名称、总核数、总内存 |
| 血缘图谱 | `lineage_graph` | 血缘边 | 源节点、目标节点、传递字段 |
| 异常捕获 | `exception_capture` | 异常记录 | 发生时间、所属管线、异常类型 |
| 模板仓库 | `template_store` | 处理模板 | 模板名称、处理类型、输入Schema |
| 模板实例 | `template_instance` | 模板实例 | 实例标识、模板版本、输入/输出Schema版本、输出字段映射 |
| 列归属数据 | `column_attribution` | 列归属 | 目标表、目标列、归属实例、计算表达式、来源列 |
| 写入计划 | `write_plan` | 写入计划 | 运行标识、目标列、签出实例、实际源列、权限判定、血缘登记 |
| 分区扫描 | `partition_scan` | 扫描报告 | 报告时间、目标表、分区总数 |
| 配置迁移 | `config_migration` | 迁移任务 | 任务名称、源环境、目标环境 |
| Schema演进 | `schema_evolution` | 变更记录 | 变更时间、目标表、变更类型 |
| 回填追踪 | `backfill_tracker` | 回填进度 | 追踪ID、回填任务、当前分区 |
| 成本分析 | `cost_analysis` | 成本快照 | 快照日期、管线标识、计算时长 |
| 告警策略 | `alert_policy` | 告警规则 | 规则名称、监控对象、告警条件 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 写入编排治理（目标列写入权限 → 写入计划 → 净额血缘）

`/write-governance` 工作台与 `/api/write-governance/*` 接口承载模板实例到目标列
写入的完整治理链路：

1. **Schema 版本**：模板实例化即锁定输入/输出 Schema 版本与输出字段映射；模板
   换版后产生新实例，编排关联新实例，旧运行的写入计划与源输入仍可复查。
2. **列归属数据**：解析输出字段映射，标明哪个模板实例可以给目标列写值、使用哪条
   计算表达式；归属待核实时写入候选只读，不能直接当成写入计划。
3. **写入权限判定**：逐候选追到实例及其源列——实例须激活、Schema 版本须匹配、
   目标列须在输出映射内、源列须在输入 Schema 授权范围内、公式不得缺失；缺失公式
   或来源权限不足的实例不得产生正式净额。
4. **写入计划签出**：同一目标表有订单/退款两个模板写向净额列时，必须能共同满足
   正式净额表达式（`net_amount=order_amount-refund_amount`）才签出正式计划，
   否则整列留待核对。
5. **血缘登记与下游核对**：正式计划入库后登记净额列采用的源列与实例，并对照
   下游 `ads.ads_sales_dashboard` 读到的字段值核验口径。

内置叙事数据复放两次编排：`RUN-20261120-01`（退款实例缺公式、净额列留待核对、
候选只读、无正式净额血缘）与 `RUN-20261121-01`（补齐净额表达式并换版后重提、
签出正式计划并登记血缘）。

端到端核查（需先启动后端）：

```bash
python3 scripts/verify_write_governance.py
```

领域：数据工程
子方向：数仓与数据湖
