<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import client from '@/api/client'
import { listJobs } from '@/api/jobs'
import type { Job } from '@/api/jobs'
import { useAuthStore } from '@/stores/auth'

interface ComponentStatus {
  ok: boolean
  detail: string
  backend: string
}

interface HealthResponse {
  status: string
  app: string
  version: string
  env: string
  components: {
    database: ComponentStatus
    storage: ComponentStatus
  }
}

const auth = useAuthStore()

// ---------------------------------------------------------------- 概览数据
const stats = ref({ total: 0, published: 0, draft: 0, closed: 0 })
const recent = ref<Job[]>([])
const statsLoading = ref(true)

async function loadOverview() {
  statsLoading.value = true
  try {
    const [all, published, draft, closed] = await Promise.all([
      listJobs({ page: 1, page_size: 5 }),
      listJobs({ status: 'published', page: 1, page_size: 1 }),
      listJobs({ status: 'draft', page: 1, page_size: 1 }),
      listJobs({ status: 'closed', page: 1, page_size: 1 }),
    ])
    recent.value = all.items
    stats.value = {
      total: all.total,
      published: published.total,
      draft: draft.total,
      closed: closed.total,
    }
  } catch {
    // 后端未启动时保持空态，不在首页打断用户
  } finally {
    statsLoading.value = false
  }
}

const kpis = computed(() => [
  { label: '职位总数', value: stats.value.total, hint: '全部状态', tone: 'indigo' },
  { label: '招聘中', value: stats.value.published, hint: '对外可见', tone: 'emerald' },
  { label: '草稿', value: stats.value.draft, hint: '待完善后发布', tone: 'amber' },
  { label: '已关闭', value: stats.value.closed, hint: '可归档留档', tone: 'violet' },
])

const STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  pending: '待审批',
  published: '招聘中',
  closed: '已关闭',
  archived: '已归档',
}

function statusText(status: string): string {
  return STATUS_TEXT[status] || status
}

const hour = new Date().getHours()
const greeting = hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
const dateText = new Intl.DateTimeFormat('zh-CN', {
  month: 'long',
  day: 'numeric',
  weekday: 'long',
}).format(new Date())

// ---------------------------------------------------------------- 系统状态
const health = ref<HealthResponse | null>(null)
const healthError = ref('')
const healthLoading = ref(true)

async function fetchHealth() {
  healthLoading.value = true
  healthError.value = ''
  try {
    const { data } = await client.get<HealthResponse>('/healthz')
    health.value = data
  } catch (e: any) {
    healthError.value = e?.message ?? '无法连接后端'
  } finally {
    healthLoading.value = false
  }
}

onMounted(() => {
  void loadOverview()
  void fetchHealth()
})
</script>

<template>
  <div class="home">
    <header class="hero">
      <div class="hero-copy">
        <div class="eyebrow">DASHBOARD · 招聘概览</div>
        <h1>{{ greeting }}，{{ auth.user?.name || '招聘伙伴' }}</h1>
        <p class="sub">
          {{ dateText }} · 目前 {{ stats.published }} 个职位在招，{{ stats.draft }} 个草稿待完善
        </p>
      </div>
      <div class="hero-actions">
        <RouterLink class="btn ghost" to="/jobs">查看职位</RouterLink>
        <RouterLink class="btn primary" to="/jobs?new=1">＋ 新建职位</RouterLink>
      </div>
    </header>

    <section class="kpis">
      <article v-for="item in kpis" :key="item.label" class="kpi" :class="item.tone">
        <div class="kpi-top">
          <span class="kpi-label">{{ item.label }}</span>
          <span class="kpi-dot"></span>
        </div>
        <div class="kpi-value">{{ statsLoading ? '—' : item.value }}</div>
        <div class="kpi-hint">{{ item.hint }}</div>
      </article>
    </section>

    <section class="cols">
      <div class="card">
        <div class="card-head">
          <span>最近职位</span>
          <RouterLink class="link" to="/jobs">全部 →</RouterLink>
        </div>

        <div v-if="statsLoading" class="state">加载中…</div>
        <div v-else-if="!recent.length" class="state">
          还没有职位，<RouterLink class="link" to="/jobs?new=1">创建第一个</RouterLink>
        </div>
        <div v-else class="job-list">
          <RouterLink v-for="job in recent" :key="job.id" class="job-row" to="/jobs">
            <span class="job-main">
              <span class="job-title">{{ job.title }}</span>
              <span class="job-meta">
                {{ job.department || '未填部门' }} · {{ job.location || '地点待定' }} ·
                {{ job.skills.length }} 项技能
              </span>
            </span>
            <span class="job-side">
              <span class="status" :class="job.status">{{ statusText(job.status) }}</span>
              <span class="arrow">→</span>
            </span>
          </RouterLink>
        </div>
      </div>

      <div class="side">
        <div class="card">
          <div class="card-head">
            <span>系统状态</span>
            <button class="mini" @click="fetchHealth">刷新</button>
          </div>
          <p v-if="healthLoading" class="state">检测中…</p>
          <p v-else-if="healthError" class="state err">连接失败：{{ healthError }}</p>
          <div v-else-if="health" class="health-rows">
            <div class="h-row">
              <span>数据库 · {{ health.components.database.backend }}</span>
              <span class="pill" :class="health.components.database.ok ? 'ok' : 'bad'">
                {{ health.components.database.ok ? '正常' : '异常' }}
              </span>
            </div>
            <div class="h-row">
              <span>对象存储 · {{ health.components.storage.backend }}</span>
              <span class="pill" :class="health.components.storage.ok ? 'ok' : 'bad'">
                {{ health.components.storage.ok ? '正常' : '异常' }}
              </span>
            </div>
            <div class="h-row">
              <span>版本 / 环境</span>
              <span class="mono">{{ health.version }} · {{ health.env }}</span>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><span>快捷操作</span></div>
          <div class="quick-actions">
            <RouterLink class="quick-item" to="/jobs?new=1">
              <span class="qi-icon">＋</span>
              <span class="qi-text"><strong>新建职位</strong><small>填 JD 后发布</small></span>
            </RouterLink>
            <RouterLink class="quick-item" to="/jobs">
              <span class="qi-icon">≡</span>
              <span class="qi-text"><strong>职位管理</strong><small>筛选与状态流转</small></span>
            </RouterLink>
          </div>
        </div>
      </div>
    </section>

    <footer class="phase">
      <span class="phase-dot"></span>
      当前进度：阶段三 · 职位管理已完成，下一步「简历上传与解析」
    </footer>
  </div>
</template>

<style scoped>
.home {
  max-width: 1240px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* Hero */
.hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding: 6px 2px 2px;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--faint);
  font-weight: 650;
  margin-bottom: 6px;
}
.hero h1 {
  margin: 0 0 6px;
  font-size: 26px;
  font-weight: 750;
}
.sub {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
.hero-actions {
  display: flex;
  gap: 10px;
}
.btn {
  display: inline-flex;
  align-items: center;
  height: 38px;
  padding: 0 17px;
  border-radius: 10px;
  font-size: 13.5px;
  font-weight: 600;
  text-decoration: none;
  transition: 0.16s;
}
.btn.ghost {
  background: #fff;
  color: var(--text);
  border: 1px solid var(--line-strong);
}
.btn.ghost:hover {
  box-shadow: var(--shadow-sm);
  border-color: #c9cffa;
}
.btn.primary {
  color: #fff;
  background: linear-gradient(135deg, #5b54ee, #7c5cf0);
  box-shadow: 0 8px 18px -12px rgba(79, 70, 229, 0.8);
}
.btn.primary:hover {
  background: linear-gradient(135deg, #4f46e5, #6d3ee8);
  transform: translateY(-1px);
}

/* KPI */
.kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
.kpi {
  position: relative;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px 14px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.18s, transform 0.18s;
}
.kpi:hover {
  box-shadow: var(--shadow);
  transform: translateY(-1px);
}
.kpi::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: linear-gradient(90deg, #6366f1, #a78bfa);
}
.kpi.emerald::before {
  background: linear-gradient(90deg, #10b981, #6ee7b7);
}
.kpi.amber::before {
  background: linear-gradient(90deg, #f59e0b, #fcd34d);
}
.kpi.violet::before {
  background: linear-gradient(90deg, #8b5cf6, #c4b5fd);
}
.kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.kpi-label {
  font-size: 11.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 650;
}
.kpi-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #6366f1;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
}
.kpi.emerald .kpi-dot {
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.12);
}
.kpi.amber .kpi-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12);
}
.kpi.violet .kpi-dot {
  background: #8b5cf6;
  box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.12);
}
.kpi-value {
  margin-top: 8px;
  font-size: 30px;
  font-weight: 750;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.kpi-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--faint);
}

/* 两栏 */
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 18px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, #fbfcff, #f7f8fd);
  font-size: 13px;
  font-weight: 700;
}
.link {
  font-size: 12.5px;
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}
.link:hover {
  text-decoration: underline;
}
.state {
  padding: 22px 18px;
  color: var(--muted);
  font-size: 13px;
  margin: 0;
}
.state.err {
  color: var(--danger);
}

/* 最近职位 */
.job-list {
  display: flex;
  flex-direction: column;
}
.job-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 18px;
  text-decoration: none;
  color: inherit;
  border-bottom: 1px solid #f2f3f8;
  transition: background 0.14s;
}
.job-row:last-child {
  border-bottom: none;
}
.job-row:hover {
  background: #fafbff;
}
.job-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.job-title {
  font-size: 13.5px;
  font-weight: 650;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.job-meta {
  font-size: 12px;
  color: var(--muted);
}
.job-side {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}
.status {
  font-size: 11.5px;
  padding: 3px 9px;
  border-radius: 7px;
  background: #f2f4f7;
  color: #475467;
  border: 1px solid transparent;
}
.status.published {
  background: var(--success-soft);
  color: var(--success);
  border-color: rgba(5, 150, 105, 0.16);
}
.status.draft {
  background: #f2f4f7;
  color: #475467;
}
.status.pending {
  background: var(--warn-soft);
  color: var(--warn);
  border-color: rgba(180, 83, 9, 0.16);
}
.status.closed {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: rgba(220, 38, 38, 0.14);
}
.status.archived {
  background: #f7f8fa;
  color: var(--faint);
}
.arrow {
  color: var(--faint);
  font-size: 13px;
}

/* 右栏 */
.side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.health-rows {
  padding: 6px 18px 14px;
}
.h-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  font-size: 12.5px;
  color: var(--muted);
  border-bottom: 1px dashed #eef0f5;
}
.h-row:last-child {
  border-bottom: none;
}
.pill {
  font-size: 11.5px;
  padding: 2px 9px;
  border-radius: 20px;
  background: #f2f4f7;
  color: #475467;
}
.pill.ok {
  background: var(--success-soft);
  color: var(--success);
}
.pill.bad {
  background: var(--danger-soft);
  color: var(--danger);
}
.mono {
  font-variant-numeric: tabular-nums;
  color: var(--text);
  font-weight: 550;
  margin-left: 10px;
}
.mini {
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 7px;
  padding: 3px 9px;
  font-size: 11.5px;
  color: var(--muted);
  cursor: pointer;
}
.mini:hover {
  border-color: #c9cffa;
  color: var(--primary);
}

.quick-actions {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.quick-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  text-decoration: none;
  color: inherit;
  transition: 0.16s;
}
.quick-item:hover {
  border-color: #c9cffa;
  background: #fafbff;
  box-shadow: 0 6px 16px -14px rgba(79, 70, 229, 0.8);
}
.qi-icon {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 700;
}
.qi-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.qi-text strong {
  font-size: 13px;
}
.qi-text small {
  font-size: 11.5px;
  color: var(--muted);
}

.phase {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: linear-gradient(180deg, #fafbff, #f5f7ff);
  border: 1px solid #e7eaf9;
  border-radius: 11px;
  font-size: 12.5px;
  color: #5b6478;
}
.phase-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.12);
}

@media (max-width: 1100px) {
  .kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .cols {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
  }
  .kpis {
    grid-template-columns: 1fr;
  }
}
</style>
