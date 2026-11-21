import client from '@/api/client'

export interface RagHealth {
  enabled: boolean
  index_enabled: boolean
  backend: string
  embedding_configured: boolean
  embedding_provider: string
  embedding_model: string
  dim: number
  collections: Record<string, number>
}

export interface ResumeHit {
  candidate_id: number
  name: string
  current_title: string
  current_company: string
  years_experience: number | null
  city: string | null
  skills: string[]
  score: number
  snippets: string[]
}

export interface ResumeSearchResult {
  query: string
  total: number
  available: boolean
  items: ResumeHit[]
}

export async function getRagHealth(): Promise<RagHealth> {
  const { data } = await client.get<RagHealth>('/rag/health')
  return data
}

export async function searchResumes(payload: {
  query: string
  top_k?: number
  job_id?: number
  exclude_candidate_id?: number
  min_score?: number
}): Promise<ResumeSearchResult> {
  const { data } = await client.post<ResumeSearchResult>('/rag/search/resumes', payload)
  return data
}

export async function reindexRag(params: {
  scope?: 'all' | 'resumes' | 'jobs' | 'questions'
  rebuild?: boolean
}): Promise<{ scope: string; rebuilt: boolean; counts: Record<string, number> }> {
  const { data } = await client.post('/rag/reindex', null, { params })
  return data
}
