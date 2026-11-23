import { defineStore } from 'pinia'

import client from '@/api/client'

export interface UserInfo {
  id: number
  name: string
  nickname: string | null
  email: string
  role: string
  department: string | null
  phone: string | null
  avatar_url: string | null
  bio: string | null
  status: string
  email_verified: boolean
  last_login_at: string | null
  create_time: string
}

interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

export interface RegisterResult {
  user: UserInfo
  email_sent: boolean
  message: string
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as UserInfo | null,
    accessToken: localStorage.getItem('access_token') ?? '',
  }),

  getters: {
    isLoggedIn: (state) => Boolean(state.accessToken),
    isAdmin: (state) => state.user?.role === 'admin',
    isSuperAdmin: (state) => state.user?.role === 'superadmin',
    isManager: (state) => state.user?.role === 'manager',
    isRecruiter: (state) => state.user?.role === 'recruiter',
    /** 顶栏展示名：优先昵称，其次登录名 */
    displayName: (state) => state.user?.nickname || state.user?.name || '',
    /** 中文角色名，用于顶栏展示 */
    roleLabel: (state) => {
      const labels: Record<string, string> = {
        recruiter: '招聘专员',
        manager: '用人经理',
        admin: '公司管理员',
        superadmin: '平台超管',
      }
      return state.user ? labels[state.user.role] ?? state.user.role : ''
    },
  },

  actions: {
    async login(account: string, password: string) {
      const { data } = await client.post<LoginResult>('/auth/login', { account, password })
      this.accessToken = data.access_token
      this.user = data.user
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
    },

    async register(payload: {
      name: string
      email: string
      password: string
      mode: 'create' | 'join'
      company_name?: string
      invite_code?: string
      role?: 'recruiter' | 'manager'
    }): Promise<RegisterResult> {
      const { data } = await client.post<RegisterResult>('/auth/register', payload)
      return data
    },

    async fetchMe() {
      if (!this.accessToken) return
      try {
        const { data } = await client.get<UserInfo>('/auth/me')
        this.user = data
      } catch {
        // 401 由 client 拦截器统一处理
      }
    },

    async updateProfile(payload: {
      nickname?: string | null
      phone?: string | null
      bio?: string | null
    }) {
      const { data } = await client.patch<UserInfo>('/auth/me', payload)
      this.user = data
      return data
    },

    /** 上传头像：后端校验格式/大小并统一裁成 256×256 */
    async uploadAvatar(file: File) {
      const form = new FormData()
      form.append('file', file)
      const { data } = await client.post<UserInfo>('/auth/me/avatar', form)
      this.user = data
      return data
    },

    async removeAvatar() {
      const { data } = await client.delete<UserInfo>('/auth/me/avatar')
      this.user = data
      return data
    },

    /** 注销账号：清理本人创建的数据并软删除账号（仅专员/经理） */
    async cancelAccount(password: string) {
      const { data } = await client.delete<{
        message: string
        deleted_jobs: number
        deleted_candidates: number
        deleted_applications: number
        deleted_files: number
      }>('/auth/me', { data: { password } })
      return data
    },

    async logout() {
      // 先通知后端作废令牌（失败也不影响本地登出）
      if (this.accessToken) {
        try {
          await client.post('/auth/logout')
        } catch {
          // 令牌已失效等情况，忽略
        }
      }
      this.user = null
      this.accessToken = ''
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    },
  },
})
