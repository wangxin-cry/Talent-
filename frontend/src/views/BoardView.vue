<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import * as appApi from '@/api/applications'
import * as jobApi from '@/api/jobs'
import * as candidateApi from '@/api/candidates'
import type { ApplicationCard, ApplicationDetail, BoardColumn, TimelineItem } from '@/api/applications'
import type { Candidate } from '@/api/candidates'
import type { Job } from '@/api/jobs'

const router = useRouter()

const jobs = ref<Job[]>([])
const selectedJobId = ref<number | null>(null)
const columns = ref<BoardColumn[]>([])
const jobTitle = ref('')
const loading = ref(false)
const moving = ref(false)

// ---------------- 拖拽 ----------------
const dragId = ref<number | null>(null)
const dragFrom = ref<string | null>(null)
const dragOver = ref<string | null>(null)

// ---------------- 详情抽屉 ----------------
const drawer = ref(false)
const detail = ref<ApplicationDetail | null>(null)
const timeline = ref<TimelineItem[]>([])
const detailLoading = ref(false)

// ---------------- 添加候选人 ----------------
const addDialog = ref(false)
const candidates = ref<Candidate[]>([])
const candidateLoading = ref(false)
const candidateKeyword = ref('')
const pickedCandidateId = ref<number | null>(null)

const STATUS_COLORS: Record<string, string> = {
  new: '#64748b',
  screening: '#0ea5e9',
  interview: '#6366f1',
  offer: '#d97706',
  hired: '#16a34a',
  rejected: '#dc2626',
}

const STATUS_LABELS: Record<string, string> = {
  new: '新申请',
  screening: '筛选中',
  interview: '面试中',
  offer: 'Offer',
  hired: '已入职',
  rejected: '已淘汰',
}

function statusLabel(value: string): string {
  return STATUS_LABELS[value] || value
}

function statusColor(value: string): string {
  return STATUS_COLORS[value] || '#64748b'
}

function scoreColor(score: number): string {
  if (score >= 80) return '#16a34a'
  if (score >= 60) return '#2563eb'
  if (score >= 40) return '#d97706'
  return '#dc2626'
}

function formatTime(value?: string | null): string {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return ''
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} 分钟`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} 小时`
  return `${(seconds / 86400).toFixed(1)} 天`
}

const totalCards = computed(() => columns.value.reduce((sum, col) => sum + col.items.length, 0))

async function loadJobs() {
  try {
    const data = await jobApi.listJobs({ page_size: 100 })
    jobs.value = data.items
    if (jobs.value.length) selectedJobId.value = jobs.value[0].id
  } catch (e: any) {
    ElMessage.error(e.message || '加载职位失败')
  }
}

async function loadBoard() {
  if (!selectedJobId.value) return
  loading.value = true
  try {
    const data = await appApi.listBoard(selectedJobId.value)
    columns.value = data.columns
    jobTitle.value = data.job_title
  } catch (e: any) {
    ElMessage.error(e.message || '加载看板失败')
  } finally {
    loading.value = false
  }
}

function findCard(id: number): ApplicationCard | undefined {
  for (const column of columns.value) {
    const hit = column.items.find((item) => item.id === id)
    if (hit) return hit
  }
  return undefined
}

function onDragStart(card: ApplicationCard) {
  dragId.value = card.id
  dragFrom.value = card.status
}

function onDragEnd() {
  dragId.value = null
  dragFrom.value = null
  dragOver.value = null
}

function onDragOver(status: string) {
  if (dragFrom.value && status !== dragFrom.value) dragOver.value = status
}

async function onDrop(target: string) {
  dragOver.value = null
  const id = dragId.value
  const card = id ? findCard(id) : undefined
  onDragEnd()
  if (!card || card.status === target) return
  await changeStatus(card, target)
}

async function changeStatus(card: ApplicationCard, target: string) {
  if (!card.allowed_next.includes(target)) {
    ElMessage.error(
      `${card.status_label} 不能直接转为「${statusLabel(target)}」，请按流程逐步推进`,
    )
    return
  }

  let note: string | undefined
  if (target === 'rejected') {
    const result: any = await ElMessageBox.prompt('请填写淘汰原因（必填）', '淘汰候选人', {
      confirmButtonText: '确认淘汰',
      cancelButtonText: '取消',
      inputValidator: (value: string) => (value && value.trim() ? true : '淘汰原因不能为空'),
    }).catch(() => null)
    if (!result) return
    note = String(result.value || '').trim()
  }

  moving.value = true
  try {
    const updated = await appApi.transition(card.id, { to_status: target, note })
    ElMessage.success(`已流转到「${updated.status_label}」`)
    await loadBoard()
    if (drawer.value && detail.value?.id === card.id) {
      await openDetail(card.id)
    }
  } catch (e: any) {
    ElMessage.error(e.message || '状态流转失败')
  } finally {
    moving.value = false
  }
}

async function openDetail(id: number) {
  drawer.value = true
  detailLoading.value = true
  try {
    const [data, line] = await Promise.all([appApi.getApplication(id), appApi.getTimeline(id)])
    detail.value = data
    timeline.value = line.items
  } catch (e: any) {
    ElMessage.error(e.message || '加载详情失败')
  } finally {
    detailLoading.value = false
  }
}

function openPrep(id?: number) {
  const target = id ?? detail.value?.id
  if (!target) return
  router.push(`/applications/${target}/prep`)
}

function advanceCurrent(next: string) {
  if (detail.value) void changeStatus(detail.value, next)
}

async function openAddDialog() {
  addDialog.value = true
  pickedCandidateId.value = null
  candidateKeyword.value = ''
  await searchCandidates()
}

async function searchCandidates() {
  candidateLoading.value = true
  try {
    const data = await candidateApi.listCandidates({
      q: candidateKeyword.value || undefined,
      page_size: 50,
    })
    candidates.value = data.items
  } catch (e: any) {
    ElMessage.error(e.message || '加载候选人失败')
  } finally {
    candidateLoading.value = false
  }
}

async function addCandidate() {
  if (!selectedJobId.value || !pickedCandidateId.value) return
  try {
    await appApi.createApplication({
      job_id: selectedJobId.value,
      candidate_id: pickedCandidateId.value,
      source: 'manual',
    })
    ElMessage.success('已加入招聘流程')
    addDialog.value = false
    await loadBoard()
  } catch (e: any) {
    ElMessage.error(e.message || '加入流程失败')
  }
}

watch(selectedJobId, (id) => {
  if (id) loadBoard()
})

onMounted(loadJobs)
</script>

<template>
  <div class="board-page">
    <div class="page-header">
      <div>
        <h2>招聘流程看板</h2>
        <p class="subtitle">拖动卡片推进阶段；非法跳转会被状态机拒绝，每次流转都写入时间线并触发站内通知</p>
      </div>
      <div class="header-actions">
        <el-select v-model="selectedJobId" placeholder="选择职位" style="width: 280px">
          <el-option
            v-for="job in jobs"
            :key="job.id"
            :label="`${job.title}（${job.department || '未分配'}）`"
            :value="job.id"
          />
        </el-select>
        <el-button type="primary" @click="openAddDialog">添加候选人</el-button>
        <el-button @click="loadBoard">刷新</el-button>
      </div>
    </div>

    <div v-if="jobTitle" class="job-info">
      当前职位：<strong>{{ jobTitle }}</strong>
      <span class="count">共 {{ totalCards }} 人</span>
      <span v-if="moving" class="count">流转中…</span>
    </div>

    <div v-loading="loading" class="board">
      <section
        v-for="column in columns"
        :key="column.status"
        class="column"
        :class="{ 'is-over': dragOver === column.status }"
        @dragover.prevent="onDragOver(column.status)"
        @dragleave="dragOver = null"
        @drop.prevent="onDrop(column.status)"
      >
        <header class="column-head">
          <span class="dot" :style="{ background: statusColor(column.status) }"></span>
          <span class="column-title">{{ column.label }}</span>
          <span class="column-count">{{ column.items.length }}</span>
        </header>

        <div class="column-body">
          <article
            v-for="card in column.items"
            :key="card.id"
            class="card"
            :class="{ dragging: dragId === card.id }"
            draggable="true"
            @dragstart="onDragStart(card)"
            @dragend="onDragEnd"
            @click="openDetail(card.id)"
          >
            <div class="card-top">
              <span class="name">{{ card.candidate_name || `候选人 #${card.candidate_id}` }}</span>
              <span
                v-if="card.match_score !== null"
                class="score"
                :style="{ color: scoreColor(card.match_score) }"
              >{{ card.match_score.toFixed(0) }}</span>
            </div>
            <div class="card-sub">
              {{ card.candidate_title || '未填写当前职位' }}
              <span v-if="card.years_experience !== null"> · {{ card.years_experience }} 年</span>
            </div>
            <div class="card-foot">
              <span class="days">停留 {{ card.days_in_stage }} 天</span>
              <span class="prep" @click.stop="openPrep(card.id)">面试准备</span>
            </div>
          </article>

          <div v-if="!column.items.length" class="empty-slot">暂无候选人</div>
        </div>
      </section>
    </div>

    <el-empty
      v-if="!loading && !columns.length"
      description="请选择职位查看流程看板"
    />

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawer" :title="detail?.candidate_name || '应聘详情'" size="520px">
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <div class="detail-head">
            <el-tag
              effect="dark"
              :style="{ background: statusColor(detail.status), borderColor: statusColor(detail.status) }"
            >{{ detail.status_label }}</el-tag>
            <span v-if="detail.match_score !== null" class="detail-score">
              匹配分 <strong :style="{ color: scoreColor(detail.match_score) }">{{ detail.match_score.toFixed(1) }}</strong>
            </span>
            <span class="detail-days">本阶段停留 {{ detail.days_in_stage }} 天</span>
          </div>

          <dl class="info-grid">
            <div><dt>应聘职位</dt><dd>{{ detail.job_title || '-' }}</dd></div>
            <div><dt>当前公司</dt><dd>{{ detail.candidate_company || '-' }}</dd></div>
            <div><dt>当前职位</dt><dd>{{ detail.candidate_title || '-' }}</dd></div>
            <div><dt>工作年限</dt><dd>{{ detail.years_experience !== null ? `${detail.years_experience} 年` : '-' }}</dd></div>
            <div><dt>学历</dt><dd>{{ detail.candidate_education || '-' }}</dd></div>
            <div><dt>城市</dt><dd>{{ detail.candidate_city || '-' }}</dd></div>
          </dl>

          <div v-if="detail.candidate_skills.length" class="block">
            <div class="block-title">技能</div>
            <el-tag
              v-for="skill in detail.candidate_skills"
              :key="skill"
              size="small"
              class="skill-tag"
            >{{ skill }}</el-tag>
          </div>

          <div v-if="detail.match" class="block gap-block">
            <div class="block-title">匹配缺口</div>
            <p class="gap-summary">{{ detail.match.summary }}</p>
            <div class="gap-row">
              <span class="gap-label ok">命中必备</span>
              <span>{{ detail.match.matched_must.join('、') || '无' }}</span>
            </div>
            <div class="gap-row">
              <span class="gap-label miss">缺失必备</span>
              <span>{{ detail.match.missing_must.join('、') || '无' }}</span>
            </div>
            <div class="gap-row">
              <span class="gap-label">年限差</span>
              <span v-if="detail.match.years_gap !== null">
                {{ detail.match.years_gap >= 0 ? `超 ${detail.match.years_gap} 年` : `差 ${Math.abs(detail.match.years_gap)} 年` }}
              </span>
              <span v-else>信息不足</span>
            </div>
          </div>

          <div v-if="detail.rejected_reason" class="block">
            <div class="block-title">淘汰原因</div>
            <p class="reject-reason">{{ detail.rejected_reason }}</p>
          </div>

          <div class="block">
            <div class="block-title">流转操作</div>
            <div class="actions">
              <el-button
                v-for="next in detail.allowed_next.filter((s) => s !== 'rejected')"
                :key="next"
                type="primary"
                plain
                size="small"
                :loading="moving"
                @click="advanceCurrent(next)"
              >推进到 {{ statusLabel(next) }}</el-button>
              <el-button
                v-if="detail.allowed_next.includes('rejected')"
                type="danger"
                plain
                size="small"
                :loading="moving"
                @click="advanceCurrent('rejected')"
              >淘汰</el-button>
              <span v-if="!detail.allowed_next.length" class="muted">终态，不可再流转</span>
            </div>
          </div>

          <div class="block">
            <div class="block-title">流转时间线</div>
            <el-timeline v-if="timeline.length">
              <el-timeline-item
                v-for="item in timeline"
                :key="item.id"
                :timestamp="formatTime(item.create_time)"
                placement="top"
                :color="statusColor(item.to_status)"
              >
                <div class="timeline-title">
                  {{ item.from_label ? `${item.from_label} → ${item.to_label}` : `进入${item.to_label}` }}
                </div>
                <div class="timeline-meta">
                  操作人：{{ item.operator_name || '-' }}
                  <span v-if="item.duration_in_prev_status !== null">
                    · 上一阶段停留 {{ formatDuration(item.duration_in_prev_status) }}
                  </span>
                </div>
                <div v-if="item.note" class="timeline-note">备注：{{ item.note }}</div>
              </el-timeline-item>
            </el-timeline>
            <span v-else class="muted">暂无记录</span>
          </div>
        </template>
      </div>

      <template #footer>
        <el-button @click="drawer = false">关闭</el-button>
        <el-button type="primary" @click="openPrep()">打开面试准备页</el-button>
      </template>
    </el-drawer>

    <!-- 添加候选人 -->
    <el-dialog v-model="addDialog" title="把候选人加入流程" width="520px">
      <div class="dialog-search">
        <el-input
          v-model="candidateKeyword"
          placeholder="搜索姓名"
          clearable
          @keyup.enter="searchCandidates"
          @clear="searchCandidates"
        />
        <el-button @click="searchCandidates">搜索</el-button>
      </div>
      <el-select
        v-model="pickedCandidateId"
        v-loading="candidateLoading"
        filterable
        placeholder="选择候选人"
        style="width: 100%"
      >
        <el-option
          v-for="candidate in candidates"
          :key="candidate.id"
          :label="`${candidate.name || '未命名'}${candidate.current_title ? ' · ' + candidate.current_title : ''}`"
          :value="candidate.id"
        />
      </el-select>
      <template #footer>
        <el-button @click="addDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!pickedCandidateId" @click="addCandidate">
          加入流程
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.board-page {
  max-width: 100%;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.job-info {
  margin: 14px 0 12px;
  font-size: 14px;
}
.job-info .count {
  margin-left: 12px;
  color: var(--muted);
  font-size: 13px;
}
.board {
  display: grid;
  grid-template-columns: repeat(6, minmax(210px, 1fr));
  gap: 14px;
  align-items: start;
  overflow-x: auto;
  padding-bottom: 8px;
}
.column {
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  min-height: 260px;
  transition: border-color 0.16s, box-shadow 0.16s, background 0.16s;
}
.column.is-over {
  border-color: #b9bdf3;
  background: #f7f8ff;
  box-shadow: var(--ring);
}
.column-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.column-title {
  font-size: 13.5px;
  font-weight: 650;
}
.column-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--muted);
  background: #f1f2f8;
  border-radius: 10px;
  padding: 1px 8px;
}
.column-body {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-height: 200px;
}
.card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 11px;
  padding: 10px 12px;
  cursor: grab;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.16s, transform 0.12s, border-color 0.16s;
}
.card:hover {
  box-shadow: var(--shadow);
  border-color: #d9dcf9;
  transform: translateY(-1px);
}
.card.dragging {
  opacity: 0.45;
}
.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.name {
  font-size: 13.5px;
  font-weight: 650;
}
.score {
  font-size: 15px;
  font-weight: 700;
}
.card-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted);
}
.card-foot {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--faint);
}
.prep {
  color: var(--primary);
  font-weight: 600;
  cursor: pointer;
}
.prep:hover {
  text-decoration: underline;
}
.empty-slot {
  display: grid;
  place-items: center;
  height: 90px;
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  color: var(--faint);
  font-size: 12.5px;
}
.drawer-body {
  min-height: 200px;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.detail-score,
.detail-days {
  font-size: 13px;
  color: var(--muted);
}
.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 18px;
  margin: 0 0 16px;
}
.info-grid dt {
  font-size: 12px;
  color: var(--muted);
}
.info-grid dd {
  margin: 2px 0 0;
  font-size: 13.5px;
  font-weight: 550;
}
.block {
  margin-bottom: 18px;
}
.block-title {
  font-size: 13px;
  font-weight: 650;
  margin-bottom: 8px;
}
.skill-tag {
  margin: 0 6px 6px 0;
}
.gap-block {
  background: #fafbff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
}
.gap-summary {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text);
}
.gap-row {
  display: flex;
  gap: 10px;
  font-size: 13px;
  margin-top: 5px;
}
.gap-label {
  flex: 0 0 64px;
  color: var(--muted);
  font-size: 12.5px;
}
.gap-label.ok {
  color: #16a34a;
}
.gap-label.miss {
  color: #dc2626;
}
.reject-reason {
  margin: 0;
  font-size: 13px;
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 8px;
  padding: 8px 10px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.timeline-title {
  font-size: 13px;
  font-weight: 600;
}
.timeline-meta {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}
.timeline-note {
  font-size: 12px;
  color: var(--warn);
  margin-top: 2px;
}
.muted {
  color: var(--muted);
  font-size: 13px;
}
.dialog-search {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
@media (max-width: 1100px) {
  .board {
    grid-template-columns: repeat(6, 220px);
  }
}
</style>
