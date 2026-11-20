import { defineStore } from 'pinia'

import client from '@/api/client'

export interface UserInfo {
  id: number
  name: string
  email: string
  role: string
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
    isManager: (state) => state.user?.role === 'manager',
    /** 中文角色名，用于顶栏展示 */
    roleLabel: (state) => {
      const labels: Record<string, string> = {
        recruiter: '招聘专员',
        manager: '用人经理',
        admin: '管理员',
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

    async register(payload: { name: string; email: string; password: string }): Promise<RegisterResult> {
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
