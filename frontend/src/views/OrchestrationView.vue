<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import * as jobApi from '@/api/jobs'
import * as orchApi from '@/api/orchestration'
import type {
  IntentItem,
  OrchestrationRun,
  OrchestrationStep,
  TraceSummary,
} from '@/api/orchestration'
import type { Job } from '@/api/jobs'

const jobs = ref<Job[]>([])
const selectedJobId = ref<number | null>(null)
const useLlm = ref(false)
const loading = ref(false)
const data = ref<OrchestrationRun | null>(null)
const intents = ref<IntentItem[]>([])
const traces = ref<TraceSummary[]>([])
const applicationId = ref<number | null>(null)
const toStatus = ref('screening')

const ranking = computed<any[]>(() => data.value?.result?.ranking || [])
const evaluations = computed<any[]>(() => data.value?.result?.evaluations || [])
const resumeBatch = computed<any | null>(() => {
  const result = data.value?.result || {}
  return data.value?.intent === 'resume_upload' ? result : null
})
const insights = computed<string[]>(() => data.value?.result?.insights || [])
const advanceResult = computed<any | null>(() => {
  return data.value?.intent === 'advance_status' ? data.value?.result : null
})
const genericResult = computed(() => {
  const intent = data.value?.intent
  if (!intent) return null
  if (['full_eval', 'match', 'interview', 'resume_upload', 'advance_status', 'analytics'].includes(intent)) {
    return null
  }
  return data.value?.result || null
})

const STATUS_OPTIONS = [
  { value: 'screening', label: '筛选中' },
  { value: 'interview', label: '面试中' },
  { value: 'offer', label: 'Offer' },
  { value: 'hired', label: '已入职' },
  { value: 'rejected', label: '已淘汰' },
]

async function loadJobs() {
  try {
    const result = await jobApi.listJobs({ page_size: 100 })
    jobs.value = result.items
    if (jobs.value.length) selectedJobId.value = jobs.value[0].id
  } catch (e: any) {
    ElMessage.error(e.message || '加载职位失败')
  }
}

async function loadIntents() {
  try {
    intents.value = await orchApi.listIntents()
  } catch {
    // 映射表加载失败不影响主流程
  }
}

async function loadTraces() {
  try {
    traces.value = await orchApi.listTraces(10)
  } catch {
    // 轨迹列表失败不影响主流程
  }
}

async function run(intent: string, extra: Record<string, any> = {}) {
  const needsJob = ['full_eval', 'match'].includes(intent)
  if (needsJob && !selectedJobId.value) {
    ElMessage.warning('请先选择职位')
    return
  }
  if (intent === 'advance_status' && !applicationId.value) {
    ElMessage.warning('请填写应聘记录 id')
    return
  }

  loading.value = true
  try {
    data.value = await orchApi.runOrchestration({
      intent,
      job_id: needsJob ? selectedJobId.value : null,
      use_llm: useLlm.value,
      ...extra,
    })
    if (data.value.degraded) {
      ElMessage.warning(`编排完成（有降级）：${data.value.intent_label}`)
    } else {
      ElMessage.success(`编排完成：${data.value.intent_label}`)
    }
    void loadTraces()
  } catch (e: any) {
    ElMessage.error(e.message || '编排失败')
  } finally {
    loading.value = false
  }
}

function runFullEval() {
  void run('full_eval', { top_n: 3 })
}

function runMatch() {
  void run('match', { top_n: 5 })
}

function runResumeBatch() {
  void run('resume_upload', { limit: 20 })
}

function runAnalytics() {
  void run('analytics')
}

function runAdvance() {
  void run('advance_status', {
    application_id: applicationId.value,
    to_status: toStatus.value,
  })
}

async function viewTrace(traceId: string) {
  try {
    const detail = await orchApi.getTrace(traceId)
    data.value = {
      trace_id: detail.trace_id,
      intent: detail.intent || '',
      intent_label: '历史轨迹',
      status: detail.status,
      degraded: detail.degraded,
      duration_ms: detail.duration_ms,
      total_tokens: detail.total_tokens,
      total_cost: detail.total_cost,
      plan: [],
      steps: detail.steps,
      result: {},
    }
  } catch (e: any) {
    ElMessage.error(e.message || '加载轨迹失败')
  }
}

function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'success') return 'success'
  if (value === 'degraded') return 'warning'
  if (value === 'timeout' || value === 'failed') return 'danger'
  return 'info'
}

function statusLabel(value: string): string {
  const map: Record<string, string> = {
    success: '成功',
    degraded: '降级',
    timeout: '超时',
    failed: '失败',
    skipped: '跳过',
  }
  return map[value] || value
}

function stepRowClass({ row }: { row: OrchestrationStep }): string {
  return row.degraded ? 'row-degraded' : ''
}

function formatMs(value: number): string {
  if (!value) return '0ms'
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(2)}s`
}

function formatCost(value: number): string {
  return `¥${(value || 0).toFixed(6)}`
}

function formatValue(value: any): string {
  if (Array.isArray(value)) return value.slice(0, 3).join('/')
  if (value && typeof value === 'object') return JSON.stringify(value).slice(0, 60)
  return String(value)
}

function stepSummary(step: OrchestrationStep): string {
  if (step.error_reason) return step.error_reason
  const entries = Object.entries(step.output_summary || {})
  if (!entries.length) return ''
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}=${formatValue(value)}`)
    .join(' · ')
}

function formatTime(value: string): string {
  return (value || '').replace('T', ' ').slice(5, 19)
}

onMounted(() => {
  void loadJobs()
  void loadIntents()
  void loadTraces()
})
</script>

<template>
  <div class="orch-page">
    <header class="page-head">
      <div>
        <h1>多 Agent 编排</h1>
        <p>Supervisor 按意图拆解任务，子 Agent 依次执行；每一步的耗时、token 与降级都会写入轨迹。</p>
      </div>
      <div class="intent-chips">
        <span v-for="item in intents" :key="item.intent" class="chip" :title="item.description">
          {{ item.label }}
        </span>
      </div>
    </header>

    <section class="panel toolbar">
      <div class="field">
        <span class="label">职位</span>
        <el-select v-model="selectedJobId" placeholder="选择职位" style="width: 260px">
          <el-option v-for="job in jobs" :key="job.id" :label="job.title" :value="job.id" />
        </el-select>
      </div>
      <div class="field">
        <span class="label">LLM</span>
        <el-switch v-model="useLlm" active-text="允许调用" inactive-text="模板优先" />
      </div>
      <div class="actions">
        <el-button type="primary" :loading="loading" @click="runFullEval">一键评估 top3</el-button>
        <el-button :loading="loading" @click="runMatch">仅匹配</el-button>
        <el-button :loading="loading" @click="runResumeBatch">批量解析</el-button>
        <el-button :loading="loading" @click="runAnalytics">看板洞察</el-button>
      </div>
    </section>

    <section class="panel toolbar">
      <div class="field">
        <span class="label">推进状态</span>
        <el-input-number v-model="applicationId" :min="1" placeholder="应聘记录 id" controls-position="right" />
        <el-select v-model="toStatus" style="width: 140px">
          <el-option v-for="item in STATUS_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-button :loading="loading" @click="runAdvance">执行推进</el-button>
      </div>
      <span class="hint">推进状态由状态机校验，非法迁移返回 allowed=false 并标记降级。</span>
    </section>

    <template v-if="data">
      <section class="panel summary">
        <div class="summary-main">
          <el-tag :type="statusType(data.status)" effect="dark" size="large">
            {{ data.status === 'success' ? '编排成功' : '编排降级' }}
          </el-tag>
          <div class="summary-title">
            <strong>{{ data.intent_label }}</strong>
            <span class="trace-id">trace {{ data.trace_id.slice(0, 12) }}…</span>
          </div>
          <div class="summary-plan">
            <span v-for="(step, index) in data.plan" :key="step" class="plan-step">
              {{ step }}<span v-if="index < data.plan.length - 1"> → </span>
            </span>
          </div>
        </div>
        <div class="metrics">
          <div class="metric">
            <span class="metric-label">总耗时</span>
            <span class="metric-value">{{ formatMs(data.duration_ms) }}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Token</span>
            <span class="metric-value">{{ data.total_tokens }}</span>
          </div>
          <div class="metric">
            <span class="metric-label">总成本</span>
            <span class="metric-value">{{ formatCost(data.total_cost) }}</span>
          </div>
          <div class="metric">
            <span class="metric-label">步骤</span>
            <span class="metric-value">{{ data.steps.length }}</span>
          </div>
        </div>
      </section>

      <section v-if="ranking.length" class="panel">
        <h2>候选人排名</h2>
        <el-table :data="ranking" size="small" stripe>
          <el-table-column label="#" width="56">
            <template #default="{ $index }">{{ $index + 1 }}</template>
          </el-table-column>
          <el-table-column prop="candidate_name" label="候选人" min-width="120" />
          <el-table-column prop="score" label="分数" width="90">
            <template #default="{ row }">
              <strong :class="{ high: row.score >= 80 }">{{ Number(row.score).toFixed(1) }}</strong>
            </template>
          </el-table-column>
          <el-table-column label="命中技能" min-width="160">
            <template #default="{ row }">{{ (row.matched_skills || []).join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="缺失技能" min-width="160">
            <template #default="{ row }">{{ (row.missing_skills || []).join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column prop="summary" label="结论" min-width="220" show-overflow-tooltip />
        </el-table>
      </section>

      <section v-if="evaluations.length" class="panel">
        <h2>面试题（{{ evaluations.length }} 人）</h2>
        <div class="eval-grid">
          <el-card
            v-for="item in evaluations"
            :key="item.candidate_id"
            shadow="never"
            class="eval-card"
            :class="{ failed: item.status !== 'success' }"
          >
            <template #header>
              <div class="eval-head">
                <strong>{{ item.candidate_name || `候选人#${item.candidate_id}` }}</strong>
                <el-tag :type="item.status === 'success' ? 'success' : 'danger'" size="small">
                  {{ item.status === 'success' ? `${item.questions.length} 题` : statusLabel(item.status) }}
                </el-tag>
              </div>
            </template>
            <p v-if="item.status !== 'success'" class="eval-error">{{ item.error || '生成失败' }}</p>
            <ol v-else class="question-list">
              <li v-for="(question, index) in item.questions" :key="index">
                <div class="q-text">{{ question.question }}</div>
                <div v-if="question.reference" class="q-ref">依据：{{ question.reference }}</div>
                <div v-if="question.follow_up" class="q-follow">追问：{{ question.follow_up }}</div>
              </li>
            </ol>
          </el-card>
        </div>
      </section>

      <section v-if="advanceResult" class="panel">
        <h2>状态推进</h2>
        <el-alert
          :type="advanceResult.allowed ? 'success' : 'warning'"
          :closable="false"
          :title="advanceResult.allowed ? '状态已推进' : '状态迁移被拒绝'"
          :description="advanceResult.allowed
            ? `应聘记录 #${advanceResult.application_id}：${advanceResult.from_label} → ${advanceResult.to_label}`
            : advanceResult.reason"
        />
      </section>

      <section v-if="resumeBatch" class="panel">
        <h2>批量解析</h2>
        <div class="batch-stats">
          <span>共 {{ resumeBatch.total }} 份</span>
          <span class="ok">成功 {{ resumeBatch.success }}</span>
          <span class="bad">失败 {{ resumeBatch.failed }}</span>
        </div>
        <el-table v-if="resumeBatch.items?.length" :data="resumeBatch.items" size="small">
          <el-table-column prop="file_id" label="文件 id" width="100" />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column prop="candidate_id" label="候选人" width="100" />
          <el-table-column prop="error" label="失败原因" min-width="200" />
        </el-table>
      </section>

      <section v-if="insights.length" class="panel">
        <h2>看板洞察</h2>
        <ul class="insights">
          <li v-for="(item, index) in insights" :key="index">{{ item }}</li>
        </ul>
      </section>

      <section v-if="genericResult" class="panel">
        <h2>结果</h2>
        <pre class="result-json">{{ JSON.stringify(genericResult, null, 2) }}</pre>
      </section>

      <section class="panel">
        <h2>编排轨迹</h2>
        <el-table :data="data.steps" :row-class-name="stepRowClass" size="small">
          <el-table-column prop="step_no" label="#" width="50" />
          <el-table-column prop="agent" label="Agent" width="160" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">{{ formatMs(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column label="Token（入/出）" width="140">
            <template #default="{ row }">{{ row.tokens_in }} / {{ row.tokens_out }}</template>
          </el-table-column>
          <el-table-column label="成本" width="110">
            <template #default="{ row }">{{ formatCost(row.cost) }}</template>
          </el-table-column>
          <el-table-column label="降级" width="70">
            <template #default="{ row }">
              <span :class="row.degraded ? 'degraded-yes' : 'degraded-no'">
                {{ row.degraded ? '是' : '否' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="摘要" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">{{ stepSummary(row) || '—' }}</template>
          </el-table-column>
        </el-table>
      </section>
    </template>

    <section v-else class="panel empty">
      <p>选择职位后点「一键评估 top3」：一次点击返回排名、3 人面试题、完整轨迹与总成本。</p>
    </section>

    <section class="panel">
      <h2>最近编排</h2>
      <el-table v-if="traces.length" :data="traces" size="small" @row-click="(row: TraceSummary) => viewTrace(row.trace_id)">
        <el-table-column prop="trace_id" label="trace" min-width="180">
          <template #default="{ row }">{{ row.trace_id.slice(0, 12) }}…</template>
        </el-table-column>
        <el-table-column prop="intent" label="意图" width="150" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">{{ formatMs(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column prop="step_count" label="步骤" width="70" />
        <el-table-column label="成本" width="110">
          <template #default="{ row }">{{ formatCost(row.total_cost) }}</template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
        </el-table-column>
      </el-table>
      <p v-else class="hint">还没有编排记录。</p>
    </section>
  </div>
</template>

<style scoped>
.orch-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1280px;
  margin: 0 auto;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.page-head h1 {
  margin: 0 0 6px;
  font-size: 21px;
  color: var(--text);
}
.page-head p {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}
.intent-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 520px;
  justify-content: flex-end;
}
.chip {
  padding: 4px 10px;
  border-radius: 20px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  font-weight: 550;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: var(--shadow-sm);
}
.panel h2 {
  margin: 0 0 12px;
  font-size: 15px;
  color: var(--text);
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 18px;
}
.field {
  display: flex;
  align-items: center;
  gap: 10px;
}
.label {
  font-size: 12.5px;
  color: var(--muted);
  font-weight: 600;
}
.actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
.hint {
  font-size: 12px;
  color: var(--faint);
}
.summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}
.summary-main {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.summary-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.summary-title strong {
  font-size: 16px;
  color: var(--text);
}
.trace-id {
  font-size: 11.5px;
  color: var(--faint);
  font-family: ui-monospace, monospace;
}
.summary-plan {
  font-size: 12.5px;
  color: var(--muted);
}
.plan-step {
  color: var(--primary);
  font-weight: 550;
}
.metrics {
  display: flex;
  gap: 26px;
}
.metric {
  display: flex;
  flex-direction: column;
  gap: 3px;
  align-items: flex-end;
}
.metric-label {
  font-size: 11.5px;
  color: var(--faint);
}
.metric-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
}
.high {
  color: #16a34a;
}
.eval-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.eval-card {
  border-radius: 12px;
}
.eval-card.failed {
  border-color: #fecaca;
  background: #fffafa;
}
.eval-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.eval-error {
  margin: 0;
  color: var(--danger);
  font-size: 12.5px;
}
.question-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.q-text {
  font-size: 13px;
  color: var(--text);
  line-height: 1.55;
}
.q-ref,
.q-follow {
  margin-top: 3px;
  font-size: 11.5px;
  color: var(--muted);
}
.q-follow {
  color: var(--faint);
}
.batch-stats {
  display: flex;
  gap: 18px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--muted);
}
.batch-stats .ok {
  color: #16a34a;
}
.batch-stats .bad {
  color: var(--danger);
}
.insights {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--text);
}
.result-json {
  margin: 0;
  padding: 14px;
  background: #f8f9fd;
  border-radius: 10px;
  font-size: 12px;
  color: var(--muted);
  overflow: auto;
  max-height: 360px;
}
.empty {
  text-align: center;
  color: var(--muted);
  font-size: 13px;
}
.degraded-yes {
  color: var(--danger);
  font-weight: 600;
}
.degraded-no {
  color: var(--faint);
}
:deep(.row-degraded) {
  --el-table-tr-bg-color: #fff7f5;
}
</style>
