import axios from 'axios'

/** 公开招聘页接口：无需登录，单独用 axios 实例避免带 token / 触发 401 跳转 */
const publicClient = axios.create({ baseURL: '/api/v1', timeout: 30000 })

export interface PublicJob {
  id: number
  title: string
  department: string | null
  location: string | null
  work_mode: string | null
  employment_type: string
  headcount: number
  education_level: string | null
  min_years: number | null
  salary_min: number | null
  salary_max: number | null
  description: string | null
  requirements: string | null
  published_at: string | null
}

export interface ProgressStep {
  status: string
  label: string
  reached: boolean
  current: boolean
  time: string | null
}

export interface Progress {
  job_title: string
  candidate_name: string | null
  status: string
  status_label: string
  applied_at: string | null
  steps: ProgressStep[]
  interview_at: string | null
  message: string | null
}

export async function listJobs(
  params: { slug: string; keyword?: string; page?: number; page_size?: number },
) {
  const { data } = await publicClient.get<{ total: number; items: PublicJob[] }>('/public/jobs', {
    params,
  })
  return data
}

export async function getJob(slug: string, id: number): Promise<PublicJob> {
  const { data } = await publicClient.get<PublicJob>(`/public/jobs/${id}`, {
    params: { slug },
  })
  return data
}

export async function applyJob(payload: {
  companySlug: string
  jobId: number
  name: string
  email: string
  phone?: string
  note?: string
  resume?: File | null
}) {
  const form = new FormData()
  form.append('company_slug', payload.companySlug)
  form.append('job_id', String(payload.jobId))
  form.append('name', payload.name)
  form.append('email', payload.email)
  if (payload.phone) form.append('phone', payload.phone)
  if (payload.note) form.append('note', payload.note)
  if (payload.resume) form.append('resume', payload.resume)

  const { data } = await publicClient.post<{
    application_id: number
    tracking_token: string
    job_title: string
    message: string
  }>('/public/applications', form)
  return data
}

export async function getProgress(token: string, email: string): Promise<Progress> {
  const { data } = await publicClient.get<Progress>('/public/applications/status', {
    params: { token, email },
  })
  return data
}
