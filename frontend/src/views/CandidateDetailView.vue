<script setup lang="ts">
/**
 * 候选人 360° 详情页
 * 汇总：档案与结构化简历、应聘记录、职位匹配、流转时间线、原始文件
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import * as api from '@/api/candidates'
import type { CandidateOverview } from '@/api/candidates'

const route = useRoute()
const router = useRouter()

const data = ref<CandidateOverview | null>(null)
const loading = ref(false)
const tab = ref('resume')

const candidateId = computed(() => Number(route.params.id))

const EDUCATION_LABEL: Record<string, string> = {
  college: '大专',
  bachelor: '本科',
  master: '硕士',
  phd: '博士',
}

const STATUS_TYPE: Record<string, 'info' | 'warning' | 'success' | 'danger' | ''> = {
  new: 'info',
  screening: 'warning',
  interview: '',
  offer: 'success',
  hired: 'success',
  rejected: 'danger',
}

const TIMELINE_TYPE: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  candidate: 'primary',
  resume: 'info',
  parse: 'info',
  application: 'success',
  stage: 'warning',
}

const structured = computed(() => data.value?.structured ?? null)
const files = computed(() => data.value?.files ?? [])
const applications = computed(() => data.value?.applications ?? [])
const matches = computed(() => data.value?.matches ?? [])
const timeline = computed(() => data.value?.timeline ?? [])

const activeCount = computed(
  () => applications.value.filter((item) => !['hired', 'rejected'].includes(item.status)).length,
)

const facts = computed(() => {
  const item = data.value
  if (!item) return []
  const education = [
    item.education_level ? EDUCATION_LABEL[item.education_level] || item.education_level : '',
    item.school || '',
    item.major || '',
  ].filter(Boolean)
  return [
    education.join(' · '),
    item.years_experience != null ? `${item.years_experience} 年经验` : '',
    item.city || '',
  ].filter(Boolean)
})

function statusType(status: string) {
  return STATUS_TYPE[status] ?? 'info'
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function dayOf(value?: string | null): string {
  const text = formatDate(value)
  return text === '—' ? text : text.slice(0, 10)
}

async function load() {
  if (!candidateId.value) return
  loading.value = true
  try {
    data.value = await api.getCandidateOverview(candidateId.value)
  } catch (e: any) {
    ElMessage.error(e.message || '加载候选人失败')
  } finally {
    loading.value = false
  }
}

function back() {
  router.push('/candidates')
}

async function downloadFile(fileId: number) {
  try {
    const { url } = await api.downloadResumeFile(fileId)
    window.open(url, '_blank', 'noopener')
  } catch (e: any) {
    ElMessage.error(e.message || '获取下载链接失败')
  }
}

function downloadLatest() {
  const file = files.value.find((item) => item.status === 'success') || files.value[0]
  if (!file) {
    ElMessage.warning('该候选人还没有简历文件')
    return
  }
  void downloadFile(file.id)
}

function goBoard() {
  router.push('/board')
}

function goPrep(applicationId: number) {
  router.push(`/applications/${applicationId}/prep`)
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page">
    <div class="back-row">
      <el-button link @click="back">← 返回候选人列表</el-button>
    </div>

    <template v-if="data">
      <header class="panel head">
        <div class="head-main">
          <div class="title-row">
            <h1>{{ data.name || '未识别姓名' }}</h1>
            <span class="meta">#{{ data.id }}</span>
          </div>
          <p class="role">
            {{ data.current_title || '职位未知' }}
            <span v-if="data.current_company"> · {{ data.current_company }}</span>
          </p>
          <div class="facts">
            <span v-for="fact in facts" :key="fact">{{ fact }}</span>
          </div>
          <div class="contact">
            <span>手机：{{ data.phone || '—' }}</span>
            <span>邮箱：{{ data.email || '—' }}</span>
          </div>
          <div v-if="data.skills?.length" class="skills">
            <el-tag v-for="skill in data.skills" :key="skill" size="small" effect="plain">
              {{ skill }}
            </el-tag>
          </div>
        </div>
        <div class="head-actions">
          <el-button @click="goBoard">流程看板</el-button>
          <el-button type="primary" @click="downloadLatest">下载简历</el-button>
        </div>
      </header>

      <div class="stat-row">
        <div class="stat">
          <span class="stat-value">{{ applications.length }}</span>
          <span class="stat-label">应聘职位</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ activeCount }}</span>
          <span class="stat-label">进行中</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ matches.length }}</span>
          <span class="stat-label">匹配记录</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ files.length }}</span>
          <span class="stat-label">简历文件</span>
        </div>
      </div>

      <section class="panel">
        <el-tabs v-model="tab">
          <!-- 简历信息 -->
          <el-tab-pane label="简历信息" name="resume">
            <div v-if="structured" class="stack">
              <div class="section-title">教育经历</div>
              <div v-if="structured.education?.length" class="list">
                <div v-for="(item, index) in structured.education" :key="index" class="item">
                  <div class="item-head">
                    <strong>{{ item.school || '—' }}</strong>
                    <span class="meta">{{ item.start || '—' }} ~ {{ item.end || '—' }}</span>
                  </div>
                  <div class="meta">
                    {{ [item.degree, item.major].filter(Boolean).join(' · ') || '—' }}
                  </div>
                </div>
              </div>
              <div v-else class="meta empty-line">未识别到教育经历</div>

              <div class="section-title">工作经历</div>
              <div v-if="structured.work?.length" class="list">
                <div v-for="(item, index) in structured.work" :key="index" class="item">
                  <div class="item-head">
                    <strong>{{ item.company || '—' }} · {{ item.title || '—' }}</strong>
                    <span class="meta">{{ item.start || '—' }} ~ {{ item.end || '—' }}</span>
                  </div>
                  <p v-if="item.description" class="desc">{{ item.description }}</p>
                </div>
              </div>
              <div v-else class="meta empty-line">未识别到工作经历（应届生正常）</div>

              <template v-if="structured.projects?.length">
                <div class="section-title">项目经历</div>
                <div class="list">
                  <div v-for="(item, index) in structured.projects" :key="index" class="item">
                    <div class="item-head">
                      <strong>{{ item.name || '—' }} · {{ item.role || '—' }}</strong>
                    </div>
                    <div v-if="item.stack?.length" class="meta">{{ item.stack.join(' / ') }}</div>
                    <p v-if="item.description" class="desc">{{ item.description }}</p>
                  </div>
                </div>
              </template>
            </div>
            <div v-else class="meta empty-line">暂无结构化解析结果，可在候选人列表用「校对」补充</div>

            <div class="section-title">简历文件</div>
            <div v-if="files.length" class="list">
              <div v-for="file in files" :key="file.id" class="file-row">
                <div class="file-main">
                  <div class="file-name">{{ file.original_name }}</div>
                  <div class="meta">
                    {{ file.parser || '待解析' }}
                    <span v-if="file.parsed_time"> · {{ formatDate(file.parsed_time) }}</span>
                  </div>
                  <div v-if="file.error_reason" class="error-text">{{ file.error_reason }}</div>
                </div>
                <div class="file-actions">
                  <el-tag size="small" :type="file.status === 'success' ? 'success' : file.status === 'failed' ? 'danger' : 'info'">
                    {{ file.status === 'success' ? '已解析' : file.status === 'failed' ? '解析失败' : '处理中' }}
                  </el-tag>
                  <el-button link type="primary" @click="downloadFile(file.id)">下载</el-button>
                </div>
              </div>
            </div>
            <div v-else class="meta empty-line">暂无简历文件</div>

            <el-collapse v-if="data.plain_text" class="raw">
              <el-collapse-item title="查看简历原文" name="raw">
                <pre class="raw-text">{{ data.plain_text }}</pre>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>

          <!-- 应聘与匹配 -->
          <el-tab-pane label="应聘与匹配" name="applications">
            <div class="section-title">应聘记录</div>
            <el-table v-if="applications.length" :data="applications" class="table">
              <el-table-column label="职位" min-width="170">
                <template #default="{ row }">
                  <div class="job-title">{{ row.job_title }}</div>
                  <div class="meta">{{ row.department || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusType(row.status)">{{ row.status_label }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="匹配分" width="90">
                <template #default="{ row }">
                  {{ row.match_score != null ? Math.round(row.match_score) : '—' }}
                </template>
              </el-table-column>
              <el-table-column label="投递时间" width="120">
                <template #default="{ row }">
                  <span class="meta">{{ dayOf(row.applied_at) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="当前阶段" width="120">
                <template #default="{ row }">
                  <span class="meta">{{ dayOf(row.stage_entered_at) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="面试题" width="80">
                <template #default="{ row }">
                  <span class="meta">{{ row.question_count || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="110" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="goPrep(row.id)">面试准备</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <div class="meta empty-line">还没有加入任何职位流程</div>
              </template>
            </el-table>
            <div v-else class="meta empty-line">还没有加入任何职位流程</div>

            <div class="section-title">人岗匹配</div>
            <div v-if="matches.length" class="list">
              <div v-for="match in matches" :key="match.id" class="match">
                <div class="match-head">
                  <div>
                    <div class="job-title">{{ match.job_title }}</div>
                    <div class="meta">
                      {{ formatDate(match.create_time) }}
                      <el-tag v-if="match.feedback" size="small" class="feedback" :type="match.feedback === 'fit' ? 'success' : 'danger'">
                        {{ match.feedback === 'fit' ? 'HR 认为合适' : 'HR 认为不合适' }}
                      </el-tag>
                    </div>
                  </div>
                  <div class="match-score">{{ Math.round(match.score) }}<span>分</span></div>
                </div>
                <el-progress :percentage="Math.round(match.score)" :show-text="false" :stroke-width="6" />
                <p v-if="match.summary" class="desc">{{ match.summary }}</p>
                <div class="skill-groups">
                  <div v-if="match.matched_skills.length" class="skill-group">
                    <span class="meta">命中</span>
                    <el-tag v-for="skill in match.matched_skills" :key="skill" size="small" type="success" effect="plain">
                      {{ skill }}
                    </el-tag>
                  </div>
                  <div v-if="match.missing_skills.length" class="skill-group">
                    <span class="meta">缺失</span>
                    <el-tag v-for="skill in match.missing_skills" :key="skill" size="small" type="danger" effect="plain">
                      {{ skill }}
                    </el-tag>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="meta empty-line">还没有匹配记录，可在「人岗匹配」页对职位执行匹配</div>
          </el-tab-pane>

          <!-- 时间线 -->
          <el-tab-pane label="时间线" name="timeline">
            <el-timeline v-if="timeline.length">
              <el-timeline-item
                v-for="(item, index) in timeline"
                :key="index"
                :timestamp="formatDate(item.time)"
                :type="TIMELINE_TYPE[item.kind] || 'info'"
                placement="top"
              >
                <div class="timeline-title">{{ item.title }}</div>
                <div v-if="item.description" class="meta">{{ item.description }}</div>
              </el-timeline-item>
            </el-timeline>
            <div v-else class="meta empty-line">暂无记录</div>
          </el-tab-pane>
        </el-tabs>
      </section>
    </template>

    <el-empty v-else-if="!loading" description="候选人不存在或无权访问" />
  </div>
</template>

<style scoped>
.page {
  max-width: 1240px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 200px;
}
.back-row {
  margin-bottom: -4px;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
}
.head-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.title-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.title-row h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 750;
  letter-spacing: -0.02em;
}
.role {
  margin: 0;
  font-size: 13.5px;
  color: var(--text);
}
.facts,
.contact {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 12.5px;
  color: var(--muted);
}
.skills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}
.head-actions {
  display: flex;
  gap: 10px;
  flex: 0 0 auto;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stat {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  box-shadow: var(--shadow-sm);
}
.stat-value {
  font-size: 22px;
  font-weight: 750;
  color: var(--primary);
  line-height: 1.2;
}
.stat-label {
  font-size: 12px;
  color: var(--muted);
}
.meta {
  font-size: 12px;
  color: var(--muted);
}
.stack,
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.section-title {
  margin: 18px 0 8px;
  font-weight: 650;
  font-size: 13.5px;
  padding-left: 9px;
  border-left: 3px solid #c7cbf8;
}
.section-title:first-child {
  margin-top: 2px;
}
.item {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 12px;
  background: #fafbff;
}
.item-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
}
.desc {
  margin: 5px 0 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: #475467;
  white-space: pre-wrap;
}
.empty-line {
  padding: 6px 0;
}
.file-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
}
.file-main {
  min-width: 0;
}
.file-name {
  font-weight: 600;
  word-break: break-all;
}
.file-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}
.error-text {
  margin-top: 4px;
  font-size: 12px;
  color: #dc2626;
}
.table {
  width: 100%;
}
.job-title {
  font-weight: 600;
}
.match {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 11px 14px;
  background: #fafbff;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.match-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.match-score {
  font-size: 22px;
  font-weight: 750;
  color: var(--primary);
  line-height: 1.1;
}
.match-score span {
  font-size: 11px;
  color: var(--muted);
  margin-left: 2px;
}
.feedback {
  margin-left: 8px;
}
.skill-groups {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.skill-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.raw {
  margin-top: 18px;
}
.raw-text {
  white-space: pre-wrap;
  font-size: 12.5px;
  line-height: 1.7;
  color: #475467;
  margin: 0;
  max-height: 420px;
  overflow: auto;
}
.timeline-title {
  font-weight: 600;
  font-size: 13px;
}
@media (max-width: 760px) {
  .head {
    flex-direction: column;
  }
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
