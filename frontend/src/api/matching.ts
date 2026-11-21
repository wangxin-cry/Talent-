import client from '@/api/client'

export interface MatchItem {
  id: number
  job_id: number
  candidate_id: number
  candidate_name: string | null
  resume_id: number | null
  score: number
  skill_score: number | null
  exp_score: number | null
  edu_score: number | null
  other_score: number | null
  matched_skills: string[]
  missing_skills: string[]
  summary: string | null
  feedback: string | null
  create_time: string
}

export interface MatchDetail extends MatchItem {
  detail: {
    scores: Record<string, number>
    features: {
      must_skill_names: string[]
      nice_skill_names: string[]
      matched_must: string[]
      missing_must: string[]
      matched_nice: string[]
      missing_nice: string[]
      jd_min_years: number | null
      candidate_years: number | null
      years_gap: number | null
      jd_edu_level: string | null
      candidate_edu_level: string | null
      location_match: boolean
    }
    explanation: {
      summary: string
      matched_skills: string[]
      missing_skills: string[]
      risks: string[]
      suggestion: string
    }
  }
}

export interface MatchList {
  items: MatchItem[]
  total: number
  job_id: number
  job_title: string
}

export interface MatchTrigger {
  job_id: number
  matched_count: number
  cached_count: number
  computed_count: number
  items: MatchItem[]
}

export async function triggerMatch(jobId: number, useLlm = false): Promise<MatchTrigger> {
  const { data } = await client.post<MatchTrigger>(`/matching/jobs/${jobId}/match`, null, {
    params: { use_llm: useLlm },
  })
  return data
}

export async function listMatches(
  jobId: number,
  params: { min_score?: number; sort?: string } = {},
): Promise<MatchList> {
  const { data } = await client.get<MatchList>(`/matching/jobs/${jobId}/matches`, { params })
  return data
}

export async function getMatch(matchId: number): Promise<MatchDetail> {
  const { data } = await client.get<MatchDetail>(`/matching/matches/${matchId}`)
  return data
}

export async function submitFeedback(matchId: number, feedback: 'fit' | 'unfit'): Promise<MatchDetail> {
  const { data } = await client.post<MatchDetail>(`/matching/matches/${matchId}/feedback`, { feedback })
  return data
}
