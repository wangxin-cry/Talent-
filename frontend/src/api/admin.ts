import client from '@/api/client'

export interface AdminUser {
  id: number
  name: string
  email: string
  role: string
  department: string | null
  phone: string | null
  status: string
  email_verified: boolean
  last_login_at: string | null
  create_time: string
}

export interface SystemConfig {
  key: string
  value: any
  description: string | null
  updated_by: number | null
  update_time: string | null
}

export interface AuditLog {
  id: number
  action: string
  target_type: string
  target_id: number | null
  detail: Record<string, any>
  user_id: number | null
  user_name: string | null
  create_time: string
}

export interface ApiKey {
  id: number
  name: string
  prefix: string
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  create_time: string
  status: string
  user_id?: number
  user_name?: string | null
}

export async function listUsers(params: {
  q?: string
  role?: string
  status?: string
  include_deleted?: boolean
  skip?: number
  limit?: number
}) {
  const { data } = await client.get<AdminUser[]>('/admin/users', { params })
  return data
}

export async function updateUser(
  id: number,
  payload: { role?: string; status?: string; department?: string | null },
) {
  const { data } = await client.patch<AdminUser>(`/admin/users/${id}`, payload)
  return data
}

export async function deleteUser(id: number) {
  await client.delete(`/admin/users/${id}`)
}

export async function listConfigs() {
  const { data } = await client.get<SystemConfig[]>('/admin/system-config')
  return data
}

export async function updateConfig(key: string, value: any, description?: string) {
  const { data } = await client.put<SystemConfig>(
    `/admin/system-config/${encodeURIComponent(key)}`,
    { value, description },
  )
  return data
}

export async function listAudit(params: {
  action?: string
  target_type?: string
  user_id?: number
  skip?: number
  limit?: number
}) {
  const { data } = await client.get<{ items: AuditLog[]; total: number }>('/admin/audit-logs', {
    params,
  })
  return data
}

export async function listMyApiKeys() {
  const { data } = await client.get<{ items: ApiKey[] }>('/api-keys')
  return data.items
}

export async function createMyApiKey(payload: { name: string; expires_in_days?: number | null }) {
  const { data } = await client.post<ApiKey & { key: string }>('/api-keys', payload)
  return data
}

export async function revokeMyApiKey(id: number) {
  await client.delete(`/api-keys/${id}`)
}

export async function listAllApiKeys() {
  const { data } = await client.get<{ items: ApiKey[] }>('/admin/api-keys')
  return data.items
}

export async function revokeAdminApiKey(id: number) {
  await client.delete(`/admin/api-keys/${id}`)
}
