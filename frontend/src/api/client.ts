import axios, { type InternalAxiosRequestConfig } from 'axios'

/**
 * 统一的 API 客户端
 * - baseURL 走 /api/v1，由 Vite dev server 代理到后端 8000
 * - 请求自动带 Bearer Token
 * - 401 时用 refresh token 静默续期一次，失败则清空会话并跳登录
 */
const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean }

let refreshing: Promise<string | null> | null = null

function clearSession() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return null
  try {
    const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
    localStorage.setItem('access_token', data.access_token)
    return data.access_token as string
  } catch {
    clearSession()
    return null
  }
}

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const config = error.config as RetriableConfig | undefined
    const status = error?.response?.status
    const url: string = config?.url ?? ''
    const isAuthUrl = url.startsWith('/auth/')

    if (status === 401 && config && !config._retry && !isAuthUrl) {
      config._retry = true
      refreshing = refreshing ?? refreshAccessToken()
      const token = await refreshing
      refreshing = null
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
        return client(config)
      }
    }

    if (status === 401 && !isAuthUrl) {
      clearSession()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }

    const message =
      error?.response?.data?.error?.message || error?.message || '请求失败'
    error.message = message
    console.error('[api]', message)
    return Promise.reject(error)
  },
)

export default client
