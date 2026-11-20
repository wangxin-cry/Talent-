<script setup lang="ts">
/**
 * 工作台（对话式）
 *
 * 与 docs/TalentMatch_界面原型.html 对齐：三栏 = 会话列表 / 对话流+卡片 / 上下文面板
 *
 * 说明：当前阶段（阶段一~三）后端还没有编排与对话接口，
 * 因此对话流是**界面演示**（脚本驱动），右栏"当前职位/今日"是**真实数据**。
 * 阶段九½ 接入 Chat Gateway 后，把 messages 换成后端返回即可，布局不动。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import client from '@/api/client'
import { listJobs } from '@/api/jobs'
import type { Job } from '@/api/jobs'

// ---------------------------------------------------------------- 类型
interface Chip {
  label: string
  action: string
}

interface Msg {
  id: number
  role: 'user' | 'bot'
  text?: string
  kind?: 'upload' | 'progress' | 'parse' | 'rank' | 'interview' | 'confirm' | 'chart'
  data?: Record<string, any>
  chips?: Chip[]
}

interface ParseRow {
  name: string
  years: string
  skills: string[]
  status: 'ok' | 'fail'
}

interface RankRow {
  no: number
  name: string
  score: number
  sub: string
  reason: string
  open: boolean
}

interface Question {
  cat: string
  q: string
  look: string
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// ---------------------------------------------------------------- 会话列表
const sessions = [
  { title: 'Python 岗筛选', sub: '10 份简历 · 刚刚', active: true, live: true },
  { title: '前端岗初筛', sub: '6 份简历 · 昨天', active: false, live: false },
  { title: '面试题准备', sub: '张伟 · 3 天前', active: false, live: false },
  { title: '本月数据盘点', sub: '看板 · 上周', active: false, live: false },
]

// ---------------------------------------------------------------- 上下文（真实数据）
const currentJob = ref<Job | null>(null)
const todayStats = ref({ jobs: 0, published: 0 })
const healthOk = ref<boolean | null>(null)

async function loadContext() {
  try {
    const published = await listJobs({ status: 'published', page: 1, page_size: 1 })
    currentJob.value = published.items[0] ?? null
    const all = await listJobs({ page: 1, page_size: 1 })
    todayStats.value = { jobs: all.total, published: published.total }
  } catch {
    // 后端未启动时保持空态
  }
  try {
    const { data } = await client.get('/healthz')
    healthOk.value = data?.status === 'ok'
  } catch {
    healthOk.value = false
  }
}

const jobSkills = computed(() => currentJob.value?.skills?.map((s) => s.name) ?? [])

// ---------------------------------------------------------------- 对话流
const messages = ref<Msg[]>([])
let seq = 0
const streamEl = ref<HTMLElement | null>(null)
const drafting = ref(false)

function scrollBottom() {
  nextTick(() => {
    if (streamEl.value) streamEl.value.scrollTop = streamEl.value.scrollHeight
  })
}

function push(m: Omit<Msg, 'id'>): Msg {
  messages.value.push({ ...m, id: ++seq })
  scrollBottom()
  return messages.value[messages.value.length - 1]
}

function chip(label: string, action: string): Chip {
  return { label, action }
}

// 演示脚本用到的数据
const PARSE_ROWS: ParseRow[] = [
  { name: '张伟', years: '5 年', skills: ['Python', 'FastAPI', 'MySQL'], status: 'ok' },
  { name: '李娜', years: '3 年', skills: ['Vue', 'TypeScript'], status: 'ok' },
  { name: '王强', years: '4 年', skills: ['Python', 'Django'], status: 'ok' },
  { name: '赵敏', years: '—', skills: [], status: 'fail' },
]

function buildRanks(): RankRow[] {
  const jobTitle = currentJob.value?.title ?? 'Python 后端工程师'
  return [
    {
      no: 1,
      name: '张伟',
      score: 87,
      sub: '命中 Python · FastAPI · MySQL ｜ 缺 Redis 深度 ｜ 经验 5 年（要求 3 年）',
      reason:
        '技能 0.87：必备技能 3/3 全命中，加分技能 1/3；经验 0.92：5 年超过要求，电商场景相关；学历 1.00：本科满足；其他 0.80：上海本地、薪资区间重叠。',
      open: false,
    },
    {
      no: 2,
      name: '周洋',
      score: 85,
      sub: '命中 Python · K8s ｜ 经验 5 年 ｜ 云计算背景',
      reason: '技能 0.90：必备技能全命中且有 K8s 加分；经验 0.95：5 年云计算高度相关。',
      open: false,
    },
    {
      no: 3,
      name: '李娜',
      score: 81,
      sub: '命中 Python · Redis ｜ 经验 3 年 ｜ 前端转后端',
      reason: '技能 0.78：必备技能 2/3，缺 SQLAlchemy；经验 0.70：3 年刚达标，主要经验在前端。',
      open: false,
    },
  ].map((r) => ({ ...r, sub: r.sub.replace('Python 后端工程师', jobTitle) }))
}

const QUESTIONS: Question[] = [
  { cat: '技术深挖', q: '你在电商公司用 FastAPI 做过哪些接口？异步和依赖注入怎么用的？', look: '考察点：异步模型、依赖注入实践' },
  { cat: '项目追问', q: '你们订单服务怎么处理高并发？压测到多少 QPS？', look: '考察点：性能优化与瓶颈定位' },
  { cat: '缺口追问', q: '简历里没体现 Redis，你用过缓存解决过什么问题？', look: '考察点：是否补齐必备技能缺口' },
  { cat: '行为面试', q: '描述一次线上故障，你怎么排查和复盘的？', look: '考察点：故障处理与责任心' },
]

const CHANNELS = [
  { label: '官网', value: 42, pct: 100 },
  { label: '内推', value: 21, pct: 50 },
  { label: '猎头', value: 9, pct: 21 },
]

// ---------------------------------------------------------------- 演示流程
function resetDemo() {
  messages.value = []
  seq = 0
  drafting.value = false
  push({
    role: 'bot',
    text:
      '你好，我是 <b>TalentMatch</b>。可以直接说你想做什么，比如「看看这批简历谁适合后端岗」。' +
      '<div class="sub-note">当前上下文：' +
      (currentJob.value ? currentJob.value.title : '暂无在招职位') +
      ' · 界面演示，真实操作请到「职位」页</div>',
    chips: [
      chip('📥 我传了一批简历', 'upload'),
      chip('📊 本月哪个渠道效率最高？', 'analytics'),
      chip('ℹ️ 张伟现在什么状态？', 'status'),
    ],
  })
}

async function onChip(action: string) {
  if (drafting.value) return
  switch (action) {
    case 'upload':
      await actUpload()
      break
    case 'do-upload':
      await actDoUpload()
      break
    case 'match':
      await actMatch()
      break
    case 'interview':
      await actInterview()
      break
    case 'advance':
      await actAdvance()
      break
    case 'confirm-advance':
      await actConfirmAdvance()
      break
    case 'analytics':
      await actAnalytics()
      break
    case 'status':
      await actStatus()
      break
    case 'retry':
      push({ role: 'bot', text: '已重新提交解析（演示）：扫描件将尝试视觉模型兜底。' })
      break
  }
}

async function actUpload() {
  drafting.value = true
  push({ role: 'user', text: '我传了一批简历' })
  await sleep(420)
  push({
    role: 'bot',
    text: '好的，把文件拖进来吧（支持 PDF / DOCX，可批量）。',
    kind: 'upload',
    data: { target: currentJob.value?.title ?? '未选择职位' },
  })
  drafting.value = false
}

async function actDoUpload() {
  drafting.value = true
  push({ role: 'user', text: '（拖入了 10 个文件）' })
  await sleep(360)
  const pm = push({
    role: 'bot',
    kind: 'progress',
    text: '收到 10 份，正在解析…',
    data: { percent: 0, total: 10 },
  })
  for (let i = 1; i <= 10; i++) {
    await sleep(150)
    pm.data!.percent = i * 10
  }
  await sleep(420)
  push({
    role: 'bot',
    text: '解析完成：<b>9 份成功</b>，<b class="warn">1 份失败</b>。',
    kind: 'parse',
    data: { rows: PARSE_ROWS },
    chips: [chip('🎯 看看谁适合后端岗', 'match'), chip('🔁 重试失败的那份', 'retry')],
  })
  drafting.value = false
}

async function actMatch() {
  drafting.value = true
  push({ role: 'user', text: '看看谁适合后端岗' })
  await sleep(380)
  push({ role: 'bot', text: `正在用「${currentJob.value?.title ?? 'Python 后端工程师'}」匹配这 9 人…` })
  await sleep(900)
  push({
    role: 'bot',
    text: '匹配完成，按综合分排序（技能 50% + 经验 30% + 学历 12% + 其他 8%）：',
    kind: 'rank',
    data: { ranks: buildRanks() },
    chips: [chip('💬 前三个出面试题', 'interview'), chip('➡️ 把张伟推到面试', 'advance')],
  })
  drafting.value = false
}

async function actInterview() {
  drafting.value = true
  push({ role: 'user', text: '前三个出面试题' })
  await sleep(380)
  push({ role: 'bot', text: '正在为 <b>张伟、周洋、李娜</b> 并行生成面试题…（演示数据）' })
  await sleep(1100)
  push({
    role: 'bot',
    text: '已生成 <b>24 道题</b>（每人 8 道），耗时 3.2s，花费 ¥0.06。',
    kind: 'interview',
    data: { name: '张伟', questions: QUESTIONS },
    chips: [chip('➡️ 把张伟推到面试', 'advance')],
  })
  drafting.value = false
}

async function actAdvance() {
  drafting.value = true
  push({ role: 'user', text: '把张伟推到面试' })
  await sleep(380)
  push({
    role: 'bot',
    text: '这个操作会改变候选人状态，先跟你确认：',
    kind: 'confirm',
    data: { name: '张伟', from: '新申请', to: '面试中', resolved: false },
  })
  drafting.value = false
}

async function actConfirmAdvance() {
  const card = [...messages.value].reverse().find((m) => m.kind === 'confirm' && m.data && !m.data.resolved)
  if (card?.data) card.data.resolved = true
  await sleep(300)
  push({
    role: 'bot',
    text:
      '已更新状态并记录流转历史。<div class="done-card">' +
      '✅ 已完成<br>· 状态：新申请 → <b>面试中</b><br>' +
      '· 已写入流转历史（操作人：当前用户）<br>' +
      '· 已发送面试邀请通知（站内信 + 邮件）</div>',
  })
}

async function actAnalytics() {
  drafting.value = true
  push({ role: 'user', text: '本月哪个渠道效率最高？' })
  await sleep(420)
  push({
    role: 'bot',
    text: '本月各渠道简历量与转化（演示数据）：',
    kind: 'chart',
    data: { channels: CHANNELS },
  })
  drafting.value = false
}

async function actStatus() {
  drafting.value = true
  push({ role: 'user', text: '张伟现在什么状态？' })
  await sleep(380)
  push({
    role: 'bot',
    text:
      '张伟（' + (currentJob.value?.title ?? 'Python 后端工程师') + '）：<div class="done-card">' +
      '· 当前状态：<span class="pill">新申请</span><br>· 匹配分：<b>87</b><br>' +
      '· 投递时间：2026-11-18<br>· 已停留：1 天</div>',
  })
  drafting.value = false
}

// 输入框：关键词路由（演示）
const input = ref('')
async function sendTyped() {
  const text = input.value.trim()
  if (!text || drafting.value) return
  input.value = ''
  if (/传|上传|简历/.test(text) && !/适合|匹配/.test(text)) return void onChip('upload')
  if (/匹配|适合|排名|谁/.test(text)) return void onChip('match')
  if (/面试题|出题/.test(text)) return void onChip('interview')
  if (/推到|推进|状态/.test(text)) return void onChip('advance')
  if (/渠道|数据|看板|效率/.test(text)) return void onChip('analytics')
  push({ role: 'user', text })
  await sleep(320)
  push({
    role: 'bot',
    text: '我可以帮你做这些事（演示）：<br>· 📥 解析简历<br>· 🎯 人岗匹配<br>· 💬 生成面试题<br>· ➡️ 推进状态<br>· 📊 查数据',
  })
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void sendTyped()
  }
}

onMounted(async () => {
  await loadContext()
  resetDemo()
})
</script>

<template>
  <div class="workbench">
    <!-- 左：会话列表 -->
    <aside class="sessions">
      <div class="sessions-head">
        <span>会话</span>
        <button class="new-chat" disabled>+ 新会话</button>
      </div>
      <div
        v-for="s in sessions"
        :key="s.title"
        class="session"
        :class="{ active: s.active }"
      >
        <div class="t">
          <span v-if="s.live" class="pill-live"></span>{{ s.title }}
        </div>
        <div class="s">{{ s.sub }}</div>
      </div>
    </aside>

    <!-- 中：对话流 -->
    <div class="chat-col">
      <div class="chat-head">
        <div>
          <div class="title">Python 岗筛选</div>
          <div class="sub">
            上下文：{{ currentJob ? currentJob.title : '暂无在招职位' }} ·
            <span class="demo-tag">界面演示</span>
          </div>
        </div>
        <div class="spacer"></div>
        <button class="btn-replay" @click="resetDemo">↺ 重播演示</button>
      </div>

      <div ref="streamEl" class="chat-stream">
        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <div v-if="m.role === 'bot'" class="avatar-bot">🤖</div>
          <div class="bubble">
            <div v-if="m.text" class="text" v-html="m.text"></div>

            <!-- 上传卡 -->
            <div v-if="m.kind === 'upload'" class="card">
              <div class="upload-zone" @click="onChip('do-upload')">
                <div class="big">⬆</div>
                <div>拖拽 PDF / DOCX 到这里，或点击选择文件</div>
                <div class="hint">目标职位：{{ m.data?.target }}</div>
              </div>
            </div>

            <!-- 进度卡 -->
            <div v-if="m.kind === 'progress'" class="card">
              <div class="card-head">📥 正在解析简历<span class="tag">{{ m.data?.total }} 份</span></div>
              <div class="card-body">
                <div class="progress"><div class="progress-bar" :style="{ width: (m.data?.percent ?? 0) + '%' }"></div></div>
                <div class="progress-text">{{ Math.round((m.data?.percent ?? 0) / 10) }} / {{ m.data?.total }}</div>
              </div>
            </div>

            <!-- 解析结果卡 -->
            <div v-if="m.kind === 'parse'" class="card">
              <div class="card-head">📋 解析结果<span class="tag">9 成功 · 1 失败</span></div>
              <table class="tb">
                <thead><tr><th>姓名</th><th>年限</th><th>技能</th><th>状态</th></tr></thead>
                <tbody>
                  <tr v-for="r in m.data?.rows" :key="r.name">
                    <td class="name-cell">{{ r.name }}</td>
                    <td>{{ r.years }}</td>
                    <td>
                      <span v-for="sk in r.skills" :key="sk" class="skill">{{ sk }}</span>
                      <span v-if="!r.skills.length" class="muted">—</span>
                    </td>
                    <td>
                      <span class="badge" :class="r.status === 'ok' ? 'ok' : 'bad'">
                        {{ r.status === 'ok' ? '已入库' : '扫描件失败' }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 匹配排名卡 -->
            <div v-if="m.kind === 'rank'" class="card">
              <div class="card-head">🎯 匹配结果<span class="tag">{{ currentJob?.title ?? '职位' }} · 9 人</span></div>
              <template v-for="r in m.data?.ranks" :key="r.no">
                <div class="rank-row">
                  <div class="rank-no">{{ r.no }}</div>
                  <div class="rank-main">
                    <div class="rank-name">
                      {{ r.name }}
                      <span class="score" :class="{ mid: r.score < 85 }">{{ r.score }} 分</span>
                    </div>
                    <div class="rank-sub">{{ r.sub }}</div>
                  </div>
                  <button class="link" @click="r.open = !r.open">{{ r.open ? '收起' : '展开理由' }}</button>
                </div>
                <div v-if="r.open" class="reason">{{ r.reason }}</div>
              </template>
            </div>

            <!-- 面试题卡 -->
            <div v-if="m.kind === 'interview'" class="card">
              <div class="card-head">💬 {{ m.data?.name }} · 面试题<span class="tag">8 道 · 引用具体经历</span></div>
              <div v-for="q in m.data?.questions" :key="q.q" class="q-item">
                <div class="q-cat">{{ q.cat }}</div>
                <div>
                  <div class="q-text">{{ q.q }}</div>
                  <div class="q-look">{{ q.look }}</div>
                </div>
              </div>
            </div>

            <!-- 确认卡 -->
            <div v-if="m.kind === 'confirm'" class="card confirm">
              <div class="card-head">⚠️ 状态变更确认</div>
              <div class="card-body">
                <template v-if="!m.data?.resolved">
                  <div class="change-line">
                    <b>{{ m.data?.name }}</b>
                    <span class="badge">{{ m.data?.from }}</span>
                    <span class="arrow">→</span>
                    <span class="badge info">{{ m.data?.to }}</span>
                  </div>
                  <div class="warn-text">⚠️ 会跳过「筛选中」这一步，并将自动触发面试邀请通知。</div>
                </template>
                <div v-else class="ok-text">✓ 已推进：{{ m.data?.name }} {{ m.data?.from }} → {{ m.data?.to }}</div>
              </div>
              <div v-if="!m.data?.resolved" class="btn-row">
                <button class="btn ghost sm" @click="m.data!.resolved = false">取消</button>
                <button class="btn primary sm" @click="onChip('confirm-advance')">确认推进</button>
              </div>
            </div>

            <!-- 图表卡 -->
            <div v-if="m.kind === 'chart'" class="card">
              <div class="card-head">📡 渠道效果<span class="tag">本月 · 演示</span></div>
              <div class="card-body">
                <div class="chans">
                  <div v-for="c in m.data?.channels" :key="c.label" class="chan">
                    <div class="vl">{{ c.value }}</div>
                    <div class="bar" :style="{ height: Math.max(c.pct, 8) + '%' }"></div>
                    <div class="lb">{{ c.label }}</div>
                  </div>
                </div>
              </div>
              <div class="card-foot">🤖 内推转化率最高，猎头最低且单份成本最高。建议预算向内推倾斜。</div>
            </div>

            <!-- 快捷操作 -->
            <div v-if="m.chips?.length" class="chips">
              <button
                v-for="c in m.chips"
                :key="c.label"
                class="chip"
                :disabled="drafting"
                @click="onChip(c.action)"
              >
                {{ c.label }}
              </button>
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
          <button class="send" @click="sendTyped">➤</button>
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
              {{ currentJob.title }} <span class="badge ok">招聘中</span>
            </div>
            <div class="job-meta">
              {{ currentJob.department || '未填部门' }} · {{ currentJob.location || '未填地点' }} ·
              招 {{ currentJob.headcount }} 人
              <template v-if="currentJob.salary_min != null">
                · {{ currentJob.salary_min }}-{{ currentJob.salary_max }}K
              </template>
            </div>
            <div class="skills-line">
              <span v-for="sk in jobSkills" :key="sk" class="skill">{{ sk }}</span>
            </div>
          </template>
          <template v-else>
            <div class="muted">暂无在招职位</div>
            <div class="job-meta">去「职位」页发布一个职位后，这里会显示上下文</div>
          </template>
          <div style="margin-top: 10px">
            <RouterLink to="/jobs" class="btn ghost sm">切换职位</RouterLink>
          </div>
        </div>
      </div>

      <div class="ctx-card">
        <div class="ctx-head">📦 最近批次</div>
        <div class="ctx-body">
          <div class="ctx-row"><span class="k">状态</span><span class="v muted">演示数据</span></div>
          <div class="ctx-row"><span class="k">文件数</span><span class="v">10</span></div>
          <div class="ctx-row"><span class="k">成功 / 失败</span><span class="v">9 / 1</span></div>
          <div class="mini-bar"><i style="width: 90%"></i></div>
        </div>
      </div>

      <div class="ctx-card">
        <div class="ctx-head">⚡ 快捷操作</div>
        <div class="ctx-body quick">
          <button :disabled="drafting" @click="onChip('match')">🎯 智能匹配</button>
          <button :disabled="drafting" @click="onChip('interview')">💬 生成面试题</button>
          <button :disabled="drafting" @click="onChip('advance')">➡️ 推进状态</button>
        </div>
      </div>

      <div class="ctx-card">
        <div class="ctx-head">📊 今日</div>
        <div class="ctx-body">
          <div class="ctx-row"><span class="k">职位总数</span><span class="v">{{ todayStats.jobs }}</span></div>
          <div class="ctx-row"><span class="k">招聘中</span><span class="v">{{ todayStats.published }}</span></div>
          <div class="ctx-row">
            <span class="k">后端</span>
            <span class="v" :style="{ color: healthOk ? 'var(--success)' : 'var(--danger)' }">
              {{ healthOk === null ? '检测中' : healthOk ? '正常' : '异常' }}
            </span>
          </div>
        </div>
      </div>
    </aside>
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
  color: var(--faint);
  cursor: not-allowed;
}
.session {
  padding: 9px 10px;
  border-radius: 9px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: 0.15s;
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
}
.session .s {
  font-size: 11.5px;
  color: var(--faint);
  margin-top: 2px;
}
.pill-live {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  flex: 0 0 auto;
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
.demo-tag {
  background: var(--warn-soft);
  color: var(--warn);
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
.btn-replay:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.chat-stream {
  flex: 1;
  overflow-y: auto;
  padding: 20px 22px 10px;
  display: flex;
  flex-direction: column;
  gap: 14px;
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
.text :deep(b.warn) {
  color: var(--warn);
}
.sub-note {
  color: var(--faint);
  font-size: 12px;
  margin-top: 4px;
}
.done-card {
  margin-top: 9px;
  background: #fafbfe;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--text);
}
.pill {
  background: #f1f2f8;
  color: var(--muted);
  border-radius: 20px;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 600;
}

/* 卡片 */
.card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 11px;
  overflow: hidden;
  margin-top: 9px;
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
.upload-zone:hover {
  border-color: var(--primary);
  background: #f6f7ff;
}
.upload-zone .big {
  font-size: 22px;
}
.upload-zone .hint {
  font-size: 12px;
  color: var(--faint);
  margin-top: 5px;
}

/* 进度 */
.progress {
  height: 7px;
  background: #edeff6;
  border-radius: 6px;
  overflow: hidden;
  margin: 4px 0 6px;
}
.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  transition: width 0.2s;
}
.progress-text {
  font-size: 11.5px;
  color: var(--faint);
  text-align: right;
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
.warn {
  color: var(--warn);
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
}
.q-look {
  font-size: 11px;
  color: var(--faint);
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
}
.arrow {
  color: var(--faint);
}
.warn-text {
  font-size: 12px;
  color: #92400e;
  background: var(--warn-soft);
  border-radius: 7px;
  padding: 7px 10px;
}
.ok-text {
  color: var(--success);
  font-weight: 600;
  font-size: 13px;
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
  text-decoration: none;
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
