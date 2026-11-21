<script setup lang="ts">
/**
 * 工作台（对话式入口）
 *
 * 三栏：会话列表 / 对话流 + 六类卡片 / 业务上下文
 * 对话流已接后端 Chat Gateway（/api/v1/chat）：
 *   意图识别 → 缺参追问 → 安全闸（确认卡）→ Supervisor 编排 → 结构化卡片
 * 右栏上下文切换会写回会话，后续「匹配一下」无需重复说明职位。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import client from '@/api/client'
import { listJobs } from '@/api/jobs'
import type { Job } from '@/api/jobs'
import { uploadResumes } from '@/api/candidates'
import {
  confirmChatAction,
  createChatSession,
  getChatSession,
  listChatSessions,
  sendChatMessage,
  startChatStream,
  streamChatEvents,
  supportsChatStreaming,
  updateChatSession,
} from '@/api/chat'
import type { ChatMessage, ChatReply, ChatSession } from '@/api/chat'

// ---------------------------------------------------------------- 类型
interface Chip {
  label: string
  text: string
  href?: string
}

interface Msg {
  id: number
  role: 'user' | 'assistant'
  text?: string
  cardType?: string | null
  cardData: Record<string, any>
  chips: Chip[]
  errorText?: string
}

// ---------------------------------------------------------------- 状态
const sessions = ref<ChatSession[]>([])
const activeId = ref<number | null>(null)
const messages = ref<Msg[]>([])
const input = ref('')
const sending = ref(false)
const uploading = ref(false)
const bootError = ref('')

const jobs = ref<Job[]>([])
const contextJobId = ref<number | null>(null)
const todayStats = ref({ jobs: 0, published: 0 })
const healthOk = ref<boolean | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const confirmNotes = ref<Record<string, string>>({})
const streamEl = ref<HTMLElement | null>(null)

const activeSession = computed(
  () => sessions.value.find((item) => item.id === activeId.value) ?? null,
)
const currentJob = computed(
  () => jobs.value.find((item) => item.id === contextJobId.value) ?? null,
)
const jobSkills = computed(() => currentJob.value?.skills?.map((s) => s.name) ?? [])
const switchableJobs = computed(() =>
  jobs.value.filter((job) => job.status !== 'archived'),
)
const lastBatch = computed(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    if (message.cardType === 'parse_result') return message.cardData
  }
  return null
})
const batchPercent = computed(() => {
  const batch = lastBatch.value
  if (!batch) return 0
  const total = Number(batch.success || 0) + Number(batch.failed || 0)
  return total ? Math.round((Number(batch.success || 0) / total) * 100) : 0
})

function scrollBottom() {
  nextTick(() => {
    if (streamEl.value) streamEl.value.scrollTop = streamEl.value.scrollHeight
  })
}

// ---------------------------------------------------------------- 数据加载
async function loadJobs() {
  try {
    const [all, published] = await Promise.all([
      listJobs({ page: 1, page_size: 100 }),
      listJobs({ status: 'published', page: 1, page_size: 1 }),
    ])
    jobs.value = all.items
    todayStats.value = { jobs: all.total, published: published.total }
  } catch {
    jobs.value = []
  }
  try {
    const { data } = await client.get('/healthz')
    healthOk.value = data?.status === 'ok'
  } catch {
    healthOk.value = false
  }
}

function defaultJobId(): number | null {
  const published = jobs.value.find((job) => job.status === 'published')
  if (published) return published.id
  return jobs.value.find((job) => job.status !== 'archived')?.id ?? null
}

function toMsg(message: ChatMessage): Msg {
  const data = message.card_data || {}
  const rawChips: Chip[] = data.chips?.length
    ? data.chips
    : (data.options || []).map((option: any) => ({
        label: option.label,
        text: option.text,
      }))
  return {
    id: message.id,
    role: message.role === 'user' ? 'user' : 'assistant',
    text: message.content || undefined,
    cardType: message.card_type,
    cardData: data,
    chips: rawChips || [],
  }
}

function upsertSession(session: ChatSession) {
  const index = sessions.value.findIndex((item) => item.id === session.id)
  if (index >= 0) sessions.value.splice(index, 1, session)
  else sessions.value.unshift(session)
  sessions.value.sort((a, b) => {
    const left = a.last_message_at || a.create_time
    const right = b.last_message_at || b.create_time
    return right.localeCompare(left)
  })
}

async function openSession(id: number) {
  activeId.value = id
  try {
    const detail = await getChatSession(id)
    messages.value = detail.messages.map(toMsg)
    contextJobId.value = detail.session.context_job_id ?? defaultJobId()
    upsertSession(detail.session)
    scrollBottom()
  } catch (error: any) {
    bootError.value = error?.message || '加载会话失败'
  }
}

async function newSession() {
  try {
    const created = await createChatSession({
      title: null,
      context_job_id: contextJobId.value ?? defaultJobId(),
    })
    upsertSession(created)
    activeId.value = created.id
    messages.value = []
    contextJobId.value = created.context_job_id ?? defaultJobId()
  } catch (error: any) {
    bootError.value = error?.message || '新建会话失败'
  }
}

async function loadSessions() {
  try {
    sessions.value = await listChatSessions()
  } catch (error: any) {
    bootError.value = error?.message || '加载会话失败'
    return
  }
  if (sessions.value.length) await openSession(sessions.value[0].id)
  else await newSession()
}

async function switchJob() {
  if (!activeId.value || contextJobId.value == null) return
  try {
    const updated = await updateChatSession(activeId.value, {
      context_job_id: contextJobId.value,
    })
    upsertSession(updated)
  } catch {
    // 上下文切换失败不阻塞对话，下一次发消息会再次带上
  }
}

// ---------------------------------------------------------------- 对话
function pushTempUser(text: string): number {
  const id = -Date.now()
  messages.value.push({ id, role: 'user', text, cardData: {}, chips: [] })
  scrollBottom()
  return id
}

async function sendText(raw: string, fileIds: number[] = []) {
  const text = raw.trim()
  if (!text || sending.value || !activeId.value) return

  const sessionId = activeId.value
  sending.value = true
  input.value = ''
  const tempId = pushTempUser(text)
  const statusId = -Date.now() - 1000
  messages.value.push({
    id: statusId,
    role: 'assistant',
    text: '正在理解你的需求…',
    cardData: {},
    chips: [],
  })
  scrollBottom()

  const setStatus = (value: string) => {
    const message = messages.value.find((item) => item.id === statusId)
    if (message) message.text = value
  }
  const removeMessage = (id: number) => {
    const index = messages.value.findIndex((item) => item.id === id)
    if (index >= 0) messages.value.splice(index, 1)
  }

  const request = {
    text,
    file_ids: fileIds,
    context_job_id: contextJobId.value ?? undefined,
  }

  let reply: ChatReply | null = null
  let streamInterrupted = false

  // 优先 SSE：POST 只发起任务，GET 订阅进度与最终结果
  if (supportsChatStreaming()) {
    let taskId: string | null = null
    try {
      const started = await startChatStream(sessionId, request)
      taskId = started.task_id
    } catch {
      taskId = null
    }

    if (taskId) {
      try {
        reply = await streamChatEvents(sessionId, taskId, (event) => {
          if (event.type === 'status' && event.text) {
            setStatus(event.text)
          } else if (event.type === 'intent') {
            const label = event.label || '当前需求'
            setStatus(
              event.needs_clarification
                ? `识别为「${label}」，需要补充信息…`
                : `识别为「${label}」，正在执行…`,
            )
          }
        })
        if (!reply) throw new Error('流式连接中断')
      } catch (error: any) {
        // 任务已经发起，不能再用 POST 重发；直接重载会话拿已落库结果
        streamInterrupted = true
        removeMessage(statusId)
        removeMessage(tempId)
        await openSession(sessionId)
        messages.value.push({
          id: -Date.now() - 3,
          role: 'assistant',
          text:
            '流式连接中断，任务可能仍在后台执行；已为你刷新会话，稍后可重新打开查看结果。',
          cardData: {},
          chips: [],
        })
        messages.value[messages.value.length - 1].errorText =
          error?.message || '流式连接中断'
        scrollBottom()
      }
    }
  }

  // POST 兜底：浏览器不支持流式或流式任务尚未创建时，走原来的同步接口
  if (!reply && !streamInterrupted) {
    try {
      reply = await sendChatMessage(sessionId, request)
    } catch (error: any) {
      removeMessage(statusId)
      const index = messages.value.findIndex((item) => item.id === tempId)
      if (index >= 0) messages.value[index].errorText = error?.message || '发送失败'
      messages.value.push({
        id: -Date.now() - 4,
        role: 'assistant',
        text: '这次请求没有成功，页面上的同名按钮仍然可用。',
        cardData: {},
        chips: [],
      })
    }
  }

  if (reply) {
    removeMessage(statusId)
    const index = messages.value.findIndex((item) => item.id === tempId)
    if (index >= 0) messages.value.splice(index, 1, toMsg(reply.user_message))
    else if (!messages.value.some((item) => item.id === reply!.user_message.id)) {
      messages.value.push(toMsg(reply.user_message))
    }
    reply.replies.forEach((item) => messages.value.push(toMsg(item)))
    upsertSession(reply.session)
    if (reply.session.context_job_id) contextJobId.value = reply.session.context_job_id
  }

  sending.value = false
  scrollBottom()
}

function onChip(chip: Chip) {
  if (chip.href) return
  void sendText(chip.text)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void sendText(input.value)
  }
}

// ---------------------------------------------------------------- 上传
function pickFiles() {
  if (uploading.value) return
  fileInput.value?.click()
}

async function onFiles(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  if (!files.length || !activeId.value) return

  uploading.value = true
  const tempId = -Date.now()
  messages.value.push({
    id: tempId,
    role: 'assistant',
    text: `正在上传并解析 ${files.length} 份简历…`,
    cardData: {},
    chips: [],
  })
  scrollBottom()
  try {
    const uploaded = await uploadResumes(files, contextJobId.value ?? undefined)
    const ids = uploaded.items
      .map((item) => item.file_id)
      .filter((value): value is number => value != null)
    const failed = uploaded.items.filter((item) => item.status === 'failed').length
    const index = messages.value.findIndex((item) => item.id === tempId)
    if (index >= 0) messages.value.splice(index, 1)
    const note = failed ? `（${failed} 份上传失败）` : ''
    await sendText(`上传了 ${files.length} 份简历${note}，开始解析`, ids)
  } catch (error: any) {
    const index = messages.value.findIndex((item) => item.id === tempId)
    if (index >= 0) messages.value.splice(index, 1)
    messages.value.push({
      id: -Date.now() - 1,
      role: 'assistant',
      text: `上传失败：${error?.message || '请稍后重试'}`,
      cardData: {},
      chips: [],
    })
  } finally {
    uploading.value = false
    target.value = ''
    scrollBottom()
  }
}

// ---------------------------------------------------------------- 确认卡
async function confirmCard(message: Msg) {
  if (!activeId.value) return
  try {
    const note = (confirmNotes.value[String(message.id)] || '').trim()
    const result = await confirmChatAction(activeId.value, {
      message_id: message.id,
      note: note || null,
    })
    message.cardData = {
      ...message.cardData,
      status: 'done',
      resultText: result.message.content,
    }
    messages.value.push(toMsg(result.message))
    scrollBottom()
  } catch (error: any) {
    message.errorText = error?.message || '执行失败'
  }
}

function cancelConfirm(message: Msg) {
  message.cardData = { ...message.cardData, status: 'cancelled' }
}

// ---------------------------------------------------------------- 展示
function fmtTime(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return `${date.getHours().toString().padStart(2, '0')}:${date
      .getMinutes()
      .toString()
      .padStart(2, '0')}`
  }
  return `${date.getMonth() + 1}/${date.getDate()}`
}

function sessionSub(session: ChatSession): string {
  const text = session.last_message || ''
  if (text) return text.length > 22 ? `${text.slice(0, 22)}…` : text
  return `${session.message_count} 条消息`
}

function toggleReason(rank: Record<string, any>) {
  rank.open = !rank.open
}

onMounted(async () => {
  await loadJobs()
  await loadSessions()
})
</script>

<template>
  <div class="workbench">
    <!-- 左：会话列表 -->
    <aside class="sessions">
      <div class="sessions-head">
        <span>会话</span>
        <button class="new-chat" :disabled="sending" @click="newSession">+ 新会话</button>
      </div>
      <button
        v-for="session in sessions"
        :key="session.id"
        class="session"
        :class="{ active: session.id === activeId }"
        @click="openSession(session.id)"
      >
        <div class="t">
          <span v-if="session.id === activeId" class="pill-live"></span>
          {{ session.title || '未命名会话' }}
        </div>
        <div class="s">
          {{ sessionSub(session) }}
          <span class="time">{{ fmtTime(session.last_message_at) }}</span>
        </div>
      </button>
      <div v-if="!sessions.length" class="sessions-empty">还没有会话</div>
    </aside>

    <!-- 中：对话流 -->
    <div class="chat-col">
      <div class="chat-head">
        <div>
          <div class="title">{{ activeSession?.title || '新会话' }}</div>
          <div class="sub">
            上下文：{{ currentJob ? currentJob.title : '暂无职位' }} ·
            <span class="live-tag">已接 Chat Gateway</span>
          </div>
        </div>
        <div class="spacer"></div>
        <button class="btn-replay" :disabled="sending" @click="newSession">
          ＋ 新会话
        </button>
      </div>

      <div ref="streamEl" class="chat-stream">
        <div v-if="bootError" class="banner-error">{{ bootError }}</div>

        <div v-if="!messages.length && !bootError" class="empty-state">
          <div class="emoji">🤖</div>
          <div class="hello">你好，我是 TalentMatch。</div>
          <div class="hint">
            可以直接说需求，比如「我传了一批简历」「看看这批简历谁适合后端岗」。
          </div>
          <div class="chips center">
            <button class="chip" @click="sendText('我传了一批简历')">📥 我传了一批简历</button>
            <button class="chip" @click="sendText('看看这批简历谁适合后端岗')">
              🎯 智能匹配
            </button>
            <button class="chip" @click="sendText('给前三个出面试题')">💬 生成面试题</button>
            <button class="chip" @click="sendText('这个月哪个渠道效率最高？')">
              📊 本月渠道
            </button>
          </div>
        </div>

        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <div v-if="m.role === 'assistant'" class="avatar-bot">🤖</div>
          <div class="bubble">
            <div v-if="m.text" class="text">{{ m.text }}</div>
            <div v-if="m.errorText" class="error-text">{{ m.errorText }}</div>

            <!-- ① 上传卡 -->
            <div v-if="m.cardType === 'upload'" class="card">
              <div class="upload-zone" :class="{ disabled: uploading }" @click="pickFiles">
                <div class="big">⬆</div>
                <div>拖拽 PDF / DOCX 到这里，或点击选择文件</div>
                <div class="hint">
                  目标职位：{{ m.cardData.target || currentJob?.title || '未选择职位' }}
                </div>
                <div v-if="uploading" class="hint">上传中…</div>
              </div>
            </div>

            <!-- ② 解析结果卡 -->
            <div v-if="m.cardType === 'parse_result'" class="card">
              <div class="card-head">
                📋 {{ m.cardData.title || '解析结果' }}
                <span class="tag">
                  {{ m.cardData.success ?? 0 }} 成功 · {{ m.cardData.failed ?? 0 }} 失败
                </span>
              </div>
              <table v-if="m.cardData.rows?.length" class="tb">
                <thead>
                  <tr><th>姓名</th><th>年限</th><th>技能</th><th>状态</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, index) in m.cardData.rows" :key="index">
                    <td class="name-cell">{{ row.name }}</td>
                    <td>{{ row.years }}</td>
                    <td>
                      <span v-for="skill in row.skills" :key="skill" class="skill">
                        {{ skill }}
                      </span>
                      <span v-if="!row.skills?.length" class="muted">—</span>
                    </td>
                    <td>
                      <span class="badge" :class="row.status === 'ok' ? 'ok' : 'bad'">
                        {{ row.status === 'ok' ? '已入库' : row.error || '解析失败' }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="card-body muted">没有可展示的记录。</div>
            </div>

            <!-- ③ 匹配排名卡 -->
            <div v-if="m.cardType === 'match_rank'" class="card">
              <div class="card-head">
                🎯 匹配结果
                <span class="tag">
                  {{ m.cardData.job_title || currentJob?.title || '职位' }} ·
                  {{ m.cardData.total ?? 0 }} 人
                </span>
              </div>
              <template v-if="m.cardData.ranks?.length">
                <template v-for="rank in m.cardData.ranks" :key="rank.no">
                  <div class="rank-row">
                    <div class="rank-no">{{ rank.no }}</div>
                    <div class="rank-main">
                      <div class="rank-name">
                        {{ rank.name }}
                        <span class="score" :class="{ mid: rank.score < 85 }">
                          {{ rank.score }} 分
                        </span>
                      </div>
                      <div class="rank-sub">{{ rank.sub }}</div>
                    </div>
                    <button v-if="rank.reason" class="link" @click="toggleReason(rank)">
                      {{ rank.open ? '收起' : '展开理由' }}
                    </button>
                  </div>
                  <div v-if="rank.open" class="reason">{{ rank.reason }}</div>
                </template>
              </template>
              <div v-else class="card-body muted">没有可匹配的候选人。</div>
            </div>

            <!-- ④ 面试题卡 -->
            <div v-if="m.cardType === 'interview'" class="card">
              <div class="card-head">
                💬 {{ m.cardData.name }} · 面试题
                <span class="tag">{{ m.cardData.count ?? 0 }} 道</span>
              </div>
              <div
                v-for="(question, index) in m.cardData.questions"
                :key="index"
                class="q-item"
              >
                <div class="q-cat">{{ question.cat }}</div>
                <div>
                  <div class="q-text">{{ question.q }}</div>
                  <div v-if="question.look" class="q-look">{{ question.look }}</div>
                  <div v-if="question.reference" class="q-ref">
                    依据：{{ question.reference }}
                  </div>
                </div>
              </div>
            </div>

            <!-- ⑤ 确认卡 -->
            <div v-if="m.cardType === 'confirm'" class="card confirm">
              <div class="card-head">⚠️ 操作确认</div>
              <div class="card-body">
                <template v-if="m.cardData.status === 'pending'">
                  <div v-if="m.cardData.action === 'advance_status'" class="change-line">
                    <b>{{ m.cardData.candidate_name }}</b>
                    <span class="badge">{{ m.cardData.from_label }}</span>
                    <span class="arrow">→</span>
                    <span class="badge info">{{ m.cardData.to_label }}</span>
                  </div>
                  <template v-else>
                    <div class="change-line">
                      <b>{{ m.cardData.job_title }}</b>
                      <span class="badge info">发布计划</span>
                    </div>
                    <ol class="plan-list">
                      <li v-for="step in m.cardData.plan || []" :key="step">{{ step }}</li>
                    </ol>
                  </template>
                  <div class="warn-text">{{ m.cardData.warning }}</div>
                  <input
                    v-if="m.cardData.requires_reason"
                    v-model="confirmNotes[String(m.id)]"
                    class="reason-input"
                    placeholder="请填写淘汰原因（必填）"
                  />
                </template>
                <div v-else-if="m.cardData.status === 'done'" class="ok-text">
                  ✓ {{ m.cardData.resultText }}
                </div>
                <div v-else class="muted">已取消，本次没有修改任何数据。</div>
              </div>
              <div v-if="m.cardData.status === 'pending'" class="btn-row">
                <button class="btn ghost sm" :disabled="sending" @click="cancelConfirm(m)">
                  取消
                </button>
                <button class="btn primary sm" :disabled="sending" @click="confirmCard(m)">
                  确认执行
                </button>
              </div>
            </div>

            <!-- ⑥ 图表卡 -->
            <div v-if="m.cardType === 'chart'" class="card">
              <div class="card-head">
                📡 {{ m.cardData.title || '渠道效果' }}
                <span class="tag">本月</span>
              </div>
              <div class="card-body">
                <div v-if="m.cardData.channels?.length" class="chans">
                  <div
                    v-for="channel in m.cardData.channels"
                    :key="channel.label"
                    class="chan"
                  >
                    <div class="vl">{{ channel.value }}</div>
                    <div class="bar" :style="{ height: Math.max(channel.pct, 8) + '%' }"></div>
                    <div class="lb">{{ channel.label }}</div>
                  </div>
                </div>
                <div v-else class="muted">本月还没有渠道数据。</div>
              </div>
              <div v-if="m.cardData.insights?.length" class="card-foot">
                🤖 {{ m.cardData.insights.join('；') }}
              </div>
            </div>

            <!-- 快捷选项 / 追问选项 -->
            <div v-if="m.chips?.length" class="chips">
              <template v-for="chip in m.chips" :key="chip.label">
                <RouterLink v-if="chip.href" :to="chip.href" class="chip">
                  {{ chip.label }}
                </RouterLink>
                <button
                  v-else
                  class="chip"
                  :disabled="sending"
                  @click="onChip(chip)"
                >
                  {{ chip.label }}
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>

      <div class="composer">
        <div class="composer-box">
          <textarea
            v-model="input"
            rows="1"
            placeholder="说需求，比如：看看这批简历谁适合后端岗"
            @keydown="onKeydown"
          ></textarea>
          <button class="send" :disabled="sending || !input.trim()" @click="sendText(input)">
            ➤
          </button>
        </div>
        <div class="composer-hint">
          <span><span class="kbd">Enter</span> 发送 · <span class="kbd">Shift+Enter</span> 换行</span>
          <span>不可逆操作会先向你确认</span>
        </div>
      </div>
    </div>

    <!-- 右：上下文面板 -->
    <aside class="context">
      <div class="ctx-card">
        <div class="ctx-head">📌 当前职位</div>
        <div class="ctx-body">
          <template v-if="currentJob">
            <div class="job-title">
              {{ currentJob.title }}
              <span class="badge ok">
                {{ currentJob.status === 'published' ? '招聘中' : currentJob.status }}
              </span>
            </div>
            <div class="job-meta">
              {{ currentJob.department || '未填部门' }} ·
              {{ currentJob.location || '未填地点' }} · 招 {{ currentJob.headcount }} 人
              <template v-if="currentJob.salary_min != null">
                · {{ currentJob.salary_min }}-{{ currentJob.salary_max }}K
              </template>
            </div>
            <div class="skills-line">
              <span v-for="skill in jobSkills" :key="skill" class="skill">{{ skill }}</span>
            </div>
          </template>
          <template v-else>
            <div class="muted">暂无职位上下文</div>
            <div class="job-meta">发布职位后，这里会成为对话的默认匹配对象。</div>
          </template>

          <select
            v-if="switchableJobs.length"
            v-model="contextJobId"
            class="job-select"
            @change="switchJob"
          >
            <option :value="null">不指定职位</option>
            <option v-for="job in switchableJobs" :key="job.id" :value="job.id">
              {{ job.title }}
            </option>
          </select>
          <div class="ctx-actions">
            <RouterLink to="/jobs" class="btn ghost sm">职位管理</RouterLink>
          </div>
        </div>
      </div>

      <div class="ctx-card">
        <div class="ctx-head">📦 最近批次</div>
        <div class="ctx-body">
          <template v-if="lastBatch">
            <div class="ctx-row">
              <span class="k">成功 / 失败</span>
              <span class="v">
                {{ lastBatch.success ?? 0 }} / {{ lastBatch.failed ?? 0 }}
              </span>
            </div>
            <div class="mini-bar"><i :style="{ width: batchPercent + '%' }"></i></div>
          </template>
          <div v-else class="muted">还没有上传记录</div>
        </div>
      </div>

      <div class="ctx-card">
        <div class="ctx-head">⚡ 快捷操作</div>
        <div class="ctx-body quick">
          <button :disabled="sending" @click="sendText('看看这批简历谁适合后端岗')">
            🎯 智能匹配
          </button>
          <button :disabled="sending" @click="sendText('给前三个出面试题')">
            💬 生成面试题
          </button>
          <button :disabled="sending" @click="sendText('把这个候选人推进到面试中')">
            ➡️ 推进状态
          </button>
          <button :disabled="sending" @click="sendText('这个月哪个渠道效率最高？')">
            📊 查看看板
          </button>
        </div>
      </div>

      <div class="ctx-card">
        <div class="ctx-head">📊 今日</div>
        <div class="ctx-body">
          <div class="ctx-row"><span class="k">职位总数</span><span class="v">{{ todayStats.jobs }}</span></div>
          <div class="ctx-row"><span class="k">招聘中</span><span class="v">{{ todayStats.published }}</span></div>
          <div class="ctx-row">
            <span class="k">服务</span>
            <span class="v" :style="{ color: healthOk ? 'var(--success)' : 'var(--danger)' }">
              {{ healthOk === null ? '检测中' : healthOk ? '正常' : '异常' }}
            </span>
          </div>
        </div>
      </div>
    </aside>

    <input
      ref="fileInput"
      type="file"
      multiple
      accept=".pdf,.doc,.docx"
      hidden
      @change="onFiles"
    />
  </div>
</template>

<style scoped>
.workbench {
  height: 100%;
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr) 300px;
}

/* ---------------- 左：会话 ---------------- */
.sessions {
  background: var(--panel);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 10px;
  overflow: auto;
}
.sessions-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 8px 8px;
}
.sessions-head span {
  font-size: 12.5px;
  color: var(--faint);
  font-weight: 600;
  letter-spacing: 0.4px;
}
.new-chat {
  border: 1px solid var(--line-strong);
  background: #fff;
  border-radius: 8px;
  padding: 3px 9px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
}
.new-chat:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}
.new-chat:disabled {
  opacity: 0.5;
  cursor: default;
}
.session {
  text-align: left;
  padding: 9px 10px;
  border-radius: 9px;
  cursor: pointer;
  border: 1px solid transparent;
  background: transparent;
  transition: 0.15s;
  font: inherit;
}
.session:hover {
  background: #f6f7fb;
}
.session.active {
  background: var(--primary-soft);
  border-color: #dfe3ff;
}
.session .t {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text);
}
.session .s {
  font-size: 11.5px;
  color: var(--faint);
  margin-top: 2px;
  display: flex;
  justify-content: space-between;
  gap: 6px;
}
.session .time {
  flex: 0 0 auto;
}
.pill-live {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  flex: 0 0 auto;
}
.sessions-empty {
  padding: 18px 10px;
  font-size: 12px;
  color: var(--faint);
  text-align: center;
}

/* ---------------- 中：对话 ---------------- */
.chat-col {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
}
.chat-head {
  height: 52px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
.chat-head .title {
  font-weight: 650;
  font-size: 14px;
}
.chat-head .sub {
  font-size: 12px;
  color: var(--faint);
  margin-top: 1px;
}
.chat-head .spacer {
  flex: 1;
}
.live-tag {
  background: var(--success-soft);
  color: var(--success);
  border-radius: 5px;
  padding: 0 5px;
  font-size: 11px;
  font-weight: 600;
}
.btn-replay {
  border: 1px solid var(--line-strong);
  background: #fff;
  border-radius: 8px;
  padding: 5px 11px;
  font-size: 12.5px;
  color: var(--muted);
  cursor: pointer;
}
.btn-replay:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}
.btn-replay:disabled {
  opacity: 0.5;
  cursor: default;
}

.chat-stream {
  flex: 1;
  overflow-y: auto;
  padding: 20px 22px 10px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.banner-error {
  background: var(--danger-soft);
  color: var(--danger);
  border-radius: 9px;
  padding: 9px 12px;
  font-size: 12.5px;
}
.empty-state {
  margin: auto;
  text-align: center;
  max-width: 520px;
  color: var(--muted);
}
.empty-state .emoji {
  font-size: 34px;
}
.empty-state .hello {
  font-weight: 650;
  font-size: 15px;
  color: var(--text);
  margin-top: 8px;
}
.empty-state .hint {
  font-size: 12.5px;
  margin-top: 6px;
  line-height: 1.7;
}
.chips.center {
  justify-content: center;
}
.msg {
  display: flex;
  gap: 9px;
}
.msg.user {
  justify-content: flex-end;
}
.avatar-bot {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #eef1ff, #e0e4ff);
  font-size: 15px;
}
.bubble {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 13px;
  box-shadow: var(--shadow-sm);
  max-width: min(680px, 86%);
  font-size: 13.5px;
}
.msg.user .bubble {
  background: var(--primary);
  color: #fff;
  border-color: transparent;
  border-bottom-right-radius: 4px;
}
.text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}
.error-text {
  color: var(--danger);
  font-size: 12px;
  margin-top: 6px;
}

/* 卡片 */
.card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 11px;
  overflow: hidden;
  margin-top: 9px;
  color: var(--text);
}
.card-head {
  padding: 9px 13px;
  background: #fafbfe;
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
  font-weight: 650;
  color: #3b4152;
  display: flex;
  align-items: center;
  gap: 7px;
}
.card-head .tag {
  margin-left: auto;
  font-size: 11px;
  color: var(--faint);
}
.card-body {
  padding: 11px 13px;
}
.card-foot {
  padding: 9px 13px;
  border-top: 1px solid var(--line);
  background: #fafbfe;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

/* 上传 */
.upload-zone {
  border: 1.5px dashed #c7cbe0;
  border-radius: 10px;
  padding: 18px;
  text-align: center;
  color: var(--muted);
  background: #fbfbff;
  cursor: pointer;
  margin: 4px;
  transition: 0.15s;
}
.upload-zone:hover:not(.disabled) {
  border-color: var(--primary);
  background: #f6f7ff;
}
.upload-zone.disabled {
  opacity: 0.6;
  cursor: default;
}
.upload-zone .big {
  font-size: 22px;
}
.upload-zone .hint {
  font-size: 12px;
  color: var(--faint);
  margin-top: 5px;
}

/* 表格 */
.tb {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.tb th {
  text-align: left;
  font-weight: 600;
  color: var(--faint);
  font-size: 11.5px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  background: #fcfcfe;
}
.tb td {
  padding: 7px 10px;
  border-bottom: 1px solid #f0f1f6;
}
.tb tr:last-child td {
  border-bottom: 0;
}
.name-cell {
  font-weight: 600;
}
.muted {
  color: var(--faint);
}

/* 标签 */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 20px;
  background: #f1f2f8;
  color: var(--muted);
  white-space: nowrap;
}
.badge.ok {
  background: var(--success-soft);
  color: var(--success);
}
.badge.bad {
  background: var(--danger-soft);
  color: var(--danger);
}
.badge.info {
  background: var(--primary-soft);
  color: var(--primary);
}
.skill {
  display: inline-block;
  font-size: 11px;
  padding: 1.5px 7px;
  border-radius: 6px;
  background: #f3f4fa;
  color: #525a6b;
  margin: 1px 3px 1px 0;
}

/* 排名 */
.rank-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 13px;
  border-bottom: 1px solid #f1f2f7;
}
.rank-no {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: #f1f2f8;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  margin-top: 1px;
}
.rank-main {
  flex: 1;
  min-width: 0;
}
.rank-name {
  font-weight: 650;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.score {
  font-size: 11.5px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 20px;
  background: var(--success-soft);
  color: var(--success);
}
.score.mid {
  background: var(--warn-soft);
  color: var(--warn);
}
.rank-sub {
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 3px;
  line-height: 1.5;
}
.link {
  border: 0;
  background: none;
  color: var(--primary);
  font-size: 11.5px;
  padding: 0;
  white-space: nowrap;
  cursor: pointer;
}
.reason {
  font-size: 12px;
  color: #4b5563;
  background: #fbfbff;
  border-top: 1px dashed var(--line);
  padding: 10px 13px;
  line-height: 1.65;
}

/* 面试题 */
.q-item {
  padding: 9px 13px;
  border-bottom: 1px solid #f1f2f7;
  display: flex;
  gap: 9px;
}
.q-item:last-child {
  border-bottom: 0;
}
.q-cat {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-soft);
  border-radius: 5px;
  padding: 2px 6px;
  height: fit-content;
  white-space: nowrap;
  margin-top: 1px;
}
.q-text {
  font-size: 12.5px;
  line-height: 1.6;
}
.q-look {
  font-size: 11px;
  color: var(--faint);
  margin-top: 3px;
}
.q-ref {
  font-size: 11px;
  color: var(--muted);
  margin-top: 3px;
}

/* 确认 */
.confirm {
  border-color: #f0d9a8;
  background: #fffdf7;
}
.confirm .card-head {
  background: var(--warn-soft);
  border-bottom-color: #f3e2b8;
  color: #92400e;
}
.change-line {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13.5px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.arrow {
  color: var(--faint);
}
.plan-list {
  margin: 0 0 8px 18px;
  padding: 0;
  font-size: 12.5px;
  line-height: 1.8;
}
.warn-text {
  font-size: 12px;
  color: #92400e;
  background: var(--warn-soft);
  border-radius: 7px;
  padding: 7px 10px;
  line-height: 1.6;
}
.reason-input {
  width: 100%;
  margin-top: 8px;
  border: 1px solid #e5cf9f;
  border-radius: 8px;
  padding: 7px 9px;
  font: inherit;
  font-size: 12.5px;
  outline: none;
  background: #fff;
}
.reason-input:focus {
  border-color: var(--warn);
}
.ok-text {
  color: var(--success);
  font-weight: 600;
  font-size: 13px;
  line-height: 1.7;
}
.btn-row {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 10px 13px;
  border-top: 1px solid #f3e2b8;
  background: #fffdf7;
}
.btn {
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12.5px;
  font-weight: 600;
  border: 1px solid transparent;
  cursor: pointer;
  text-decoration: none;
}
.btn.primary {
  background: var(--primary);
  color: #fff;
}
.btn.ghost {
  background: #fff;
  border-color: var(--line-strong);
  color: var(--muted);
}
.btn.sm {
  padding: 4px 10px;
  font-size: 11.5px;
  display: inline-block;
}
.btn:disabled {
  opacity: 0.55;
  cursor: default;
}

/* 图表 */
.chans {
  display: flex;
  align-items: flex-end;
  gap: 22px;
  height: 130px;
  padding: 6px 6px 0;
}
.chan {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  height: 100%;
  justify-content: flex-end;
}
.chan .bar {
  width: 100%;
  max-width: 56px;
  border-radius: 8px 8px 4px 4px;
  background: linear-gradient(180deg, #818cf8, #6366f1);
}
.chan .lb {
  font-size: 11.5px;
  color: var(--muted);
}
.chan .vl {
  font-size: 12px;
  font-weight: 700;
}

/* chips */
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 10px;
}
.chip {
  border: 1px solid #dcdff0;
  background: #fff;
  color: var(--primary);
  border-radius: 20px;
  padding: 5px 12px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: 0.15s;
  text-decoration: none;
  font-family: inherit;
}
.chip:hover:not(:disabled) {
  background: var(--primary-soft);
  border-color: #c9cffa;
}
.chip:disabled {
  opacity: 0.45;
  cursor: default;
}

/* 输入 */
.composer {
  flex: 0 0 auto;
  padding: 12px 22px 16px;
  background: var(--panel);
  border-top: 1px solid var(--line);
}
.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  padding: 8px 10px;
  background: #fff;
}
.composer-box:focus-within {
  border-color: var(--primary);
  box-shadow: var(--ring);
}
.composer textarea {
  flex: 1;
  border: 0;
  outline: 0;
  resize: none;
  font: inherit;
  font-size: 13.5px;
  max-height: 110px;
  min-height: 22px;
  padding: 2px 0;
  background: transparent;
  color: var(--text);
}
.send {
  border: 0;
  background: var(--primary);
  color: #fff;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-size: 15px;
  flex: 0 0 auto;
  cursor: pointer;
}
.send:disabled {
  opacity: 0.5;
  cursor: default;
}
.composer-hint {
  font-size: 11px;
  color: var(--faint);
  margin-top: 7px;
  display: flex;
  gap: 14px;
}
.kbd {
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  padding: 0 4px;
  font-size: 10px;
}

/* ---------------- 右：上下文 ---------------- */
.context {
  background: var(--panel);
  border-left: 1px solid var(--line);
  overflow-y: auto;
  padding: 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.ctx-card {
  border: 1px solid var(--line);
  border-radius: 11px;
  overflow: hidden;
}
.ctx-head {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--faint);
  letter-spacing: 0.4px;
  padding: 9px 12px;
  background: #fafbfe;
  border-bottom: 1px solid var(--line);
}
.ctx-body {
  padding: 11px 12px;
}
.job-title {
  font-weight: 650;
  font-size: 13.5px;
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.job-meta {
  font-size: 11.5px;
  color: var(--faint);
  margin-top: 4px;
  line-height: 1.6;
}
.skills-line {
  margin-top: 8px;
}
.job-select {
  width: 100%;
  margin-top: 10px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  padding: 6px 8px;
  font: inherit;
  font-size: 12.5px;
  color: var(--text);
  background: #fff;
}
.ctx-actions {
  margin-top: 10px;
}
.ctx-row {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  padding: 4px 0;
}
.ctx-row .k {
  color: var(--faint);
}
.ctx-row .v {
  font-weight: 600;
}
.quick {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.quick button {
  text-align: left;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 8px;
  padding: 8px 11px;
  font-size: 12.5px;
  color: var(--text);
  cursor: pointer;
  transition: 0.15s;
  font-family: inherit;
}
.quick button:hover:not(:disabled) {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}
.quick button:disabled {
  opacity: 0.5;
  cursor: default;
}
.mini-bar {
  height: 5px;
  background: #edeff6;
  border-radius: 5px;
  overflow: hidden;
  margin-top: 6px;
}
.mini-bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
}

@media (max-width: 1180px) {
  .workbench {
    grid-template-columns: 200px minmax(0, 1fr) 260px;
  }
}
@media (max-width: 980px) {
  .workbench {
    grid-template-columns: minmax(0, 1fr);
  }
  .sessions,
  .context {
    display: none;
  }
}
</style>
