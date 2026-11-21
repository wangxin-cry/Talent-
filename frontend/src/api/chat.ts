import client from '@/api/client'

export interface ChatSession {
  id: number
  title: string | null
  context_job_id: number | null
  context_candidate_id: number | null
  last_message_at: string | null
  create_time: string
  update_time: string
  message_count: number
  last_message: string | null
}

export interface ChatMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant' | 'system'
  content: string | null
  card_type: string | null
  card_data: Record<string, any>
  intent: string | null
  trace_id: string | null
  tokens: number
  cost: number
  create_time: string
}

export interface ChatSessionDetail {
  session: ChatSession
  messages: ChatMessage[]
}

export interface ChatReply {
  session: ChatSession
  user_message: ChatMessage
  replies: ChatMessage[]
  intent: string | null
  intent_label: string | null
  confidence: number
  needs_clarification: boolean
  trace_id: string | null
  degraded: boolean
  duration_ms: number
  total_cost: number
}

export interface ChatConfirmResult {
  message: ChatMessage
  trace_id: string | null
  degraded: boolean
}

export interface ChatTool {
  name: string
  label: string
  description: string
  level: string
  parameters: Record<string, any>
}

export async function listChatSessions(): Promise<ChatSession[]> {
  const { data } = await client.get<{ items: ChatSession[] }>('/chat/sessions')
  return data.items
}

export async function createChatSession(payload: {
  title?: string | null
  context_job_id?: number | null
  context_candidate_id?: number | null
} = {}): Promise<ChatSession> {
  const { data } = await client.post<ChatSession>('/chat/sessions', payload)
  return data
}

export async function getChatSession(id: number): Promise<ChatSessionDetail> {
  const { data } = await client.get<ChatSessionDetail>(`/chat/sessions/${id}`)
  return data
}

export async function updateChatSession(
  id: number,
  payload: {
    title?: string | null
    context_job_id?: number | null
    context_candidate_id?: number | null
  },
): Promise<ChatSession> {
  const { data } = await client.patch<ChatSession>(`/chat/sessions/${id}`, payload)
  return data
}

export async function sendChatMessage(
  sessionId: number,
  payload: {
    text: string
    file_ids?: number[]
    context_job_id?: number | null
    context_candidate_id?: number | null
    use_llm?: boolean
  },
): Promise<ChatReply> {
  const { data } = await client.post<ChatReply>(
    `/chat/sessions/${sessionId}/messages`,
    payload,
  )
  return data
}

export async function confirmChatAction(
  sessionId: number,
  payload: { message_id: number; note?: string | null; offer_salary?: number | null },
): Promise<ChatConfirmResult> {
  const { data } = await client.post<ChatConfirmResult>(
    `/chat/sessions/${sessionId}/confirm`,
    payload,
  )
  return data
}

export async function listChatTools(): Promise<ChatTool[]> {
  const { data } = await client.get<{ items: ChatTool[] }>('/chat/tools')
  return data.items
}

// ---------------------------------------------------------------- SSE
export interface ChatStreamEvent {
  id?: number
  type: string
  stage?: string
  text?: string
  intent?: string | null
  label?: string | null
  needs_clarification?: boolean
  message?: string
  [key: string]: any
}

export function supportsChatStreaming(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.fetch === 'function' &&
    typeof ReadableStream !== 'undefined'
  )
}

export async function startChatStream(
  sessionId: number,
  payload: {
    text: string
    file_ids?: number[]
    context_job_id?: number | null
    context_candidate_id?: number | null
    use_llm?: boolean
  },
): Promise<{ task_id: string; session_id: number }> {
  const { data } = await client.post<{ task_id: string; session_id: number }>(
    `/chat/sessions/${sessionId}/messages/stream`,
    payload,
  )
  return data
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function readEventStream(
  sessionId: number,
  taskId: string,
  after: number,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<ChatReply | null> {
  const token = localStorage.getItem('access_token')
  const response = await fetch(
    `/api/v1/chat/sessions/${sessionId}/tasks/${taskId}/events?after=${after}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal,
    },
  )
  if (!response.ok || !response.body) {
    throw new Error(`流式连接失败（${response.status}）`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')

        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('\n')
        if (!data) continue

        let event: ChatStreamEvent
        try {
          event = JSON.parse(data)
        } catch {
          continue
        }
        onEvent(event)
        if (event.type === 'done') return event as unknown as ChatReply
        if (event.type === 'error') {
          throw new Error(event.message || '执行失败')
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
  return null
}

/**
 * 订阅任务事件；断线时用 Last-Event-ID 重连一次，避免重复执行。
 */
export async function streamChatEvents(
  sessionId: number,
  taskId: string,
  onEvent: (event: ChatStreamEvent) => void,
  after = 0,
  signal?: AbortSignal,
): Promise<ChatReply | null> {
  let lastId = after
  let lastError: unknown = null
  const handle = (event: ChatStreamEvent) => {
    if (typeof event.id === 'number') lastId = event.id
    onEvent(event)
  }

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const result = await readEventStream(sessionId, taskId, lastId, handle, signal)
      if (result) return result
      if (attempt === 1) return null
    } catch (error) {
      lastError = error
      if (signal?.aborted) throw error
      if (attempt === 1) break
    }
    await sleep(400)
  }
  throw lastError ?? new Error('流式连接中断')
}

