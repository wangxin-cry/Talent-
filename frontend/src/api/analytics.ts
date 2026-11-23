import client from '@/api/client'

export interface Overview {
  open_jobs: number
  total_applications: number
  pending_interview: number
  hired: number
  rejected: number
  avg_cycle_days: number | null
  status_counts: Record<string, number>
}

export interface FunnelStage {
  status: string
  label: string
  count: number
  share: number
  conversion: number | null
}

export interface Channel {
  source: string
  total: number
  interview: number
  hired: number
  rejected: number
  conversion: number
}

export interface CycleStage {
  stage: string
  label: string
  samples: number
  avg_hours: number | null
}

export interface Dashboard {
  overview: Overview
  funnel: FunnelStage[]
  channels: Channel[]
  cycle: CycleStage[]
  generated_at: string
}

export interface AiCallItem {
  id: number
  feature: string
  agent: string | null
  provider: string | null
  model: string | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost: number
  currency: string
  duration_ms: number | null
  cache_hit: boolean
  status: string
  error_reason: string | null
  job_id: number | null
  candidate_id: number | null
  user_id: number | null
  job_title: string | null
  create_time: string
}

export interface AiCallList {
  items: AiCallItem[]
  total: number
  page: number
  page_size: number
}

export interface FeatureCost {
  feature: string
  calls: number
  tokens: number
  cost: number
}

export interface JobCost {
  job_id: number
  job_title: string
  calls: number
  tokens: number
  cost: number
}

export interface CostSummary {
  total_calls: number
  total_tokens: number
  total_cost: number
  today_cost: number
  month_cost: number
  budget: number
  budget_ratio: number
  budget_status: 'ok' | 'warning' | 'exceeded' | 'disabled'
  by_feature: FeatureCost[]
  top_jobs: JobCost[]
}

export interface SlaItem {
  application_id: number
  job_id: number
  job_title: string | null
  candidate_id: number
  candidate_name: string | null
  status: string
  status_label: string
  hours_in_stage: number
  limit_hours: number
  overdue_hours: number
}

export interface SlaResult {
  thresholds: Record<string, number>
  total: number
  items: SlaItem[]
  generated_at: string
}

export async function getDashboard(): Promise<Dashboard> {
  const { data } = await client.get<Dashboard>('/analytics/dashboard')
  return data
}

export async function getSla(): Promise<SlaResult> {
  const { data } = await client.get<SlaResult>('/analytics/sla')
  return data
}

export async function downloadReport(): Promise<Blob> {
  const { data } = await client.get('/analytics/export', { responseType: 'blob' })
  return data
}

export async function getCostSummary(): Promise<CostSummary> {
  const { data } = await client.get<CostSummary>('/costs/summary')
  return data
}

export async function listCalls(params: {
  page?: number
  page_size?: number
  feature?: string
  job_id?: number
  status?: string
}): Promise<AiCallList> {
  const { data } = await client.get<AiCallList>('/costs', { params })
  return data
}
