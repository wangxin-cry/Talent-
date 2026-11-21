<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { TableInstance } from 'element-plus'

import * as matchApi from '@/api/matching'
import * as jobApi from '@/api/jobs'
import type { MatchDetail, MatchItem } from '@/api/matching'
import type { Job } from '@/api/jobs'

const route = useRoute()

const jobs = ref<Job[]>([])
const selectedJobId = ref<number | null>(null)
const matches = ref<MatchItem[]>([])
const loading = ref(false)
const matching = ref(false)
const expanded = ref<Record<number, boolean>>({})
const detailCache = ref<Record<number, MatchDetail>>({})
const jobTitle = ref('')
// expand 行的展开状态由 el-table 内部维护，必须通过实例方法切换
const tableRef = ref<TableInstance | null>(null)

const minScore = ref(0)
const sortBy = ref<'score' | 'skill_score' | 'exp_score'>('score')

async function loadJobs() {
  try {
    const data = await jobApi.listJobs({ status: 'published', page_size: 100 })
    jobs.value = data.items
    if (route.query.job_id) {
      selectedJobId.value = Number(route.query.job_id)
    } else if (jobs.value.length) {
      selectedJobId.value = jobs.value[0].id
    }
  } catch (e: any) {
    ElMessage.error(e.message || '加载职位失败')
  }
}

async function doMatch() {
  if (!selectedJobId.value) return
  matching.value = true
  try {
    const data = await matchApi.triggerMatch(selectedJobId.value)
    matches.value = data.items
    jobTitle.value = jobs.value.find(j => j.id === selectedJobId.value)?.title || ''
    ElMessage.success(
      `匹配完成：${data.matched_count} 人（新计算 ${data.computed_count}，缓存命中 ${data.cached_count}）`,
    )
  } catch (e: any) {
    ElMessage.error(e.message || '匹配失败')
  } finally {
    matching.value = false
  }
}

async function loadMatches() {
  if (!selectedJobId.value) return
  loading.value = true
  try {
    const data = await matchApi.listMatches(selectedJobId.value, {
      min_score: minScore.value || undefined,
      sort: sortBy.value,
    })
    matches.value = data.items
    jobTitle.value = data.job_title
  } catch (e: any) {
    ElMessage.error(e.message || '加载匹配结果失败')
  } finally {
    loading.value = false
  }
}

async function toggleExpand(item: MatchItem) {
  const isOpen = !!expanded.value[item.id]

  // 关键：expand 列的展开态由 el-table 内部维护，必须调用实例方法
  tableRef.value?.toggleRowExpansion(item, !isOpen)
  expanded.value[item.id] = !isOpen

  if (isOpen) return
  if (!detailCache.value[item.id]) {
    try {
      detailCache.value[item.id] = await matchApi.getMatch(item.id)
    } catch (e: any) {
      ElMessage.error(e.message || '加载明细失败')
    }
  }
}

function scoreColor(score: number): string {
  if (score >= 80) return '#16a34a'
  if (score >= 60) return '#2563eb'
  if (score >= 40) return '#d97706'
  return '#dc2626'
}

function scoreLabel(score: number): string {
  if (score >= 80) return '高度匹配'
  if (score >= 60) return '基本匹配'
  if (score >= 40) return '部分匹配'
  return '匹配度低'
}

const EDU_CN: Record<string, string> = {
  college: '大专',
  bachelor: '本科',
  master: '硕士',
  phd: '博士',
}

function eduText(level?: string | null): string {
  if (!level) return '不限'
  return EDU_CN[level] || level
}

function yearsGapText(detail: MatchDetail): string {
  const gap = detail.detail?.features?.years_gap
  if (gap === null || gap === undefined) return '信息不足'
  return gap >= 0 ? `超 ${gap.toFixed(1)} 年` : `差 ${Math.abs(gap).toFixed(1)} 年`
}

async function onFeedback(item: MatchItem, feedback: 'fit' | 'unfit') {
  try {
    const updated = await matchApi.submitFeedback(item.id, feedback)
    item.feedback = updated.feedback
    ElMessage.success(feedback === 'fit' ? '已标记为合适' : '已标记为不合适')
  } catch (e: any) {
    ElMessage.error(e.message || '反馈失败')
  }
}

const displayMatches = computed(() => matches.value)

watch([minScore, sortBy], () => {
  if (matches.value.length) loadMatches()
})

onMounted(loadJobs)
watch(selectedJobId, (id) => {
  if (id) loadMatches()
})
</script>

<template>
  <div class="matching-page">
    <div class="page-header">
      <div>
        <h2>智能人岗匹配</h2>
        <p class="subtitle">基于规则打分（技能 50% / 经验 30% / 学历 12% / 其他 8%），结果可解释、可缓存</p>
      </div>
    </div>

    <div class="toolbar">
      <el-select
        v-model="selectedJobId"
        placeholder="选择职位"
        style="width: 320px"
        :loading="!jobs.length"
      >
        <el-option
          v-for="job in jobs"
          :key="job.id"
          :label="`${job.title}（${job.department || '未分配'}）`"
          :value="job.id"
        />
      </el-select>

      <el-button type="primary" :loading="matching" @click="doMatch">
        <el-icon><Refresh /></el-icon>
        智能匹配
      </el-button>

      <div class="filters">
        <span class="filter-label">最低分</span>
        <el-input-number v-model="minScore" :min="0" :max="100" :step="5" size="small" />
        <span class="filter-label">排序</span>
        <el-select v-model="sortBy" size="small" style="width: 110px">
          <el-option label="综合分" value="score" />
          <el-option label="技能分" value="skill_score" />
          <el-option label="经验分" value="exp_score" />
        </el-select>
      </div>
    </div>

    <div v-if="jobTitle" class="job-info">
      当前职位：<strong>{{ jobTitle }}</strong>
      <span v-if="matches.length" class="count">共 {{ matches.length }} 位候选人</span>
    </div>

    <el-table
      ref="tableRef"
      v-loading="loading"
      :data="displayMatches"
      row-key="id"
      style="width: 100%"
      :default-sort="{ prop: 'score', order: 'descending' }"
    >
      <el-table-column type="expand" width="40">
        <template #default="{ row }">
          <div v-if="detailCache[row.id]" class="detail-panel">
            <div class="detail-summary">
              <div class="stat">
                <span class="stat-num ok">{{ detailCache[row.id].matched_skills.length }}</span>
                <span class="stat-label">命中技能</span>
              </div>
              <div class="stat">
                <span class="stat-num miss">{{ detailCache[row.id].missing_skills.length }}</span>
                <span class="stat-label">缺失技能</span>
              </div>
              <div class="stat">
                <span class="stat-num">{{ yearsGapText(detailCache[row.id]) }}</span>
                <span class="stat-label">经验差距</span>
              </div>
            </div>

            <div class="detail-scores">
              <div class="score-bar">
                <span class="lbl">技能</span>
                <el-progress :percentage="Math.round((detailCache[row.id].skill_score || 0) * 100)" :show-text="false" :stroke-width="8" color="#6366f1" />
                <span class="val">{{ (detailCache[row.id].skill_score || 0).toFixed(2) }}</span>
              </div>
              <div class="score-bar">
                <span class="lbl">经验</span>
                <el-progress :percentage="Math.round((detailCache[row.id].exp_score || 0) * 100)" :show-text="false" :stroke-width="8" color="#0ea5e9" />
                <span class="val">{{ (detailCache[row.id].exp_score || 0).toFixed(2) }}</span>
              </div>
              <div class="score-bar">
                <span class="lbl">学历</span>
                <el-progress :percentage="Math.round((detailCache[row.id].edu_score || 0) * 100)" :show-text="false" :stroke-width="8" color="#22c55e" />
                <span class="val">{{ (detailCache[row.id].edu_score || 0).toFixed(2) }}</span>
              </div>
              <div class="score-bar">
                <span class="lbl">其他</span>
                <el-progress :percentage="Math.round((detailCache[row.id].other_score || 0) * 100)" :show-text="false" :stroke-width="8" color="#f59e0b" />
                <span class="val">{{ (detailCache[row.id].other_score || 0).toFixed(2) }}</span>
              </div>
            </div>

            <div class="detail-section conditions">
              <span>年限要求：{{ detailCache[row.id].detail.features.jd_min_years ?? '不限' }}{{ detailCache[row.id].detail.features.jd_min_years !== null ? ' 年' : '' }}</span>
              <span>候选人年限：{{ detailCache[row.id].detail.features.candidate_years ?? '未知' }}{{ detailCache[row.id].detail.features.candidate_years !== null ? ' 年' : '' }}</span>
              <span>学历：{{ eduText(detailCache[row.id].detail.features.candidate_edu_level) }} / 要求 {{ eduText(detailCache[row.id].detail.features.jd_edu_level) }}</span>
              <span>地点：{{ detailCache[row.id].detail.features.location_match ? '匹配' : '不匹配' }}</span>
            </div>

            <div class="detail-section">
              <div class="section-title">命中技能（必备 {{ detailCache[row.id].detail.features.matched_must.length }} / 加分 {{ detailCache[row.id].detail.features.matched_nice.length }}）</div>
              <el-tag v-for="s in detailCache[row.id].matched_skills" :key="s" type="success" effect="light" class="skill-tag">{{ s }}</el-tag>
              <span v-if="!detailCache[row.id].matched_skills.length" class="muted">无</span>
            </div>

            <div class="detail-section">
              <div class="section-title">缺失技能（必备 {{ detailCache[row.id].detail.features.missing_must.length }} / 加分 {{ detailCache[row.id].detail.features.missing_nice.length }}）</div>
              <el-tag v-for="s in detailCache[row.id].missing_skills" :key="s" type="danger" effect="light" class="skill-tag">{{ s }}</el-tag>
              <span v-if="!detailCache[row.id].missing_skills.length" class="muted">无</span>
            </div>

            <div class="detail-section" v-if="detailCache[row.id].detail.explanation?.risks?.length">
              <div class="section-title">风险点</div>
              <ul class="risk-list">
                <li v-for="(r, i) in detailCache[row.id].detail.explanation.risks" :key="i">{{ r }}</li>
              </ul>
            </div>

            <div class="detail-section">
              <div class="section-title">面试建议</div>
              <p class="suggestion">{{ detailCache[row.id].detail.explanation?.suggestion }}</p>
            </div>
          </div>
          <el-skeleton v-else :rows="3" animated />
        </template>
      </el-table-column>

      <el-table-column label="候选人" width="150">
        <template #default="{ row }">
          <router-link :to="`/candidates`" class="cand-link">
            {{ row.candidate_name || `候选人 #${row.candidate_id}` }}
          </router-link>
        </template>
      </el-table-column>

      <el-table-column label="综合分" width="120" sortable :sort-by="'score'">
        <template #default="{ row }">
          <div class="score-cell">
            <span class="score-num" :style="{ color: scoreColor(row.score) }">{{ row.score.toFixed(1) }}</span>
            <span class="score-badge" :style="{ background: scoreColor(row.score) + '22', color: scoreColor(row.score) }">{{ scoreLabel(row.score) }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="命中技能" min-width="220">
        <template #default="{ row }">
          <el-tag
            v-for="s in row.matched_skills.slice(0, 5)"
            :key="s"
            type="success"
            effect="light"
            size="small"
            class="skill-tag"
          >{{ s }}</el-tag>
          <span v-if="row.matched_skills.length > 5" class="more">+{{ row.matched_skills.length - 5 }}</span>
        </template>
      </el-table-column>

      <el-table-column label="缺失技能" min-width="180">
        <template #default="{ row }">
          <el-tag
            v-for="s in row.missing_skills.slice(0, 4)"
            :key="s"
            type="danger"
            effect="light"
            size="small"
            class="skill-tag"
          >{{ s }}</el-tag>
          <span v-if="!row.missing_skills.length" class="muted">无</span>
          <span v-else-if="row.missing_skills.length > 4" class="more">+{{ row.missing_skills.length - 4 }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="summary" label="结论" min-width="240" show-overflow-tooltip />

      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="toggleExpand(row)">
            {{ expanded[row.id] ? '收起' : '明细' }}
          </el-button>
          <el-button
            size="small"
            link
            type="success"
            :disabled="row.feedback === 'fit'"
            @click="onFeedback(row, 'fit')"
          >合适</el-button>
          <el-button
            size="small"
            link
            type="danger"
            :disabled="row.feedback === 'unfit'"
            @click="onFeedback(row, 'unfit')"
          >不合适</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !matches.length" description="选择职位后点击「智能匹配」开始" />
  </div>
</template>

<style scoped>
.matching-page {
  max-width: 1280px;
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
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0 14px;
  flex-wrap: wrap;
}
.filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.filter-label {
  font-size: 13px;
  color: var(--muted);
}
.job-info {
  margin-bottom: 12px;
  font-size: 14px;
}
.job-info .count {
  margin-left: 12px;
  color: var(--muted);
  font-size: 13px;
}
.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.score-num {
  font-size: 18px;
  font-weight: 700;
}
.score-badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}
.skill-tag {
  margin: 2px 4px 2px 0;
}
.more {
  font-size: 12px;
  color: var(--muted);
}
.muted {
  color: var(--muted);
  font-size: 13px;
}
.cand-link {
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}
.detail-panel {
  padding: 8px 20px 16px;
  background: #fafbff;
  border-radius: 8px;
}
.detail-summary {
  display: flex;
  gap: 28px;
  margin-bottom: 14px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-num {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
}
.stat-num.ok {
  color: #16a34a;
}
.stat-num.miss {
  color: #dc2626;
}
.stat-label {
  font-size: 12px;
  color: var(--muted);
}
.conditions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 20px;
  padding: 8px 12px;
  background: #fff;
  border-radius: 6px;
  font-size: 13px;
  color: var(--muted);
}
.detail-scores {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.score-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.score-bar .lbl {
  width: 36px;
  font-size: 13px;
  color: var(--muted);
}
.score-bar .val {
  width: 36px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
}
.detail-section {
  margin-bottom: 12px;
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}
.risk-list {
  margin: 0;
  padding-left: 18px;
  color: #b45309;
  font-size: 13px;
}
.suggestion {
  margin: 0;
  font-size: 13px;
  color: var(--text);
  line-height: 1.6;
}
</style>
