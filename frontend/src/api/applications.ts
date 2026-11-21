import client from '@/api/client'

export interface ApplicationCard {
  id: number
  job_id: number
  candidate_id: number
  candidate_name: string | null
  candidate_title: string | null
  candidate_company: string | null
  years_experience: number | null
  status: string
  status_label: string
  match_score: number | null
  days_in_stage: number
  allowed_next: string[]
}

export interface BoardColumn {
  status: string
  label: string
  items: ApplicationCard[]
}

export interface Board {
  job_id: number
  job_title: string
  columns: BoardColumn[]
}

export interface MatchGap {
  score: number | null
  summary: string | null
  matched_must: string[]
  missing_must: string[]
  matched_nice: string[]
  missing_nice: string[]
  years_gap: number | null
  jd_min_years: number | null
  candidate_years: number | null
}

export interface ResumeProject {
  name: string | null
  role: string | null
  tech: string[]
  description: string | null
}

export interface ApplicationDetail extends ApplicationCard {
  job_title: string | null
  job_department: string | null
  candidate_city: string | null
  candidate_education: string | null
  candidate_skills: string[]
  projects: ResumeProject[]
  applied_at: string | null
  stage_entered_at: string | null
  rejected_reason: string | null
  offer_salary: number | null
  hired_at: string | null
  match: MatchGap | null
  create_time: string
  update_time: string
}

export interface TimelineItem {
  id: number
  from_status: string | null
  from_label: string | null
  to_status: string
  to_label: string
  operator_id: number | null
  operator_name: string | null
  note: string | null
  duration_in_prev_status: number | null
  create_time: string
}

export interface Question {
  id: number
  category: string
  question: string
  looking_for: string | null
  reference: string | null
  follow_up: string | null
  sort_order: number
  source: string
}

export interface RagSource {
  type: string
  id: number
  title: string
  score: number
  snippet: string
}

export interface QuestionSet {
  application_id: number
  cached: boolean
  source: string
  total: number
  rag_used: boolean
  rag_sources: RagSource[]
  questions: Question[]
}

export interface NotificationItem {
  id: number
  application_id: number | null
  candidate_id: number | null
  candidate_name: string | null
  channel: string
  template: string
  subject: string | null
  body: string | null
  status: string
  create_time: string
  read_at: string | null
}

export interface NotificationList {
  items: NotificationItem[]
  total: number
  unread: number
}

export async function listBoard(jobId: number): Promise<Board> {
  const { data } = await client.get<Board>('/applications/board', { params: { job_id: jobId } })
  return data
}

export async function getApplication(id: number): Promise<ApplicationDetail> {
  const { data } = await client.get<ApplicationDetail>(`/applications/${id}`)
  return data
}

export async function createApplication(payload: {
  job_id: number
  candidate_id: number
  source?: string
}): Promise<ApplicationDetail> {
  const { data } = await client.post<ApplicationDetail>('/applications', payload)
  return data
}

export async function transition(
  id: number,
  payload: { to_status: string; note?: string; offer_salary?: number },
): Promise<ApplicationDetail> {
  const { data } = await client.post<ApplicationDetail>(`/applications/${id}/transition`, payload)
  return data
}

export async function getTimeline(id: number): Promise<{ items: TimelineItem[] }> {
  const { data } = await client.get<{ items: TimelineItem[] }>(`/applications/${id}/timeline`)
  return data
}

export async function listQuestions(id: number): Promise<QuestionSet> {
  const { data } = await client.get<QuestionSet>(`/applications/${id}/questions`)
  return data
}

export async function generateQuestions(
  id: number,
  useLlm = true,
  useRag: boolean | null = null,
  force = false,
): Promise<QuestionSet> {
  const { data } = await client.post<QuestionSet>(`/applications/${id}/questions`, {
    use_llm: useLlm,
    use_rag: useRag,
    force,
  })
  return data
}

export async function listNotifications(params: {
  unread_only?: boolean
  limit?: number
} = {}): Promise<NotificationList> {
  const { data } = await client.get<NotificationList>('/notifications', { params })
  return data
}

export async function unreadCount(): Promise<number> {
  const { data } = await client.get<{ unread: number }>('/notifications/unread-count')
  return data.unread
}

export async function markRead(id: number): Promise<NotificationItem> {
  const { data } = await client.post<NotificationItem>(`/notifications/${id}/read`)
  return data
}
