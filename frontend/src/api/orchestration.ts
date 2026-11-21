import client from '@/api/client'

export interface OrchestrationStep {
  step_no: number
  agent: string
  parent_step: number | null
  status: string
  degraded: boolean
  duration_ms: number
  tokens_in: number
  tokens_out: number
  cost: number
  input_summary: Record<string, any>
  output_summary: Record<string, any>
  error_reason: string | null
}

export interface OrchestrationRun {
  trace_id: string
  intent: string
  intent_label: string
  status: string
  degraded: boolean
  duration_ms: number
  total_tokens: number
  total_cost: number
  plan: string[]
  steps: OrchestrationStep[]
  result: Record<string, any>
}

export interface TraceSummary {
  trace_id: string
  intent: string | null
  status: string
  degraded: boolean
  duration_ms: number
  total_cost: number
  step_count: number
  create_time: string
}

export interface TraceDetail {
  trace_id: string
  intent: string | null
  status: string
  degraded: boolean
  duration_ms: number
  total_tokens: number
  total_cost: number
  steps: OrchestrationStep[]
  create_time: string | null
}

export interface IntentItem {
  intent: string
  label: string
  agents: string[]
  description: string
}

export interface OrchestrationPayload {
  intent: string
  job_id?: number | null
  application_id?: number | null
  candidate_id?: number | null
  file_ids?: number[]
  to_status?: string | null
  note?: string | null
  offer_salary?: number | null
  top_n?: number
  limit?: number | null
  use_llm?: boolean
  step_timeout?: number | null
  title?: string | null
  department?: string | null
  location?: string | null
  keywords?: string[]
}

export async function runOrchestration(payload: OrchestrationPayload): Promise<OrchestrationRun> {
  const { data } = await client.post<OrchestrationRun>('/orchestration/run', payload)
  return data
}

export async function listIntents(): Promise<IntentItem[]> {
  const { data } = await client.get<{ items: IntentItem[] }>('/orchestration/intents')
  return data.items
}

export async function listTraces(limit = 20): Promise<TraceSummary[]> {
  const { data } = await client.get<{ items: TraceSummary[] }>('/orchestration/traces', {
    params: { limit },
  })
  return data.items
}

export async function getTrace(traceId: string): Promise<TraceDetail> {
  const { data } = await client.get<TraceDetail>(`/orchestration/traces/${traceId}`)
  return data
}
