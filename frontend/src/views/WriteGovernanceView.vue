<template>
  <section class="page governance-page">
    <header class="page-head">
      <div>
        <h2>写入编排治理</h2>
        <p class="page-desc">
          模板实例输入/输出 Schema 版本 · 列归属与输出字段映射 · 目标列写入权限检查 ·
          写入计划签出与净额字段血缘
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="refresh-governance" type="button" @click="reload">刷新治理数据</button>
        <button class="btn primary" data-testid="downstream-check" type="button" @click="checkDownstream">
          对照下游字段核对
        </button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <!-- 1. 概览卡片 -->
    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">模板实例（含历史版本）</span>
        <strong class="stat-value">{{ snapshot?.instances.length ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">列归属待核实/留待核对</span>
        <strong class="stat-value">{{ pendingAttributionCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">编排运行</span>
        <strong class="stat-value">{{ snapshot?.runs.length ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">正式字段血缘条目</span>
        <strong class="stat-value">{{ snapshot?.lineage.length ?? 0 }}</strong>
      </article>
    </div>

    <!-- 2. 正式净额表达式 -->
    <section class="gov-block">
      <h3>正式加工口径（净额表达式登记）</h3>
      <table class="data-table">
        <thead>
          <tr><th>目标表</th><th>目标列</th><th>正式表达式</th><th>所需源列</th><th>登记状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="net in snapshot?.net_expressions ?? []" :key="`${net.target_table}.${net.target_column}`">
            <td>{{ net.target_table }}</td>
            <td>{{ net.target_column }}</td>
            <td><code>{{ net.expression || '（未补齐）' }}</code></td>
            <td>{{ net.required_source_columns.join('、') || '—' }}</td>
            <td>
              <span class="tag" :class="net.registered ? 'tag-ok' : 'tag-hold'">
                {{ net.registered ? '已登记正式口径' : '待补齐' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 3. 模板实例与 Schema 版本 -->
    <section class="gov-block">
      <h3>模板实例：锁定的输入/输出 Schema 版本与输出字段映射</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>实例标识</th><th>模板</th><th>模板版本</th>
            <th>输入Schema版本</th><th>输出Schema版本</th>
            <th>授权源列</th><th>输出字段映射（目标列 ← 表达式）</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="inst in snapshot?.instances ?? []" :key="inst.instance_id">
            <td>{{ inst.instance_id }}</td>
            <td>{{ inst.template_name }}</td>
            <td>{{ inst.template_version }}</td>
            <td>{{ inst.input_version }}</td>
            <td>{{ inst.output_version }}</td>
            <td>{{ inst.input_columns.join('、') }}</td>
            <td>
              <div v-for="m in inst.mappings" :key="`${inst.instance_id}-${m.target_column}`" class="mapping-line">
                <strong>{{ m.target_column }}</strong>
                <template v-if="m.expression"> ← <code>{{ m.expression }}</code>
                  <span class="muted">（源列：{{ m.source_columns.join('、') }}）</span>
                </template>
                <template v-else>
                  <span class="tag tag-reject">缺失公式</span>
                </template>
              </div>
            </td>
            <td>
              <span class="tag" :class="inst.active ? 'tag-ok' : 'tag-reject'">
                {{ inst.active ? '已激活' : '已停用' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 4. 列归属数据 -->
    <section class="gov-block">
      <h3>列归属数据：哪个实例可以给目标列写值、使用哪条计算表达式</h3>
      <table class="data-table">
        <thead>
          <tr><th>目标表</th><th>目标列</th><th>归属实例</th><th>计算表达式</th><th>来源列</th><th>归属状态</th><th>核实结论</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="attr in snapshot?.attributions ?? []" :key="`${attr.target_table}.${attr.target_column}`">
            <td>{{ attr.target_table }}</td>
            <td>{{ attr.target_column }}</td>
            <td>{{ attr.owner_instance_id || '—' }}</td>
            <td><code>{{ attr.expression || '—' }}</code></td>
            <td>{{ attr.source_columns.join('、') }}</td>
            <td><span class="tag" :class="attributionTagClass(attr.status)">{{ attr.status }}</span></td>
            <td class="muted">{{ attr.resolution }}</td>
            <td>
              <button
                v-if="attr.status !== '归属已核实'"
                class="link"
                type="button"
                :data-testid="`verify-${attr.target_column}`"
                @click="onVerify(attr.target_column)"
              >
                核实归属
              </button>
              <span v-else class="muted">已核实</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 5. 编排运行：候选可展开，待核实时只读 -->
    <section class="gov-block">
      <h3>编排运行与写入候选（归属待核实时候选只读，不能直接当成写入计划）</h3>
      <div class="run-tabs">
        <button
          v-for="run in snapshot?.runs ?? []"
          :key="run.run_id"
          type="button"
          class="btn"
          :class="{ primary: run.run_id === selectedRunId }"
          :data-testid="`run-tab-${run.run_id}`"
          @click="selectRun(run.run_id)"
        >
          {{ run.run_id }} · {{ run.plan_status }}
        </button>
      </div>

      <div v-if="runDetail" class="run-detail" :data-testid="`run-detail-${runDetail.run_id}`">
        <p class="run-meta">
          目标表：{{ runDetail.target_table }} ｜ 计划状态：
          <span class="tag" :class="runDetail.plan_status === '正式计划' ? 'tag-ok' : 'tag-hold'">
            {{ runDetail.plan_status }}
          </span>
          ｜ 留待核对列：{{ runDetail.held_columns.join('、') || '无' }}
        </p>
        <ul v-if="runDetail.warnings.length" class="warning-list">
          <li v-for="w in runDetail.warnings" :key="w">{{ w }}</li>
        </ul>

        <h4>写入候选（展开查看权限判定）</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>候选</th><th>目标列</th><th>实例</th><th>计算表达式</th><th>实际源列</th>
              <th>权限判定</th><th>只读</th><th>核查原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="cand in runDetail.candidates" :key="cand.candidate_id" :data-testid="`candidate-${cand.candidate_id}`">
              <td>{{ cand.candidate_id }}</td>
              <td>{{ cand.target_column }}</td>
              <td>{{ cand.instance_id }}</td>
              <td><code>{{ cand.expression || '（缺失公式）' }}</code></td>
              <td>{{ cand.source_columns.join('、') || '—' }}</td>
              <td><span class="tag" :class="verdictTagClass(cand.verdict)">{{ cand.verdict }}</span></td>
              <td>
                <span class="tag" :class="cand.readonly ? 'tag-hold' : 'tag-ok'">
                  {{ cand.readonly ? '只读' : '可签出' }}
                </span>
              </td>
              <td class="muted">
                <ul class="reason-list">
                  <li v-for="(reason, idx) in cand.check_reasons" :key="idx">{{ reason }}</li>
                  <li v-if="!cand.check_reasons.length">权限齐备，可参与正式写入</li>
                </ul>
              </td>
            </tr>
          </tbody>
        </table>

        <h4>写入计划（按列归属签出；未授权条目为只读草稿，不产生正式净额）</h4>
        <table class="data-table">
          <thead>
            <tr><th>目标列</th><th>签出实例</th><th>模板版本</th><th>表达式</th><th>实际源列</th><th>授权</th><th>阻断原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in runDetail.plan_items" :key="`${item.instance_id}-${item.target_column}-${idx}`">
              <td>{{ item.target_column }}</td>
              <td>{{ item.instance_id }}</td>
              <td>{{ item.template_version }}</td>
              <td><code>{{ item.expression || '—' }}</code></td>
              <td>{{ item.source_columns.join('、') }}</td>
              <td>
                <span class="tag" :class="item.authorized ? 'tag-ok' : 'tag-reject'">
                  {{ item.authorized ? '正式写入' : '未授权' }}
                </span>
              </td>
              <td class="muted">{{ item.block_reasons.join('；') || '—' }}</td>
            </tr>
          </tbody>
        </table>

        <h4>本次运行登记的字段血缘</h4>
        <table v-if="runDetail.lineage.length" class="data-table">
          <thead>
            <tr><th>目标列</th><th>采用实例</th><th>表达式</th><th>源列</th><th>登记时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="(line, idx) in runDetail.lineage" :key="idx">
              <td>{{ line.target_column }}</td>
              <td>{{ line.instance_id }}</td>
              <td><code>{{ line.expression }}</code></td>
              <td>{{ line.source_columns.join('、') }}</td>
              <td>{{ line.registered_at }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">本次运行没有签出正式写入计划，未登记字段血缘（候选仍可在上表展开复查）。</p>
      </div>
    </section>

    <!-- 6. 正式血缘与下游核对 -->
    <section class="gov-block">
      <h3>净额列正式血缘（源列与实例）与下游读取核对</h3>
      <table class="data-table">
        <thead>
          <tr><th>目标表</th><th>目标列</th><th>采用实例</th><th>表达式</th><th>源列</th><th>来源运行</th></tr>
        </thead>
        <tbody>
          <tr v-for="(line, idx) in snapshot?.lineage ?? []" :key="idx">
            <td>{{ line.target_table }}</td>
            <td>{{ line.target_column }}</td>
            <td>{{ line.instance_id }}</td>
            <td><code>{{ line.expression }}</code></td>
            <td>{{ line.source_columns.join('、') }}</td>
            <td>{{ line.run_id }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="downstream" class="downstream-box" data-testid="downstream-box">
        <p>
          下游表 <strong>{{ downstream.downstream.downstream_table }}</strong> 读取字段
          <strong>{{ downstream.downstream.read_field }}</strong>，期望口径
          <code>{{ downstream.downstream.expected_expression }}</code>
        </p>
        <p class="muted">样例值核对：{{ downstream.downstream.sample_value }}</p>
        <span class="tag" :class="downstream.consistent ? 'tag-ok' : 'tag-reject'">
          {{ downstream.consistent ? '正式血缘与下游字段一致' : '口径不一致，下游字段不可信' }}
        </span>
        <p class="muted">{{ downstream.message }}</p>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  loadDownstreamCheck,
  loadGovernanceSnapshot,
  loadRunDetail,
  verifyAttribution,
  type DownstreamCheck,
  type GovernanceSnapshot,
  type RunDetail,
} from '@/api/write-governance'

const snapshot = ref<GovernanceSnapshot | null>(null)
const runDetail = ref<RunDetail | null>(null)
const selectedRunId = ref('')
const downstream = ref<DownstreamCheck | null>(null)
const errorMessage = ref('')

const pendingAttributionCount = computed(
  () =>
    (snapshot.value?.attributions ?? []).filter(
      (item) => item.status === '归属待核实' || item.status === '留待核对',
    ).length,
)

function attributionTagClass(status: string): string {
  if (status === '归属已核实') return 'tag-ok'
  if (status === '留待核对') return 'tag-reject'
  return 'tag-hold'
}

function verdictTagClass(verdict: string): string {
  if (verdict === '允许写入') return 'tag-ok'
  if (verdict === '权限不足') return 'tag-reject'
  return 'tag-hold'
}

async function selectRun(runId: string) {
  selectedRunId.value = runId
  try {
    runDetail.value = await loadRunDetail(runId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运行详情读取失败'
  }
}

async function onVerify(targetColumn: string) {
  errorMessage.value = ''
  try {
    const result = await verifyAttribution(targetColumn)
    errorMessage.value = result.ok ? '' : result.message
    await reload()
    if (selectedRunId.value) await selectRun(selectedRunId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归属核实失败'
  }
}

async function checkDownstream() {
  errorMessage.value = ''
  try {
    downstream.value = await loadDownstreamCheck()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下游核对失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    snapshot.value = await loadGovernanceSnapshot()
    const defaultRun = selectedRunId.value || snapshot.value.first_run_id
    if (snapshot.value.runs.some((run) => run.run_id === defaultRun)) {
      await selectRun(defaultRun)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '治理数据读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.governance-page {
  display: block;
}
.gov-block {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 16px;
}
.gov-block h3 {
  margin: 0 0 10px;
  font-size: 15px;
}
.gov-block h4 {
  margin: 14px 0 8px;
  font-size: 13px;
  color: var(--muted);
}
.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  white-space: nowrap;
}
.tag-ok {
  background: #e6f7ec;
  color: #157347;
}
.tag-hold {
  background: #fff4e0;
  color: #b26a00;
}
.tag-reject {
  background: #fde8e8;
  color: #b42318;
}
.muted {
  color: var(--muted);
  font-size: 12px;
}
.mapping-line {
  margin: 2px 0;
  font-size: 12px;
}
.run-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.run-meta {
  font-size: 13px;
}
.warning-list,
.reason-list {
  margin: 6px 0;
  padding-left: 18px;
  font-size: 12px;
  color: #b26a00;
}
.downstream-box {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: #fafbfc;
}
.error-text {
  color: #b42318;
}
</style>
