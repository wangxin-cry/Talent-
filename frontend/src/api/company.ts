import client from '@/api/client'

export interface CompanyLookup {
  name: string
  slug: string
}

export interface CompanyCurrent {
  id: number
  name: string
  slug: string
  status: string
  invite_code: string | null
  member_count: number
}

export interface CompanyMember {
  id: number
  name: string
  email: string
  role: string
  status: string
  create_time: string
}

export interface PlatformCompany {
  id: number
  name: string
  slug: string
  status: string
  invite_code: string
  member_count: number
  create_time: string
}

export async function lookupCompany(inviteCode: string): Promise<CompanyLookup> {
  const { data } = await client.get<CompanyLookup>('/company/lookup', {
    params: { invite_code: inviteCode },
  })
  return data
}

export async function currentCompany(): Promise<CompanyCurrent> {
  const { data } = await client.get<CompanyCurrent>('/company/current')
  return data
}

export async function resetInviteCode(): Promise<CompanyCurrent> {
  const { data } = await client.post<CompanyCurrent>('/company/invite/reset')
  return data
}

export async function listMembers(): Promise<CompanyMember[]> {
  const { data } = await client.get<CompanyMember[]>('/company/members')
  return data
}

export async function updateMember(
  memberId: number,
  payload: { role?: string; status?: string },
): Promise<CompanyMember> {
  const { data } = await client.patch<CompanyMember>(`/company/members/${memberId}`, payload)
  return data
}

export async function listPlatformCompanies(): Promise<PlatformCompany[]> {
  const { data } = await client.get<PlatformCompany[]>('/platform/companies')
  return data
}

export async function createPlatformCompany(name: string): Promise<PlatformCompany> {
  const { data } = await client.post<PlatformCompany>('/platform/companies', { name })
  return data
}

export async function updatePlatformCompany(
  id: number,
  status: 'active' | 'disabled',
): Promise<PlatformCompany> {
  const { data } = await client.patch<PlatformCompany>(`/platform/companies/${id}`, { status })
  return data
}
