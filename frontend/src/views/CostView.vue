<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import * as analyticsApi from '@/api/analytics'
import * as jobApi from '@/api/jobs'
import type { AiCallItem, CostSummary } from '@/api/analytics'
import type { Job } from '@/api/jobs'

const summary = ref<CostSummary | null>(null)
const calls = ref<AiCallItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const jobs = ref<Job[]>([])
const filters = reactive({
  feature: '',
  jobId: undefined as number | undefined,
  status: '',
})

const FEATURE_OPTIONS = [
  { value: 'jd_generate', label: 'JD 生成' },
  { value: 'resume_parse', label: '简历解析' },
  { value: 'resume_ocr', label: '简历 OCR' },
  { value: 'match_explain', label: '匹配理由' },
  { value: 'interview_generate', label: '面试题生成' },
]

const FEATURE_LABELS: Record<string, string> = Object.fromEntries(
  FEATURE_OPTIONS.map((item) => [item.value, item.label]),
)

const STATUS_LABELS: Record<string, string> = {
  success: '成功',
  failed: '失败',
  skipped: '跳过',
}

const budgetPercent = computed(() =>
  summary.value ? Math.min(100, Math.round(summary.value.budget_ratio * 100)) : 0,
)

function featureLabel(value: string): string {
  return FEATURE_LABELS[value] || value
}

function money(value: number): string {
  // 小额（单次调用）保留 6 位，大额（预算/月度）保留 2 位，避免出现 ¥500.000000
  if (value >= 1) return `¥${value.toFixed(2)}`
  return `¥${value.toFixed(6)}`
}

function tokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return String(value)
}

function formatTime(value: string): string {
  return value.replace('T', ' ').slice(0, 19)
}

function statusType(value: string): 'success' | 'danger' | 'info' {
  if (value === 'success') return 'success'
  if (value === 'failed') return 'danger'
  return 'info'
}

async function loadSummary() {
  try {
    summary.value = await analyticsApi.getCostSummary()
  } catch (e: any) {
    ElMessage.error(e.message || '加载成本汇总失败')
  }
}

async function loadCalls() {
  loading.value = true
  try {
    const data = await analyticsApi.listCalls({
      page: page.value,
      page_size: pageSize.value,
      feature: filters.feature || undefined,
      job_id: filters.jobId || undefined,
      status: filters.status || undefined,
    })
    calls.value = data.items
    total.value = data.total
  } catch (e: any) {
    ElMessage.error(e.message || '加载调用明细失败')
  } finally {
    loading.value = false
  }
}

async function loadJobs() {
  try {
    const data = await jobApi.listJobs({ page_size: 100 })
    jobs.value = data.items
  } catch {
    // 职位筛选项加载失败不阻断页面
  }
}

function refresh() {
  page.value = 1
  void loadCalls()
}

function onPageChange(value: number) {
  page.value = value
  void loadCalls()
}

watch(
  () => [filters.feature, filters.jobId, filters.status],
  () => refresh(),
)

onMounted(() => {
  void loadSummary()
  void loadCalls()
  void loadJobs()
})
</script>

<template>
  <div class="cost-page">
    <div class="page-header">
      <div>
        <h2>AI 成本监控</h2>
        <p class="subtitle">每次真实 LLM 调用都写入台账，金额按模型单价与 token 数计算</p>
      </div>
      <div class="header-actions">
        <el-button @click="$router.push('/analytics')">返回数据看板</el-button>
        <el-button type="primary" plain @click="loadSummary">刷新汇总</el-button>
      </div>
    </div>

    <template v-if="summary">
      <section class="kpi-grid">
        <article class="kpi">
          <span class="kpi-label">本月费用</span>
          <span class="kpi-value">{{ money(summary.month_cost) }}</span>
          <span class="kpi-hint">预算 {{ money(summary.budget) }}</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">今日费用</span>
          <span class="kpi-value">{{ money(summary.today_cost) }}</span>
          <span class="kpi-hint">UTC 当日</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">累计调用</span>
          <span class="kpi-value">{{ summary.total_calls }}</span>
          <span class="kpi-hint">{{ tokens(summary.total_tokens) }} tokens</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">预算使用率</span>
          <span
            class="kpi-value"
            :class="{ warn: summary.budget_status === 'warning', danger: summary.budget_status === 'exceeded' }"
          >{{ budgetPercent }}%</span>
          <div class="budget-track">
            <div
              class="budget-fill"
              :class="{ warn: summary.budget_status === 'warning', danger: summary.budget_status === 'exceeded' }"
              :style="{ width: `${budgetPercent}%` }"
            ></div>
          </div>
        </article>
      </section>

      <el-alert
        v-if="summary.budget_status === 'exceeded'"
        class="budget-alert"
        type="error"
        :closable="false"
        show-icon
        title="本月 AI 预算已超支"
        :description="`本月已花费 ${money(summary.month_cost)}，预算 ${money(summary.budget)}。建议检查高频功能或暂停非必要调用。`"
      />
      <el-alert
        v-else-if="summary.budget_status === 'warning'"
        class="budget-alert"
        type="warning"
        :closable="false"
        show-icon
        title="本月 AI 预算即将用尽"
        :description="`已使用 ${budgetPercent}%，本月花费 ${money(summary.month_cost)}。`"
      />

      <div class="content-grid">
        <section class="panel table-panel">
          <div class="panel-head">
            <h3>调用明细</h3>
            <span class="panel-hint">共 {{ total }} 条</span>
          </div>

          <div class="filters">
            <el-select v-model="filters.feature" placeholder="全部功能" clearable style="width: 150px">
              <el-option
                v-for="item in FEATURE_OPTIONS"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
            <el-select
              v-model="filters.jobId"
              placeholder="全部职位"
              clearable
              filterable
              style="width: 220px"
            >
              <el-option v-for="job in jobs" :key="job.id" :label="job.title" :value="job.id" />
            </el-select>
            <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px">
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="跳过" value="skipped" />
            </el-select>
          </div>

          <el-table v-loading="loading" :data="calls" size="small" class="cost-table">
            <el-table-column label="时间" width="150">
              <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
            </el-table-column>
            <el-table-column label="功能" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ featureLabel(row.feature) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="职位" min-width="120">
              <template #default="{ row }">{{ row.job_title || '—' }}</template>
            </el-table-column>
            <el-table-column label="模型" min-width="170">
              <template #default="{ row }">
                <span class="mono">{{ row.model || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Token（入/出）" width="130" align="right">
              <template #default="{ row }">
                {{ tokens(row.input_tokens) }} / {{ tokens(row.output_tokens) }}
              </template>
            </el-table-column>
            <el-table-column label="费用" width="110" align="right">
              <template #default="{ row }">
                <span class="cost">{{ money(row.cost) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="80" align="right">
              <template #default="{ row }">
                {{ row.duration_ms !== null ? `${row.duration_ms}ms` : '—' }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="statusType(row.status)">
                  {{ STATUS_LABELS[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination
              :current-page="page"
              :page-size="pageSize"
              :total="total"
              layout="prev, pager, next, total"
              background
              @current-change="onPageChange"
            />
          </div>
        </section>

        <aside class="side">
          <section class="panel">
            <div class="panel-head">
              <h3>按功能</h3>
              <span class="panel-hint">费用</span>
            </div>
            <div v-if="summary.by_feature.length" class="mini-list">
              <div v-for="item in summary.by_feature" :key="item.feature" class="mini-row">
                <span class="mini-name">{{ featureLabel(item.feature) }}</span>
                <span class="mini-meta">{{ item.calls }} 次 · {{ tokens(item.tokens) }}</span>
                <span class="mini-value">{{ money(item.cost) }}</span>
              </div>
            </div>
            <p v-else class="muted">暂无调用</p>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h3>按职位 Top 10</h3>
              <span class="panel-hint">费用</span>
            </div>
            <div v-if="summary.top_jobs.length" class="mini-list">
              <div v-for="item in summary.top_jobs" :key="item.job_id" class="mini-row">
                <span class="mini-name">{{ item.job_title }}</span>
                <span class="mini-meta">{{ item.calls }} 次 · {{ tokens(item.tokens) }}</span>
                <span class="mini-value">{{ money(item.cost) }}</span>
              </div>
            </div>
            <p v-else class="muted">暂无职位维度数据</p>
          </section>
        </aside>
      </div>
    </template>

    <el-empty v-else description="暂无成本数据" />
  </div>
</template>

<style scoped>
.cost-page {
  max-width: 1320px;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
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
  gap: 10px;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}
.kpi {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kpi-label {
  font-size: 12.5px;
  color: var(--muted);
}
.kpi-value {
  font-size: 24px;
  font-weight: 750;
  letter-spacing: -0.02em;
}
.kpi-value.warn {
  color: var(--warn);
}
.kpi-value.danger {
  color: var(--danger);
}
.kpi-hint {
  font-size: 11.5px;
  color: var(--faint);
}
.budget-track {
  height: 6px;
  background: #f1f2f8;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 4px;
}
.budget-fill {
  height: 100%;
  border-radius: 4px;
  background: var(--primary);
  transition: width 0.4s ease;
}
.budget-fill.warn {
  background: var(--warn);
}
.budget-fill.danger {
  background: var(--danger);
}
.budget-alert {
  margin-bottom: 14px;
}
.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 14px;
  align-items: start;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
}
.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12px;
}
.panel-head h3 {
  margin: 0;
  font-size: 14.5px;
}
.panel-hint {
  font-size: 11.5px;
  color: var(--faint);
}
.filters {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.cost-table {
  width: 100%;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: var(--muted);
}
.cost {
  font-weight: 650;
  color: var(--text);
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.mini-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.mini-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 10px;
}
.mini-name {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mini-value {
  font-size: 12.5px;
  font-weight: 700;
  text-align: right;
}
.mini-meta {
  grid-column: 1 / -1;
  font-size: 11px;
  color: var(--faint);
}
.muted {
  color: var(--muted);
  font-size: 12.5px;
}
@media (max-width: 1080px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
