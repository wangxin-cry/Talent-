import client from '@/api/client'

export interface ResumeFileBrief {
  id: number
  original_name: string
  ext?: string | null
  mime?: string | null
  size_bytes: number
  sha256: string
  status: string
  parser?: string | null
  error_reason?: string | null
  retry_count: number
  parsed_time?: string | null
  create_time: string
}

export interface Candidate {
  id: number
  name?: string | null
  phone?: string | null
  email?: string | null
  city?: string | null
  education_level?: string | null
  school?: string | null
  major?: string | null
  years_experience?: number | null
  current_company?: string | null
  current_title?: string | null
  skills: string[]
  file_count: number
  latest_status?: string | null
  create_time: string
  update_time: string
}

export interface EducationItem {
  school?: string | null
  major?: string | null
  degree?: string | null
  start?: string | null
  end?: string | null
}

export interface WorkItem {
  company?: string | null
  title?: string | null
  employment_type?: string | null
  start?: string | null
  end?: string | null
  description?: string | null
}

export interface ProjectItem {
  name?: string | null
  role?: string | null
  stack: string[]
  start?: string | null
  end?: string | null
  description?: string | null
}

export interface StructuredResume {
  basic: Record<string, any>
  education: EducationItem[]
  work: WorkItem[]
  projects: ProjectItem[]
  skills: string[]
  certificates: string[]
}

export interface CandidateDetail extends Candidate {
  files: ResumeFileBrief[]
  resume_id?: number | null
  structured?: StructuredResume | null
  field_confidence: Record<string, number>
  plain_text?: string | null
  parser_meta: Record<string, any>
}

export interface CandidateList {
  items: Candidate[]
  total: number
}

export interface CandidatePayload {
  name?: string | null
  phone?: string | null
  email?: string | null
  city?: string | null
  education_level?: string | null
  school?: string | null
  major?: string | null
  years_experience?: number | null
  current_company?: string | null
  current_title?: string | null
  skills?: string[]
}

export interface UploadItem {
  file_id?: number | null
  original_name: string
  size_bytes: number
  sha256?: string | null
  reused: boolean
  status: string
  candidate_id?: number | null
  message?: string | null
}

export interface FileStatus {
  id: number
  status: string
  error_reason?: string | null
  candidate_id?: number | null
}

export async function listCandidates(params: {
  q?: string
  page?: number
  page_size?: number
}): Promise<CandidateList> {
  const { data } = await client.get<CandidateList>('/candidates', { params })
  return data
}

export async function getCandidate(id: number): Promise<CandidateDetail> {
  const { data } = await client.get<CandidateDetail>(`/candidates/${id}`)
  return data
}

export async function createCandidate(payload: CandidatePayload): Promise<CandidateDetail> {
  const { data } = await client.post<CandidateDetail>('/candidates', payload)
  return data
}

export async function updateCandidate(
  id: number,
  payload: CandidatePayload,
): Promise<CandidateDetail> {
  const { data } = await client.put<CandidateDetail>(`/candidates/${id}`, payload)
  return data
}

export async function uploadResumes(
  files: File[],
  appliedJobId?: number,
): Promise<{ items: UploadItem[] }> {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  if (appliedJobId != null) form.append('applied_job_id', String(appliedJobId))
  const { data } = await client.post<{ items: UploadItem[] }>('/candidates/upload', form)
  return data
}

export async function getFileStatuses(ids: number[]): Promise<{ items: FileStatus[] }> {
  const { data } = await client.get<{ items: FileStatus[] }>('/resume-files/status', {
    params: { ids: ids.join(',') },
  })
  return data
}

export async function downloadResumeFile(id: number): Promise<{
  url: string
  expires_in: number
  filename: string
}> {
  const { data } = await client.get(`/resume-files/${id}/download`)
  return data
}

export async function reparseResumeFile(id: number): Promise<UploadItem> {
  const { data } = await client.post<UploadItem>(`/resume-files/${id}/reparse`)
  return data
}
