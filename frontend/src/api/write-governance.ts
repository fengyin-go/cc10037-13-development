/** 写入编排治理 API：模板实例 Schema 版本、列归属、写入权限、写入计划与净额血缘。 */
import { fetchJson, request } from './client'

export type SchemaInstance = {
  instance_id: string
  template_name: string
  template_version: string
  input_version: string
  output_version: string
  input_columns: string[]
  output_columns: string[]
  mappings: { target_column: string; expression: string; source_columns: string[] }[]
  active: boolean
  created_at: string
}

export type Attribution = {
  target_table: string
  target_column: string
  owner_instance_id: string
  expression: string
  source_columns: string[]
  status: string
  resolution: string
}

export type Candidate = {
  candidate_id: string
  target_column: string
  instance_id: string
  expression: string
  source_columns: string[]
  verdict: string
  readonly: boolean
  check_reasons: string[]
}

export type PlanItem = {
  target_column: string
  instance_id: string
  template_version: string
  expression: string
  source_columns: string[]
  authorized: boolean
  block_reasons: string[]
}

export type RunDetail = {
  run_id: string
  target_table: string
  plan_status: string
  submitted_at: string
  held_columns: string[]
  warnings: string[]
  candidates: Candidate[]
  plan_items: PlanItem[]
  attributions: Attribution[]
  lineage: {
    target_column: string
    instance_id: string
    expression: string
    source_columns: string[]
    registered_at: string
  }[]
}

export type RunSummary = {
  run_id: string
  target_table: string
  plan_status: string
  held_columns: string[]
  submitted_at: string
  formal_items: {
    column: string
    instance_id: string
    template_version: string
    expression: string
    source_columns: string[]
  }[]
}

export type LineageRow = {
  target_table: string
  target_column: string
  instance_id: string
  expression: string
  source_columns: string[]
  run_id: string
  registered_at: string
}

export type GovernanceSnapshot = {
  instances: SchemaInstance[]
  net_expressions: {
    target_table: string
    target_column: string
    expression: string
    required_source_columns: string[]
    registered: boolean
  }[]
  attributions: Attribution[]
  runs: RunSummary[]
  lineage: LineageRow[]
  first_run_id: string
  second_run_id: string
}

export type DownstreamCheck = {
  target_table: string
  target_column: string
  formal_lineage: {
    instance_id: string
    expression: string
    source_columns: string[]
    run_id: string
  }[]
  downstream: {
    downstream_table: string
    read_field: string
    expected_expression: string
    sample_value: string
  }
  latest_run_status: string
  consistent: boolean
  message: string
}

const BASE = '/api/write-governance'

export function loadGovernanceSnapshot(): Promise<GovernanceSnapshot> {
  return fetchJson<GovernanceSnapshot>(`${BASE}/snapshot`)
}

export function loadRunDetail(runId: string): Promise<RunDetail> {
  return fetchJson<RunDetail>(`${BASE}/runs/${encodeURIComponent(runId)}`)
}

export function loadDownstreamCheck(): Promise<DownstreamCheck> {
  return fetchJson<DownstreamCheck>(`${BASE}/downstream-check`)
}

export async function verifyAttribution(targetColumn: string): Promise<{ ok: boolean; message: string }> {
  const response = await request(`${BASE}/attributions/verify`, {
    method: 'POST',
    body: JSON.stringify({ target_column: targetColumn }),
  })
  return await response.json()
}

export type Declaration = {
  candidate_id: string
  target_table: string
  target_column: string
  instance_id: string
  declared_output_version: string
}

export async function resubmitOrchestration(runId: string, declarations: Declaration[]): Promise<RunDetail> {
  const response = await request(`${BASE}/submit`, {
    method: 'POST',
    body: JSON.stringify({ run_id: runId, declarations }),
  })
  if (!response.ok) throw new Error('编排提交失败')
  return await response.json()
}
