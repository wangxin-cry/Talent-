import client from '@/api/client'

export interface InterviewSchedule {
  id: number
  application_id: number
  scheduled_at: string
  duration_minutes: number
  mode: 'online' | 'onsite' | 'phone'
  location: string | null
  interviewer: string | null
  note: string | null
  created_by: number | null
  create_time: string
  update_time: string
}

export interface EvaluationDimension {
  key: string
  name: string
  description: string
}

export interface EvaluationTemplate {
  title: string
  scale: number
  dimensions: EvaluationDimension[]
  recommendations: { value: string; label: string }[]
}

export interface InterviewFeedback {
  id: number
  application_id: number
  interviewer_id: number | null
  interviewer_name: string | null
  round: number
  scores: Record<string, number>
  overall_rating: number | null
  recommendation: string | null
  recommendation_label: string | null
  comment: string | null
  create_time: string
}

export interface FeedbackSummary {
  total: number
  average_rating: number | null
  recommendation: string | null
  recommendation_label: string | null
  items: InterviewFeedback[]
}

export async function getSchedule(applicationId: number): Promise<InterviewSchedule | null> {
  const { data } = await client.get<InterviewSchedule | null>(
    `/applications/${applicationId}/interview-schedule`,
  )
  return data
}

export async function saveSchedule(
  applicationId: number,
  payload: {
    scheduled_at: string
    duration_minutes: number
    mode: string
    location?: string | null
    interviewer?: string | null
    note?: string | null
  },
): Promise<InterviewSchedule> {
  const { data } = await client.put<InterviewSchedule>(
    `/applications/${applicationId}/interview-schedule`,
    payload,
  )
  return data
}

export async function downloadIcs(applicationId: number): Promise<Blob> {
  const { data } = await client.get(`/applications/${applicationId}/interview.ics`, {
    responseType: 'blob',
  })
  return data
}

export async function getEvaluationTemplate(): Promise<EvaluationTemplate> {
  const { data } = await client.get<EvaluationTemplate>('/interviews/evaluation-template')
  return data
}

export async function listFeedbacks(applicationId: number): Promise<FeedbackSummary> {
  const { data } = await client.get<FeedbackSummary>(`/applications/${applicationId}/feedbacks`)
  return data
}

export async function createFeedback(
  applicationId: number,
  payload: {
    round: number
    scores: Record<string, number>
    recommendation?: string | null
    comment?: string | null
    overall_rating?: number | null
  },
): Promise<InterviewFeedback> {
  const { data } = await client.post<InterviewFeedback>(
    `/applications/${applicationId}/feedbacks`,
    payload,
  )
  return data
}
