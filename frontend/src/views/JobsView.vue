<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import * as api from '@/api/jobs'
import type { Job, JobPayload, Skill, SkillBrief } from '@/api/jobs'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  pending: '待审批',
  published: '招聘中',
  closed: '已关闭',
  archived: '已归档',
}

const WORK_MODES = [
  { value: 'onsite', label: '坐班' },
  { value: 'hybrid', label: '混合' },
  { value: 'remote', label: '远程' },
]

const EMPLOYMENT_TYPES = [
  { value: 'fulltime', label: '全职' },
  { value: 'intern', label: '实习' },
  { value: 'parttime', label: '兼职' },
]

const EDUCATION_LEVELS = [
  { value: 'college', label: '大专' },
  { value: 'bachelor', label: '本科' },
  { value: 'master', label: '硕士' },
  { value: 'phd', label: '博士' },
]

function tagType(status: string): 'success' | 'info' | 'warning' | 'danger' | undefined {
  if (status === 'published') return 'success'
  if (status === 'draft') return 'info'
  if (status === 'pending') return 'warning'
  if (status === 'closed') return 'danger'
  return undefined
}

function salaryText(job: Job): string {
  if (job.salary_min == null && job.salary_max == null) return '—'
  const min = job.salary_min ?? '?'
  const max = job.salary_max ?? '?'
  return `${min}-${max}K`
}

// ---------------------------------------------------------------- 列表
const jobs = ref<Job[]>([])
const total = ref(0)
const loading = ref(false)
const filters = reactive({ status: '', q: '' })
const page = ref(1)
const pageSize = ref(10)

async function loadJobs() {
  loading.value = true
  try {
    const data = await api.listJobs({
      status: filters.status || undefined,
      q: filters.q.trim() || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    jobs.value = data.items
    total.value = data.total
  } catch (e: any) {
    ElMessage.error(e.message || '加载职位失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  void loadJobs()
}

function onReset() {
  filters.status = ''
  filters.q = ''
  page.value = 1
  void loadJobs()
}

function onPageChange(value: number) {
  page.value = value
  void loadJobs()
}

// ---------------------------------------------------------------- 表单
interface FormState {
  id: number | null
  title: string
  department: string
  location: string
  work_mode: string
  employment_type: string
  headcount: number
  min_years: number | undefined
  education_level: string
  salary_min: number | undefined
  salary_max: number | undefined
  description: string
  requirements: string
  skills: (number | string)[]
  must_have_skills: (number | string)[]
  jd_source: string
}

function emptyForm(): FormState {
  return {
    id: null,
    title: '',
    department: '',
    location: '',
    work_mode: '',
    employment_type: 'fulltime',
    headcount: 1,
    min_years: undefined,
    education_level: '',
    salary_min: undefined,
    salary_max: undefined,
    description: '',
    requirements: '',
    skills: [],
    must_have_skills: [],
    jd_source: 'manual',
  }
}

const drawer = ref(false)
const saving = ref(false)
const form = reactive<FormState>(emptyForm())
const skillOptions = ref<Skill[]>([])
const isEditing = computed(() => form.id !== null)

function mergeSkillOptions(skills: SkillBrief[]) {
  for (const skill of skills) {
    if (!skillOptions.value.some((item) => item.id === skill.id)) {
      skillOptions.value.push({ ...skill, aliases: [], is_active: true })
    }
  }
}

async function loadSkillOptions() {
  try {
    skillOptions.value = await api.searchSkills('', 200)
  } catch {
    skillOptions.value = []
  }
}

function openCreate() {
  Object.assign(form, emptyForm())
  aiKeywords.value = ''
  aiNote.value = ''
  drawer.value = true
  void loadSkillOptions()
}

function openEdit(job: Job) {
  Object.assign(form, {
    id: job.id,
    title: job.title,
    department: job.department ?? '',
    location: job.location ?? '',
    work_mode: job.work_mode ?? '',
    employment_type: job.employment_type,
    headcount: job.headcount,
    min_years: job.min_years ?? undefined,
    education_level: job.education_level ?? '',
    salary_min: job.salary_min ?? undefined,
    salary_max: job.salary_max ?? undefined,
    description: job.description ?? '',
    requirements: job.requirements ?? '',
    skills: job.skills.map((skill) => skill.id),
    must_have_skills: job.must_have_skills.map((skill) => skill.id),
    jd_source: job.jd_source,
  })
  mergeSkillOptions([...job.skills, ...job.must_have_skills])
  aiKeywords.value = ''
  aiNote.value = ''
  drawer.value = true
  void loadSkillOptions()
}

async function resolveSkillValues(values: (number | string)[]): Promise<number[]> {
  const ids: number[] = []
  for (const value of values) {
    if (typeof value === 'number') {
      ids.push(value)
      continue
    }
    const name = String(value).trim()
    if (!name) continue
    const existing = skillOptions.value.find(
      (skill) => skill.name.toLowerCase() === name.toLowerCase(),
    )
    if (existing) {
      ids.push(existing.id)
      continue
    }
    try {
      const created = await api.createSkill({ name })
      skillOptions.value.push(created)
      ids.push(created.id)
    } catch (e: any) {
      ElMessage.error(e.message || `创建技能「${name}」失败`)
    }
  }
  return [...new Set(ids)]
}

async function save(publishAfter: boolean) {
  if (!form.title.trim()) {
    ElMessage.warning('请填写职位名称')
    return
  }
  if (
    form.salary_min != null &&
    form.salary_max != null &&
    form.salary_min > form.salary_max
  ) {
    ElMessage.warning('薪资下限不能大于上限')
    return
  }

  saving.value = true
  try {
    const payload: JobPayload = {
      title: form.title.trim(),
      department: form.department.trim() || null,
      location: form.location.trim() || null,
      work_mode: form.work_mode || null,
      employment_type: form.employment_type,
      headcount: form.headcount,
      min_years: form.min_years ?? null,
      education_level: form.education_level || null,
      salary_min: form.salary_min ?? null,
      salary_max: form.salary_max ?? null,
      description: form.description.trim() || null,
      requirements: form.requirements.trim() || null,
      skills: await resolveSkillValues(form.skills),
      must_have_skills: await resolveSkillValues(form.must_have_skills),
      jd_source: form.jd_source,
    }

    let job: Job
    if (form.id != null) {
      job = await api.updateJob(form.id, payload)
    } else {
      job = await api.createJob(payload)
      form.id = job.id
    }

    if (publishAfter && job.status !== 'published') {
      job = await api.publishJob(job.id)
    }

    ElMessage.success(publishAfter ? '已发布' : '已保存')
    drawer.value = false
    await loadJobs()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
    await loadJobs()
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- AI 生成
const aiKeywords = ref('')
const aiNote = ref('')
const generating = ref(false)

async function onGenerateJd() {
  if (!form.title.trim()) {
    ElMessage.warning('请先填写职位名称')
    return
  }
  generating.value = true
  try {
    const keywords = aiKeywords.value
      .split(/[,，、\s]+/)
      .map((item) => item.trim())
      .filter(Boolean)
    const result = await api.generateJd({
      title: form.title.trim(),
      department: form.department.trim() || null,
      location: form.location.trim() || null,
      keywords,
    })
    form.description = result.description
    form.requirements = result.requirements
    form.skills = result.skills.map((skill) => skill.id)
    form.must_have_skills = result.must_have_skills.map((skill) => skill.id)
    form.jd_source = 'ai'
    mergeSkillOptions([...result.skills, ...result.must_have_skills])
    aiNote.value = result.note || ''
    ElMessage.success('JD 已生成，可编辑后保存')
  } catch (e: any) {
    ElMessage.error(e.message || '生成失败')
  } finally {
    generating.value = false
  }
}

// ---------------------------------------------------------------- 状态流转
async function transition(job: Job, action: 'publish' | 'close' | 'archive') {
  const labels = { publish: '发布', close: '关闭', archive: '归档' }
  try {
    await ElMessageBox.confirm(
      `确定要${labels[action]}职位「${job.title}」吗？`,
      '状态变更',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  try {
    if (action === 'publish') await api.publishJob(job.id)
    if (action === 'close') await api.closeJob(job.id)
    if (action === 'archive') await api.archiveJob(job.id)
    ElMessage.success(`已${labels[action]}`)
    await loadJobs()
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
  }
}

const route = useRoute()
const router = useRouter()

onMounted(async () => {
  await loadJobs()
  if (route.query.new !== undefined) {
    openCreate()
    void router.replace({ path: '/jobs' })
  }
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>职位管理</h1>
        <p class="sub">建职位 → AI 生成 JD → 编辑 → 发布，状态机控制流转</p>
      </div>
      <el-button type="primary" @click="openCreate">新建职位</el-button>
    </header>

    <section class="panel">
      <div class="filters">
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 140px">
          <el-option label="草稿" value="draft" />
          <el-option label="待审批" value="pending" />
          <el-option label="招聘中" value="published" />
          <el-option label="已关闭" value="closed" />
          <el-option label="已归档" value="archived" />
        </el-select>
        <el-input
          v-model="filters.q"
          placeholder="搜索职位名称 / 部门"
          clearable
          style="width: 240px"
          @keyup.enter="onSearch"
        />
        <el-button type="primary" plain @click="onSearch">查询</el-button>
        <el-button @click="onReset">重置</el-button>
      </div>

      <el-table v-loading="loading" :data="jobs" row-key="id" class="table">
        <el-table-column label="职位" min-width="220">
          <template #default="{ row }">
            <div class="job-title">{{ row.title }}</div>
            <div class="job-meta">
              {{ row.department || '未填部门' }} · {{ row.location || '地点待定' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="技能" min-width="220">
          <template #default="{ row }">
            <el-tag
              v-for="skill in row.skills.slice(0, 4)"
              :key="skill.id"
              size="small"
              class="skill-tag"
              :type="row.must_have_skills.some((s: SkillBrief) => s.id === skill.id) ? 'warning' : 'info'"
            >
              {{ skill.name }}
            </el-tag>
            <span v-if="row.skills.length > 4" class="more">+{{ row.skills.length - 4 }}</span>
            <span v-if="!row.skills.length" class="muted">暂无技能</span>
          </template>
        </el-table-column>
        <el-table-column label="薪资" width="110">
          <template #default="{ row }">{{ salaryText(row) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="tagType(row.status)" size="small">
              {{ STATUS_LABEL[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="apply_count" label="应聘" width="70" />
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ row.update_time?.replace('T', ' ').slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button
              v-if="row.status === 'draft' || row.status === 'pending'"
              link
              type="success"
              @click="transition(row, 'publish')"
            >
              发布
            </el-button>
            <el-button
              v-if="row.status === 'published'"
              link
              type="warning"
              @click="transition(row, 'close')"
            >
              关闭
            </el-button>
            <el-button
              v-if="row.status !== 'archived'"
              link
              type="info"
              @click="transition(row, 'archive')"
            >
              归档
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty">还没有职位，点击右上角「新建职位」开始</div>
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </section>

    <el-drawer v-model="drawer" :title="isEditing ? '编辑职位' : '新建职位'" size="680px">
      <el-form label-width="92px" label-position="right">
        <div class="grid2">
          <el-form-item label="职位名称" required>
            <el-input v-model="form.title" maxlength="200" placeholder="如：高级后端工程师" />
          </el-form-item>
          <el-form-item label="部门">
            <el-input v-model="form.department" maxlength="100" placeholder="如：研发部" />
          </el-form-item>
          <el-form-item label="工作地点">
            <el-input v-model="form.location" maxlength="100" placeholder="如：上海" />
          </el-form-item>
          <el-form-item label="招聘人数">
            <el-input-number v-model="form.headcount" :min="1" :max="999" controls-position="right" />
          </el-form-item>
          <el-form-item label="工作模式">
            <el-select v-model="form.work_mode" clearable placeholder="不限">
              <el-option v-for="item in WORK_MODES" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="用工类型">
            <el-select v-model="form.employment_type">
              <el-option v-for="item in EMPLOYMENT_TYPES" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="最低学历">
            <el-select v-model="form.education_level" clearable placeholder="不限">
              <el-option v-for="item in EDUCATION_LEVELS" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="经验要求">
            <el-input-number v-model="form.min_years" :min="0" :max="50" :step="0.5" controls-position="right" />
          </el-form-item>
          <el-form-item label="薪资下限">
            <el-input-number v-model="form.salary_min" :min="0" :max="1000" controls-position="right" />
            <span class="unit">K / 月</span>
          </el-form-item>
          <el-form-item label="薪资上限">
            <el-input-number v-model="form.salary_max" :min="0" :max="1000" controls-position="right" />
            <span class="unit">K / 月</span>
          </el-form-item>
        </div>

        <el-form-item label="技能要求">
          <el-select
            v-model="form.skills"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入技能后回车，如 K8s"
            style="width: 100%"
          >
            <el-option v-for="item in skillOptions" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>

        <el-form-item label="必备技能">
          <el-select
            v-model="form.must_have_skills"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="发布匹配时会重点考察"
            style="width: 100%"
          >
            <el-option v-for="item in skillOptions" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>

        <div class="ai-box">
          <div class="ai-head">
            <strong>AI 生成 JD</strong>
            <span class="muted small">输入关键词，生成三段式 JD，可编辑后再保存</span>
          </div>
          <div class="ai-row">
            <el-input
              v-model="aiKeywords"
              placeholder="关键词，逗号分隔，如：Python, K8s, 微服务"
              @keyup.enter="onGenerateJd"
            />
            <el-button type="primary" plain :loading="generating" @click="onGenerateJd">生成</el-button>
          </div>
          <p v-if="aiNote" class="ai-note">{{ aiNote }}</p>
        </div>

        <el-form-item label="职位描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="7"
            placeholder="职责描述；发布前必填"
          />
        </el-form-item>
        <el-form-item label="任职要求">
          <el-input
            v-model="form.requirements"
            type="textarea"
            :rows="7"
            placeholder="任职要求；发布前必填"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="drawer-footer">
          <span class="muted small">AI 生成内容请确认后再保存；发布前需描述、要求与技能齐全</span>
          <div class="actions">
            <el-button @click="drawer = false">取消</el-button>
            <el-button :loading="saving" @click="save(false)">保存草稿</el-button>
            <el-button type="primary" :loading="saving" @click="save(true)">保存并发布</el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { max-width: 1240px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-head h1 {
  position: relative; margin: 0 0 4px; padding-left: 13px;
  font-size: 23px; font-weight: 750; letter-spacing: -0.02em;
}
.page-head h1::before {
  content: ''; position: absolute; left: 0; top: 4px; bottom: 4px; width: 4px;
  border-radius: 4px; background: linear-gradient(180deg, #6366f1, #a78bfa);
}
.sub { margin: 0 0 0 13px; color: var(--muted); font-size: 13px; }

.panel {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 16px 18px; box-shadow: var(--shadow-sm);
}
.filters { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.table { width: 100%; }
.job-title { font-weight: 600; }
.job-meta { font-size: 12px; color: var(--muted); margin-top: 2px; }
.skill-tag { margin: 0 6px 4px 0; }
.more { font-size: 12px; color: var(--muted); }
.muted { color: var(--muted); font-size: 12.5px; }
.empty { color: var(--muted); padding: 24px 0; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; column-gap: 10px; }
.unit { margin-left: 8px; color: var(--muted); font-size: 12px; }

.ai-box {
  background: linear-gradient(180deg, #fbfcff, #f5f7ff);
  border: 1px dashed #c9cffa; border-radius: 11px;
  padding: 12px; margin: 4px 0 16px 92px;
}
.ai-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 9px; }
.ai-row { display: flex; gap: 9px; }
.ai-note { margin: 8px 0 0; font-size: 12px; color: #8a6d3b; }
.small { font-size: 12px; }

.drawer-footer { display: flex; align-items: center; justify-content: space-between; }
.actions { display: flex; gap: 10px; }
</style>
