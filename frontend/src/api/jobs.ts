import client from '@/api/client'

export interface SkillBrief {
  id: number
  name: string
  display_name?: string | null
}

export interface Skill extends SkillBrief {
  aliases: string[]
  category?: string | null
  is_active: boolean
}

export interface Job {
  id: number
  title: string
  department?: string | null
  location?: string | null
  work_mode?: string | null
  employment_type: string
  headcount: number
  description?: string | null
  requirements?: string | null
  skills: SkillBrief[]
  must_have_skills: SkillBrief[]
  min_years?: number | null
  education_level?: string | null
  salary_min?: number | null
  salary_max?: number | null
  status: string
  jd_source: string
  jd_version: number
  published_at?: string | null
  closed_at?: string | null
  approved_by?: number | null
  approved_at?: string | null
  reject_reason?: string | null
  apply_count: number
  created_by?: number | null
  create_time: string
  update_time: string
}

export interface JobList {
  items: Job[]
  total: number
}

export interface JobPayload {
  title: string
  department?: string | null
  location?: string | null
  work_mode?: string | null
  employment_type?: string
  headcount?: number
  description?: string | null
  requirements?: string | null
  skills?: number[]
  must_have_skills?: number[]
  min_years?: number | null
  education_level?: string | null
  salary_min?: number | null
  salary_max?: number | null
  jd_source?: string
}

export interface JDGenerated {
  summary: string
  description: string
  requirements: string
  skills: SkillBrief[]
  must_have_skills: SkillBrief[]
  ai_generated: boolean
  note?: string | null
}

export async function listJobs(params: {
  status?: string
  q?: string
  page?: number
  page_size?: number
}): Promise<JobList> {
  const { data } = await client.get<JobList>('/jobs', { params })
  return data
}

export async function getJob(id: number): Promise<Job> {
  const { data } = await client.get<Job>(`/jobs/${id}`)
  return data
}

export async function createJob(payload: JobPayload): Promise<Job> {
  const { data } = await client.post<Job>('/jobs', payload)
  return data
}

export async function updateJob(id: number, payload: Partial<JobPayload>): Promise<Job> {
  const { data } = await client.put<Job>(`/jobs/${id}`, payload)
  return data
}

export async function publishJob(id: number): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/publish`)
  return data
}

export async function submitJob(id: number): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/submit`)
  return data
}

export async function approveJob(id: number): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/approve`)
  return data
}

export async function rejectJob(id: number, reason: string): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/reject`, { reason })
  return data
}

export async function closeJob(id: number): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/close`)
  return data
}

export async function archiveJob(id: number): Promise<Job> {
  const { data } = await client.post<Job>(`/jobs/${id}/archive`)
  return data
}

export async function generateJd(payload: {
  title: string
  department?: string | null
  location?: string | null
  keywords: string[]
  level?: string | null
}): Promise<JDGenerated> {
  const { data } = await client.post<JDGenerated>('/jobs/generate-jd', payload)
  return data
}

export async function searchSkills(q = '', limit = 100): Promise<Skill[]> {
  const { data } = await client.get<Skill[]>('/skills', { params: { q, limit } })
  return data
}

export async function createSkill(payload: {
  name: string
  aliases?: string[]
  category?: string | null
}): Promise<Skill> {
  const { data } = await client.post<Skill>('/skills', payload)
  return data
}
