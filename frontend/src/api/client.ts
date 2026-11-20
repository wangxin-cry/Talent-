import axios from 'axios'

/**
 * 统一的 API 客户端
 * - baseURL 走 /api/v1，由 Vite dev server 代理到后端 8000
 * - 预留 token 注入与错误处理（阶段二补齐登录后启用）
 */
const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 阶段二：登录后自动带上 Bearer Token
// client.interceptors.request.use((config) => {
//   const token = localStorage.getItem('access_token')
//   if (token) config.headers.Authorization = `Bearer ${token}`
//   return config
// })

client.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const message =
      error?.response?.data?.error?.message || error?.message || '请求失败'
    console.error('[api]', message)
    return Promise.reject(error)
  },
)

export default client
