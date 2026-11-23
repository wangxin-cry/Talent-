<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import * as appApi from '@/api/applications'
import * as interviewApi from '@/api/interviews'
import type { ApplicationDetail, Question, RagSource } from '@/api/applications'
import type { EvaluationTemplate, FeedbackSummary, InterviewSchedule } from '@/api/interviews'

const route = useRoute()
const router = useRouter()

const applicationId = Number(route.params.id)
const detail = ref<ApplicationDetail | null>(null)
const questions = ref<Question[]>([])
const questionMeta = ref<{ cached: boolean; source: string } | null>(null)
const ragSources = ref<RagSource[]>([])
const ragUsed = ref(false)
const useRag = ref(true)
const loading = ref(false)
const generating = ref(false)

// ---------------- 面试安排 / 评估 ----------------
const schedule = ref<InterviewSchedule | null>(null)
const scheduleForm = reactive({
  scheduled_at: '',
  duration_minutes: 60,
  mode: 'online',
  location: '',
  interviewer: '',
  note: '',
})
const savingSchedule = ref(false)
const template = ref<EvaluationTemplate | null>(null)
const feedbacks = ref<FeedbackSummary | null>(null)
const scores = reactive<Record<string, number>>({})
const feedbackForm = reactive({ round: 1, recommendation: 'hire', comment: '' })
const submittingFeedback = ref(false)

const EDU_CN: Record<string, string> = {
  college: '大专',
  bachelor: '本科',
  master: '硕士',
  phd: '博士',
}

const CATEGORY_LABELS: Record<string, string> = {
  project: '项目深挖',
  skill: '技能验证',
  gap: '能力缺口',
  experience: '经验评估',
  scenario: '场景设计',
  motivation: '动机匹配',
  general: '综合',
}

const CATEGORY_TYPES: Record<string, string> = {
  project: 'primary',
  skill: 'success',
  gap: 'danger',
  experience: 'warning',
  scenario: 'info',
  motivation: 'info',
  general: 'info',
}

type TagType = 'primary' | 'success' | 'danger' | 'warning' | 'info'

const match = computed(() => detail.value?.match || null)

const sourceLabel = computed(() => {
  const source = questionMeta.value?.source
  if (source === 'llm_rag') return 'AI 生成 · 知识库增强'
  if (source === 'llm') return 'LLM 生成'
  if (source === 'template') return '模板生成'
  return ''
})

const sourceTagType = computed(() =>
  questionMeta.value?.source === 'template' ? 'warning' : 'success',
)

function categoryLabel(value: string): string {
  return CATEGORY_LABELS[value] || value
}

function categoryType(value: string): TagType {
  return (CATEGORY_TYPES[value] || 'info') as TagType
}

function eduText(value?: string | null): string {
  if (!value) return '-'
  return EDU_CN[value] || value
}

function formatTime(value?: string | null): string {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

async function load() {
  loading.value = true
  try {
    const [data, questionSet] = await Promise.all([
      appApi.getApplication(applicationId),
      appApi.listQuestions(applicationId),
    ])
    detail.value = data
    questions.value = questionSet.questions
    questionMeta.value = { cached: questionSet.cached, source: questionSet.source }
    ragSources.value = questionSet.rag_sources || []
    ragUsed.value = questionSet.rag_used
  } catch (e: any) {
    ElMessage.error(e.message || '加载面试准备信息失败')
  } finally {
    loading.value = false
  }
  void loadInterview()
}

// ---------------- 面试安排 / 评估 ----------------
/** 后端存 UTC（无时区），展示时补 Z 再转本地 */
function utcToLocalInput(value?: string | null): string {
  if (!value) return ''
  const date = new Date(`${value}Z`)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatUtcLocal(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(`${value}Z`)
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function loadInterview() {
  try {
    const [saved, tpl, feedbackSummary] = await Promise.all([
      interviewApi.getSchedule(applicationId),
      interviewApi.getEvaluationTemplate(),
      interviewApi.listFeedbacks(applicationId),
    ])
    schedule.value = saved
    if (saved) {
      scheduleForm.scheduled_at = utcToLocalInput(saved.scheduled_at)
      scheduleForm.duration_minutes = saved.duration_minutes
      scheduleForm.mode = saved.mode
      scheduleForm.location = saved.location || ''
      scheduleForm.interviewer = saved.interviewer || ''
      scheduleForm.note = saved.note || ''
    }
    template.value = tpl
    feedbacks.value = feedbackSummary
    for (const dimension of tpl.dimensions) {
      if (!scores[dimension.key]) scores[dimension.key] = 3
    }
  } catch (e: any) {
    ElMessage.warning(e.message || '加载面试安排失败')
  }
}

async function saveSchedule() {
  if (!scheduleForm.scheduled_at) {
    ElMessage.warning('请选择面试时间')
    return
  }
  savingSchedule.value = true
  try {
    const utc = new Date(scheduleForm.scheduled_at).toISOString().slice(0, 19)
    schedule.value = await interviewApi.saveSchedule(applicationId, {
      scheduled_at: utc,
      duration_minutes: scheduleForm.duration_minutes,
      mode: scheduleForm.mode,
      location: scheduleForm.location || null,
      interviewer: scheduleForm.interviewer || null,
      note: scheduleForm.note || null,
    })
    ElMessage.success('面试安排已保存')
  } catch (e: any) {
    ElMessage.error(e.message || '保存面试安排失败')
  } finally {
    savingSchedule.value = false
  }
}

async function downloadIcs() {
  try {
    const blob = await interviewApi.downloadIcs(applicationId)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `interview-${applicationId}.ics`
    link.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e.message || '下载日历失败')
  }
}

async function submitFeedback() {
  submittingFeedback.value = true
  try {
    await interviewApi.createFeedback(applicationId, {
      round: feedbackForm.round,
      scores: { ...scores },
      recommendation: feedbackForm.recommendation,
      comment: feedbackForm.comment || null,
    })
    feedbacks.value = await interviewApi.listFeedbacks(applicationId)
    ElMessage.success('评估已提交')
    feedbackForm.comment = ''
  } catch (e: any) {
    ElMessage.error(e.message || '提交评估失败')
  } finally {
    submittingFeedback.value = false
  }
}

async function generate(useLlm: boolean) {
  generating.value = true
  try {
    const data = await appApi.generateQuestions(applicationId, useLlm, useRag.value)
    questions.value = data.questions
    questionMeta.value = { cached: data.cached, source: data.source }
    ragSources.value = data.rag_sources || []
    ragUsed.value = data.rag_used
    if (data.cached) {
      ElMessage.success('指纹未变化，已读取缓存题目（不重复计费）')
    } else if (data.source === 'llm_rag') {
      ElMessage.success(`AI 已结合知识库生成 ${data.total} 题`)
    } else if (data.source === 'llm') {
      ElMessage.success(`AI 生成完成，共 ${data.total} 题`)
    } else {
      ElMessage.warning(`LLM 不可用，已用模板兜底生成 ${data.total} 题`)
    }
  } catch (e: any) {
    ElMessage.error(e.message || '生成面试题失败')
  } finally {
    generating.value = false
  }
}

async function copyAll() {
  if (!questions.value.length) return
  const text = questions.value
    .map(
      (q, index) =>
        `${index + 1}. ${q.question}\n   考察点：${q.looking_for || '-'}\n   依据：${q.reference || '-'}\n   追问：${q.follow_up || '-'}`,
    )
    .join('\n\n')
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制全部题目')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="prep-page">
    <div class="page-header">
      <div class="title-line">
        <el-button link type="primary" @click="router.push('/board')">← 返回看板</el-button>
        <h2>{{ detail?.candidate_name || '候选人' }} · 面试准备</h2>
        <el-tag v-if="detail" effect="dark">{{ detail.status_label }}</el-tag>
      </div>
      <p class="subtitle">
        应聘职位：{{ detail?.job_title || '-' }}
        <span v-if="detail?.job_department"> · {{ detail.job_department }}</span>
      </p>
    </div>

    <div class="layout">
      <!-- 左：候选人画像 -->
      <aside class="profile">
        <section class="panel">
          <h3>候选人概况</h3>
          <dl class="info-grid">
            <div><dt>当前公司</dt><dd>{{ detail?.candidate_company || '-' }}</dd></div>
            <div><dt>当前职位</dt><dd>{{ detail?.candidate_title || '-' }}</dd></div>
            <div><dt>工作年限</dt><dd>{{ detail?.years_experience !== null && detail?.years_experience !== undefined ? `${detail.years_experience} 年` : '-' }}</dd></div>
            <div><dt>学历</dt><dd>{{ eduText(detail?.candidate_education) }}</dd></div>
            <div><dt>城市</dt><dd>{{ detail?.candidate_city || '-' }}</dd></div>
            <div><dt>进入流程</dt><dd>{{ formatTime(detail?.applied_at) }}</dd></div>
          </dl>
          <div v-if="detail?.candidate_skills.length" class="skills">
            <el-tag v-for="skill in detail.candidate_skills" :key="skill" size="small">{{ skill }}</el-tag>
          </div>
        </section>

        <section v-if="match" class="panel">
          <h3>匹配缺口</h3>
          <p class="gap-summary">{{ match.summary || '暂无结论' }}</p>
          <div class="gap-row">
            <span class="gap-label ok">命中必备</span>
            <span>{{ match.matched_must.join('、') || '无' }}</span>
          </div>
          <div class="gap-row">
            <span class="gap-label miss">缺失必备</span>
            <span>{{ match.missing_must.join('、') || '无' }}</span>
          </div>
          <div class="gap-row">
            <span class="gap-label miss">缺失加分</span>
            <span>{{ match.missing_nice.join('、') || '无' }}</span>
          </div>
          <div class="gap-row">
            <span class="gap-label">年限</span>
            <span v-if="match.years_gap !== null">
              候选人 {{ match.candidate_years ?? '-' }} 年 / 要求 {{ match.jd_min_years ?? '-' }} 年，
              {{ match.years_gap >= 0 ? `超 ${match.years_gap} 年` : `差 ${Math.abs(match.years_gap)} 年` }}
            </span>
            <span v-else>信息不足</span>
          </div>
        </section>

        <section v-if="detail?.projects.length" class="panel">
          <h3>简历项目</h3>
          <article v-for="(project, index) in detail.projects" :key="index" class="project">
            <div class="project-name">{{ project.name || `项目 ${index + 1}` }}</div>
            <div class="project-meta">
              {{ project.role || '角色未填' }}
              <span v-if="project.tech.length"> · {{ project.tech.join('、') }}</span>
            </div>
            <p v-if="project.description" class="project-desc">{{ project.description }}</p>
          </article>
        </section>
      </aside>

      <!-- 右：面试题 -->
      <main class="questions">
        <section class="panel">
          <div class="panel-head interview-head">
            <h3>面试安排</h3>
            <span class="panel-hint">
              {{ schedule ? `已安排：${formatUtcLocal(schedule.scheduled_at)}` : '尚未安排面试' }}
            </span>
          </div>
          <div class="schedule-grid">
            <el-date-picker
              v-model="scheduleForm.scheduled_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm"
              placeholder="选择面试时间"
            />
            <el-select v-model="scheduleForm.mode">
              <el-option label="线上" value="online" />
              <el-option label="现场" value="onsite" />
              <el-option label="电话" value="phone" />
            </el-select>
            <el-input-number
              v-model="scheduleForm.duration_minutes"
              :min="15"
              :max="480"
              :step="15"
              controls-position="right"
            />
            <el-input v-model="scheduleForm.interviewer" placeholder="面试官" />
            <el-input
              v-model="scheduleForm.location"
              class="span-2"
              placeholder="地点 / 会议链接"
            />
            <el-input v-model="scheduleForm.note" class="span-2" placeholder="备注（可选）" />
          </div>
          <div class="schedule-actions">
            <el-button type="primary" :loading="savingSchedule" @click="saveSchedule">保存安排</el-button>
            <el-button :disabled="!schedule" @click="downloadIcs">下载日历 (.ics)</el-button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head interview-head">
            <h3>面试评估</h3>
            <span v-if="feedbacks && feedbacks.total" class="panel-hint">
              已记录 {{ feedbacks.total }} 份 · 平均 {{ feedbacks.average_rating ?? '-' }} 分 · 结论
              {{ feedbacks.recommendation_label || '-' }}
            </span>
            <span v-else class="panel-hint">按维度打分并给出结论，沉淀面试记录</span>
          </div>
          <div v-if="template" class="score-grid">
            <div v-for="dimension in template.dimensions" :key="dimension.key" class="score-item">
              <div class="score-head">
                <span>{{ dimension.name }}</span>
                <el-rate v-model="scores[dimension.key]" :max="template.scale" />
              </div>
              <p class="score-desc">{{ dimension.description }}</p>
            </div>
          </div>
          <div class="feedback-form">
            <el-input-number v-model="feedbackForm.round" :min="1" :max="10" controls-position="right" />
            <el-select v-model="feedbackForm.recommendation">
              <el-option
                v-for="item in template?.recommendations || []"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
            <el-input v-model="feedbackForm.comment" class="feedback-comment" placeholder="面试评语" />
            <el-button type="primary" :loading="submittingFeedback" @click="submitFeedback">提交评估</el-button>
          </div>
          <div v-if="feedbacks?.items.length" class="feedback-list">
            <article v-for="item in feedbacks.items" :key="item.id" class="feedback-item">
              <div class="feedback-line">
                <strong>{{ item.interviewer_name || '面试官' }}</strong>
                <span>第 {{ item.round }} 轮</span>
                <el-tag
                  size="small"
                  :type="item.recommendation === 'no_hire' ? 'danger' : item.recommendation === 'hold' ? 'warning' : 'success'"
                >
                  {{ item.recommendation_label || '未结论' }}
                </el-tag>
                <span class="feedback-score">{{ item.overall_rating ?? '-' }} 分</span>
                <span class="feedback-time">{{ formatUtcLocal(item.create_time) }}</span>
              </div>
              <p v-if="item.comment" class="feedback-text">{{ item.comment }}</p>
            </article>
          </div>
        </section>

        <div class="questions-head">
          <div>
            <h3>面试题（{{ questions.length }}）</h3>
            <p class="hint">
              根据岗位要求与简历项目生成，每题标注考察点、引用依据与追问；LLM 不可用时自动模板兜底
            </p>
          </div>
          <div class="actions">
            <el-switch v-model="useRag" active-text="知识库增强" />
            <el-tag v-if="questionMeta?.cached && questions.length" type="info" effect="plain">缓存命中</el-tag>
            <el-tag v-if="questions.length" :type="sourceTagType" effect="plain">
              {{ sourceLabel }}
            </el-tag>
            <el-button v-if="questions.length" @click="copyAll">复制全部</el-button>
            <el-button :loading="generating" @click="generate(false)">模板生成</el-button>
            <el-button type="primary" :loading="generating" @click="generate(true)">AI 生成</el-button>
          </div>
        </div>

        <section v-if="ragUsed && ragSources.length" class="rag-panel">
          <div class="rag-head">
            <strong>知识库参考</strong>
            <span>来自相似候选人简历与历史面试题，仅供出题灵感</span>
          </div>
          <div class="rag-list">
            <div v-for="(source, index) in ragSources" :key="`${source.type}-${source.id}-${index}`" class="rag-item">
              <div class="rag-title">
                <el-tag size="small" :type="source.type === 'resume' ? 'primary' : 'info'" effect="plain">
                  {{ source.type === 'resume' ? '简历' : '历史题' }}
                </el-tag>
                <span>{{ source.title }}</span>
                <span class="rag-score">{{ Math.round(source.score * 100) }}%</span>
              </div>
              <p class="rag-snippet">{{ source.snippet }}</p>
            </div>
          </div>
        </section>

        <div v-if="questions.length" class="question-list">
          <article v-for="(item, index) in questions" :key="item.id" class="question">
            <div class="question-head">
              <span class="index">{{ index + 1 }}</span>
              <el-tag size="small" :type="categoryType(item.category)">
                {{ categoryLabel(item.category) }}
              </el-tag>
            </div>
            <p class="question-text">{{ item.question }}</p>
            <div v-if="item.reference" class="meta-row reference">
              <span class="meta-key">依据</span>{{ item.reference }}
            </div>
            <div v-if="item.looking_for" class="meta-row">
              <span class="meta-key">考察</span>{{ item.looking_for }}
            </div>
            <div v-if="item.follow_up" class="meta-row follow">
              <span class="meta-key">追问</span>{{ item.follow_up }}
            </div>
          </article>
        </div>

        <el-empty v-else description="还没有面试题">
          <el-button type="primary" :loading="generating" @click="generate(true)">生成面试题</el-button>
        </el-empty>
      </main>
    </div>
  </div>
</template>

<style scoped>
.prep-page {
  max-width: 1280px;
}
.page-header {
  margin-bottom: 18px;
}
.title-line {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.title-line h2 {
  margin: 0;
  font-size: 20px;
}
.subtitle {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 13px;
}
.layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.profile {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
}
.panel h3 {
  margin: 0 0 12px;
  font-size: 14px;
}
.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
  margin: 0;
}
.info-grid dt {
  font-size: 12px;
  color: var(--muted);
}
.info-grid dd {
  margin: 2px 0 0;
  font-size: 13px;
  font-weight: 550;
}
.skills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}
.gap-summary {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.6;
}
.gap-row {
  display: flex;
  gap: 10px;
  font-size: 12.5px;
  margin-top: 6px;
}
.gap-label {
  flex: 0 0 64px;
  color: var(--muted);
}
.gap-label.ok {
  color: #16a34a;
}
.gap-label.miss {
  color: #dc2626;
}
.project + .project {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}
.project-name {
  font-size: 13.5px;
  font-weight: 650;
}
.project-meta {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}
.project-desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.6;
}
.questions {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 18px 20px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.questions > .panel {
  background: transparent;
  border: none;
  border-bottom: 1px dashed var(--line);
  border-radius: 0;
  box-shadow: none;
  padding: 0 0 16px;
}
.questions > .panel:last-of-type {
  border-bottom: none;
}
.interview-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}
.interview-head h3 {
  margin: 0;
  font-size: 14.5px;
}
.panel-hint {
  font-size: 11.5px;
  color: var(--faint);
}
.schedule-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.schedule-grid .span-2 {
  grid-column: span 2;
}
.schedule-actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}
.score-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 18px;
}
.score-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  font-weight: 600;
}
.score-desc {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--muted);
}
.feedback-form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}
.feedback-comment {
  flex: 1;
  min-width: 220px;
}
.feedback-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.feedback-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: #fafbff;
}
.feedback-line {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  flex-wrap: wrap;
}
.feedback-score {
  font-weight: 700;
}
.feedback-time {
  margin-left: auto;
  color: var(--faint);
  font-size: 11.5px;
}
.feedback-text {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.6;
}
@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .schedule-grid,
  .score-grid {
    grid-template-columns: 1fr;
  }
  .schedule-grid .span-2 {
    grid-column: span 1;
  }
}
.questions-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.questions-head h3 {
  margin: 0;
  font-size: 15px;
}
.hint {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12.5px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.question-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}
.question {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 16px;
  background: #fdfdff;
  transition: border-color 0.16s, box-shadow 0.16s;
}
.question:hover {
  border-color: #d9dcf9;
  box-shadow: var(--shadow-sm);
}
.question-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.index {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
}
.question-text {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 550;
  line-height: 1.65;
}
.meta-row {
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.6;
  margin-top: 4px;
}
.meta-row.reference {
  color: #4338ca;
  background: #f5f6ff;
  border-radius: 7px;
  padding: 5px 8px;
}
.meta-row.follow {
  color: var(--warn);
}
.meta-key {
  display: inline-block;
  min-width: 38px;
  font-weight: 650;
  margin-right: 6px;
}
.rag-panel {
  margin-top: 16px;
  border: 1px solid #dbe3ff;
  background: #f7f9ff;
  border-radius: 12px;
  padding: 12px 14px;
}
.rag-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 13px;
}
.rag-head strong {
  font-size: 13.5px;
}
.rag-head span {
  color: var(--muted);
  font-size: 12px;
}
.rag-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rag-item {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 9px 11px;
}
.rag-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
}
.rag-score {
  margin-left: auto;
  color: var(--primary);
  font-weight: 700;
}
.rag-snippet {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
}
@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
