<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadUserFile } from 'element-plus'

import * as api from '@/api/candidates'
import type {
  Candidate,
  CandidateDetail,
  CandidatePayload,
  UploadItem,
} from '@/api/candidates'

const ACCEPT = '.pdf,.docx,.doc,.jpg,.jpeg,.png'
const MAX_MB = 20
const LOW_CONFIDENCE = 0.7

const FILE_STATUS: Record<string, { label: string; type: 'info' | 'warning' | 'success' | 'danger' }> = {
  pending: { label: '待解析', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  success: { label: '已解析', type: 'success' },
  failed: { label: '解析失败', type: 'danger' },
}

const EDUCATION_OPTIONS = [
  { value: 'college', label: '大专' },
  { value: 'bachelor', label: '本科' },
  { value: 'master', label: '硕士' },
  { value: 'phd', label: '博士' },
]

const EDUCATION_LABEL: Record<string, string> = {
  college: '大专',
  bachelor: '本科',
  master: '硕士',
  phd: '博士',
}

function fileStatus(status?: string | null) {
  return FILE_STATUS[status || ''] ?? { label: status || '未知', type: 'info' as const }
}

const router = useRouter()

function openDetail(id: number) {
  router.push(`/candidates/${id}`)
}

function educationText(value?: string | null): string {
  if (!value) return '—'
  return EDUCATION_LABEL[value] || value
}

function contactText(row: Candidate): string {
  return row.phone || row.email || '—'
}

// ---------------------------------------------------------------- 列表
const rows = ref<Candidate[]>([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const pageSize = ref(10)

async function loadCandidates() {
  loading.value = true
  try {
    const data = await api.listCandidates({
      q: keyword.value.trim() || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = data.items
    total.value = data.total
  } catch (e: any) {
    ElMessage.error(e.message || '加载候选人失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  void loadCandidates()
}

function onReset() {
  keyword.value = ''
  page.value = 1
  void loadCandidates()
}

function onPageChange(value: number) {
  page.value = value
  void loadCandidates()
}

// ---------------------------------------------------------------- 上传
const uploadOpen = ref(false)
const uploadFiles = ref<UploadUserFile[]>([])
const uploadResults = ref<UploadItem[]>([])
const uploading = ref(false)
let pollTimer: number | null = null

function stopPoll() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function extOf(name: string): string {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index).toLowerCase() : ''
}

function openUpload() {
  uploadResults.value = []
  uploadFiles.value = []
  uploadOpen.value = true
}

async function submitUpload() {
  const files = uploadFiles.value
    .map((item) => item.raw)
    .filter((item): item is NonNullable<typeof item> => Boolean(item))

  if (!files.length) {
    ElMessage.warning('请先选择简历文件')
    return
  }
  for (const file of files) {
    if (!ACCEPT.split(',').includes(extOf(file.name))) {
      ElMessage.error(`不支持的格式：${file.name}（仅支持 PDF / DOCX / 图片）`)
      return
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      ElMessage.error(`${file.name} 超过 ${MAX_MB}MB，请压缩后再上传`)
      return
    }
  }

  uploading.value = true
  try {
    const { items } = await api.uploadResumes(files)
    uploadResults.value = items
    const pollIds = items
      .filter((item) => item.file_id && ['pending', 'parsing'].includes(item.status))
      .map((item) => item.file_id as number)
    uploadFiles.value = []
    ElMessage.success(`已接收 ${items.length} 个文件`)
    if (pollIds.length) startPoll(pollIds)
    else await loadCandidates()
  } catch (e: any) {
    ElMessage.error(e.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

function startPoll(ids: number[], refreshReview = false) {
  stopPoll()
  let ticks = 0
  pollTimer = window.setInterval(async () => {
    ticks += 1
    try {
      const { items } = await api.getFileStatuses(ids)
      for (const status of items) {
        const target = uploadResults.value.find((item) => item.file_id === status.id)
        if (target) {
          target.status = status.status
          if (status.candidate_id) target.candidate_id = status.candidate_id
          if (status.error_reason) target.message = status.error_reason
        }
      }
      const pending = items.filter((item) => ['pending', 'parsing'].includes(item.status))
      if (!pending.length || ticks > 90) {
        stopPoll()
        await loadCandidates()
        if (refreshReview && reviewOpen.value && reviewForm.id != null) {
          await openReview(reviewForm.id)
        }
      }
    } catch {
      stopPoll()
    }
  }, 2000)
}

async function reparseFromUpload(item: UploadItem) {
  if (!item.file_id) return
  try {
    await api.reparseResumeFile(item.file_id)
    item.status = 'pending'
    item.message = '已重新提交解析'
    startPoll([item.file_id])
  } catch (e: any) {
    ElMessage.error(e.message || '重新解析失败')
  }
}

// ---------------------------------------------------------------- 校对
interface ReviewForm {
  id: number | null
  name: string
  phone: string
  email: string
  city: string
  education_level: string
  school: string
  major: string
  years_experience: number | undefined
  current_company: string
  current_title: string
  skills: string[]
}

function emptyReview(): ReviewForm {
  return {
    id: null,
    name: '',
    phone: '',
    email: '',
    city: '',
    education_level: '',
    school: '',
    major: '',
    years_experience: undefined,
    current_company: '',
    current_title: '',
    skills: [],
  }
}

const reviewOpen = ref(false)
const reviewLoading = ref(false)
const saving = ref(false)
const detail = ref<CandidateDetail | null>(null)
const reviewForm = reactive<ReviewForm>(emptyReview())

const isManual = computed(() => reviewForm.id == null)
const lowCount = computed(() => {
  const conf = detail.value?.field_confidence ?? {}
  return Object.values(conf).filter((value) => value < LOW_CONFIDENCE).length
})

function isLow(key: string): boolean {
  const conf = detail.value?.field_confidence ?? {}
  return typeof conf[key] === 'number' && conf[key] < LOW_CONFIDENCE
}

function applyDetail(data: CandidateDetail) {
  detail.value = data
  Object.assign(reviewForm, {
    id: data.id,
    name: data.name ?? '',
    phone: data.phone ?? '',
    email: data.email ?? '',
    city: data.city ?? '',
    education_level: data.education_level ?? '',
    school: data.school ?? '',
    major: data.major ?? '',
    years_experience: data.years_experience ?? undefined,
    current_company: data.current_company ?? '',
    current_title: data.current_title ?? '',
    skills: [...(data.skills || [])],
  })
}

async function openReview(id: number) {
  reviewLoading.value = true
  try {
    applyDetail(await api.getCandidate(id))
    reviewOpen.value = true
  } catch (e: any) {
    ElMessage.error(e.message || '加载候选人失败')
  } finally {
    reviewLoading.value = false
  }
}

function openManual() {
  detail.value = null
  Object.assign(reviewForm, emptyReview())
  reviewOpen.value = true
}

function buildPayload(): CandidatePayload {
  return {
    name: reviewForm.name.trim() || null,
    phone: reviewForm.phone.trim() || null,
    email: reviewForm.email.trim() || null,
    city: reviewForm.city.trim() || null,
    education_level: reviewForm.education_level || null,
    school: reviewForm.school.trim() || null,
    major: reviewForm.major.trim() || null,
    years_experience: reviewForm.years_experience ?? null,
    current_company: reviewForm.current_company.trim() || null,
    current_title: reviewForm.current_title.trim() || null,
    skills: reviewForm.skills,
  }
}

async function saveReview() {
  if (!reviewForm.name.trim()) {
    ElMessage.warning('请填写姓名后再保存')
    return
  }
  saving.value = true
  try {
    const payload = buildPayload()
    const data =
      reviewForm.id == null
        ? await api.createCandidate(payload)
        : await api.updateCandidate(reviewForm.id, payload)
    applyDetail(data)
    ElMessage.success('已保存')
    await loadCandidates()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function downloadFile(fileId: number) {
  try {
    const { url } = await api.downloadResumeFile(fileId)
    window.open(url, '_blank', 'noopener')
  } catch (e: any) {
    ElMessage.error(e.message || '获取下载链接失败')
  }
}

async function reparseFile(fileId: number) {
  try {
    await ElMessageBox.confirm('重新解析会覆盖当前结构化结果，确定继续吗？', '重新解析', {
      type: 'warning',
      confirmButtonText: '重新解析',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api.reparseResumeFile(fileId)
    ElMessage.success('已提交解析，稍后自动刷新')
    startPoll([fileId], true)
  } catch (e: any) {
    ElMessage.error(e.message || '重新解析失败')
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

onMounted(() => {
  void loadCandidates()
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>候选人</h1>
        <p class="sub">上传 PDF / DOCX / 图片 → 自动解析 → 校对字段 → 同人自动合并</p>
      </div>
      <div class="head-actions">
        <el-button @click="openManual">手动新增</el-button>
        <el-button type="primary" @click="openUpload">上传简历</el-button>
      </div>
    </header>

    <section class="panel">
      <div class="filters">
        <el-input
          v-model="keyword"
          placeholder="搜姓名 / 学校 / 当前公司"
          clearable
          style="width: 260px"
          @keyup.enter="onSearch"
        />
        <el-button @click="onSearch">搜索</el-button>
        <el-button link @click="onReset">重置</el-button>
      </div>

      <el-table v-loading="loading" :data="rows" class="table">
        <el-table-column label="候选人" min-width="150">
          <template #default="{ row }">
            <button class="name-link" type="button" @click="openDetail(row.id)">
              {{ row.name || '未识别' }}
            </button>
            <div class="meta">#{{ row.id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="联系方式" min-width="170">
          <template #default="{ row }">
            <div>{{ contactText(row) }}</div>
            <div v-if="row.phone && row.email" class="meta">{{ row.email }}</div>
          </template>
        </el-table-column>
        <el-table-column label="城市" width="100">
          <template #default="{ row }">{{ row.city || '—' }}</template>
        </el-table-column>
        <el-table-column label="学历 / 院校" min-width="150">
          <template #default="{ row }">
            <div>{{ educationText(row.education_level) }}</div>
            <div class="meta">{{ row.school || '—' }}<span v-if="row.major"> · {{ row.major }}</span></div>
          </template>
        </el-table-column>
        <el-table-column label="经验" width="80">
          <template #default="{ row }">
            {{ row.years_experience != null ? `${row.years_experience} 年` : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="当前公司 / 职位" min-width="160">
          <template #default="{ row }">
            <div>{{ row.current_company || '—' }}</div>
            <div class="meta">{{ row.current_title || '' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="技能" min-width="180">
          <template #default="{ row }">
            <el-tag
              v-for="skill in (row.skills || []).slice(0, 3)"
              :key="skill"
              size="small"
              class="skill-tag"
            >
              {{ skill }}
            </el-tag>
            <span v-if="(row.skills || []).length > 3" class="meta">
              +{{ row.skills.length - 3 }}
            </span>
            <span v-if="!(row.skills || []).length" class="meta">—</span>
          </template>
        </el-table-column>
        <el-table-column label="简历" width="110">
          <template #default="{ row }">
            <div class="meta">{{ row.file_count }} 份</div>
            <el-tag v-if="row.latest_status" size="small" :type="fileStatus(row.latest_status).type">
              {{ fileStatus(row.latest_status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="120">
          <template #default="{ row }">
            <span class="meta">{{ new Date(row.update_time).toLocaleDateString() }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row.id)">详情</el-button>
            <el-button link @click="openReview(row.id)">校对</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty">还没有候选人，点击右上角「上传简历」开始</div>
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

    <!-- 上传抽屉 -->
    <el-drawer v-model="uploadOpen" title="上传简历" size="560px">
      <el-upload
        v-model:file-list="uploadFiles"
        drag
        multiple
        :auto-upload="false"
        :accept="ACCEPT"
      >
        <div class="upload-title">拖拽文件到此处，或点击选择</div>
        <div class="upload-hint">支持 PDF / DOCX / JPG / PNG，单个文件不超过 {{ MAX_MB }}MB</div>
      </el-upload>
      <p class="tip">同一份文件重复上传会复用已有记录，不会重复解析；同一个人多份简历会合并为一条。</p>

      <div v-if="uploadResults.length" class="result-list">
        <div class="result-title">处理结果</div>
        <div v-for="item in uploadResults" :key="`${item.file_id}-${item.original_name}`" class="result-item">
          <div class="result-main">
            <div class="result-name">{{ item.original_name }}</div>
            <div class="meta">
              {{ formatSize(item.size_bytes) }}
              <span v-if="item.reused"> · 已复用已有文件</span>
            </div>
            <div v-if="item.message" class="result-msg" :class="{ error: item.status === 'failed' }">
              {{ item.message }}
            </div>
          </div>
          <div class="result-side">
            <el-tag size="small" :type="fileStatus(item.status).type">
              {{ fileStatus(item.status).label }}
            </el-tag>
            <el-button
              v-if="item.file_id && item.status === 'failed'"
              link
              type="primary"
              @click="reparseFromUpload(item)"
            >
              重试
            </el-button>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="drawer-footer">
          <span class="meta">解析失败的文件会提示手动录入</span>
          <div class="actions">
            <el-button @click="uploadOpen = false">关闭</el-button>
            <el-button type="primary" :loading="uploading" @click="submitUpload">
              上传并解析
            </el-button>
          </div>
        </div>
      </template>
    </el-drawer>

    <!-- 校对抽屉 -->
    <el-drawer
      v-model="reviewOpen"
      :title="isManual ? '手动新增候选人' : `校对候选人 #${reviewForm.id}`"
      size="720px"
    >
      <div v-loading="reviewLoading">
        <el-alert
          v-if="!isManual && lowCount"
          type="warning"
          :closable="false"
          show-icon
          :title="`有 ${lowCount} 个字段置信度较低（橙色底），请核对后再保存`"
          class="conf-alert"
        />

        <el-form label-width="92px" label-position="right">
          <div class="grid2">
            <el-form-item label="姓名" required :class="{ low: isLow('name') }">
              <el-input v-model="reviewForm.name" maxlength="100" placeholder="如：王鑫" />
            </el-form-item>
            <el-form-item label="手机号" :class="{ low: isLow('phone') }">
              <el-input v-model="reviewForm.phone" maxlength="30" placeholder="13800000000" />
            </el-form-item>
            <el-form-item label="邮箱" :class="{ low: isLow('email') }">
              <el-input v-model="reviewForm.email" maxlength="120" placeholder="name@example.com" />
            </el-form-item>
            <el-form-item label="城市" :class="{ low: isLow('city') }">
              <el-input v-model="reviewForm.city" maxlength="100" placeholder="如：上海" />
            </el-form-item>
            <el-form-item label="学历" :class="{ low: isLow('education') }">
              <el-select v-model="reviewForm.education_level" clearable placeholder="请选择">
                <el-option
                  v-for="item in EDUCATION_OPTIONS"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="院校" :class="{ low: isLow('education') }">
              <el-input v-model="reviewForm.school" maxlength="100" />
            </el-form-item>
            <el-form-item label="专业" :class="{ low: isLow('education') }">
              <el-input v-model="reviewForm.major" maxlength="100" />
            </el-form-item>
            <el-form-item label="工作年限" :class="{ low: isLow('years_experience') }">
              <el-input-number
                v-model="reviewForm.years_experience"
                :min="0"
                :max="50"
                :step="0.5"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="当前公司" :class="{ low: isLow('current_company') }">
              <el-input v-model="reviewForm.current_company" maxlength="100" />
            </el-form-item>
            <el-form-item label="当前职位" :class="{ low: isLow('current_title') }">
              <el-input v-model="reviewForm.current_title" maxlength="100" />
            </el-form-item>
          </div>

          <el-form-item label="技能" :class="{ low: isLow('skills') }">
            <el-select
              v-model="reviewForm.skills"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="输入技能后回车"
              style="width: 100%"
            >
              <el-option v-for="item in reviewForm.skills" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
        </el-form>

        <template v-if="detail?.structured">
          <div class="section-title">教育经历</div>
          <div v-if="detail.structured.education.length" class="timeline">
            <div v-for="(item, index) in detail.structured.education" :key="index" class="timeline-item">
              <div class="timeline-head">
                {{ item.school || '—' }}
                <span class="meta">{{ item.start || '—' }} ~ {{ item.end || '—' }}</span>
              </div>
              <div class="meta">{{ [item.degree, item.major].filter(Boolean).join(' · ') || '—' }}</div>
            </div>
          </div>
          <div v-else class="meta empty-line">未识别到教育经历</div>

          <div class="section-title">工作经历</div>
          <div v-if="detail.structured.work.length" class="timeline">
            <div v-for="(item, index) in detail.structured.work" :key="index" class="timeline-item">
              <div class="timeline-head">
                {{ item.company || '—' }} · {{ item.title || '—' }}
                <span class="meta">{{ item.start || '—' }} ~ {{ item.end || '—' }}</span>
              </div>
              <div v-if="item.description" class="desc">{{ item.description }}</div>
            </div>
          </div>
          <div v-else class="meta empty-line">未识别到工作经历（应届生正常）</div>

          <template v-if="detail.structured.projects.length">
            <div class="section-title">项目经历</div>
            <div class="timeline">
              <div v-for="(item, index) in detail.structured.projects" :key="index" class="timeline-item">
                <div class="timeline-head">{{ item.name || '—' }} · {{ item.role || '—' }}</div>
                <div v-if="item.stack?.length" class="meta">{{ item.stack.join(' / ') }}</div>
                <div v-if="item.description" class="desc">{{ item.description }}</div>
              </div>
            </div>
          </template>
        </template>

        <template v-if="detail?.files?.length">
          <div class="section-title">简历文件</div>
          <div v-for="file in detail.files" :key="file.id" class="file-row">
            <div>
              <div class="file-name">{{ file.original_name }}</div>
              <div class="meta">
                {{ formatSize(file.size_bytes) }} · {{ file.parser || '待解析' }}
                <span v-if="file.parsed_time"> · {{ new Date(file.parsed_time).toLocaleString() }}</span>
              </div>
              <div v-if="file.error_reason" class="result-msg error">{{ file.error_reason }}</div>
            </div>
            <div class="file-actions">
              <el-tag size="small" :type="fileStatus(file.status).type">
                {{ fileStatus(file.status).label }}
              </el-tag>
              <el-button link type="primary" @click="downloadFile(file.id)">下载</el-button>
              <el-button link @click="reparseFile(file.id)">重新解析</el-button>
            </div>
          </div>
        </template>

        <el-collapse v-if="detail?.plain_text" class="raw-text">
          <el-collapse-item title="查看简历原文" name="raw">
            <pre class="raw">{{ detail.plain_text }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>

      <template #footer>
        <div class="drawer-footer">
          <span class="meta">橙色底字段为低置信度，建议人工核对</span>
          <div class="actions">
            <el-button @click="reviewOpen = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="saveReview">保存</el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { max-width: 1320px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
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
.head-actions { display: flex; gap: 10px; }

.panel {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 16px 18px; box-shadow: var(--shadow-sm);
}
.filters { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }
.table { width: 100%; }
.name-link {
  padding: 0;
  border: none;
  background: none;
  font: inherit;
  font-weight: 600;
  color: var(--primary);
  cursor: pointer;
  text-align: left;
}
.name-link:hover {
  text-decoration: underline;
}
.meta { font-size: 12px; color: var(--muted); }
.skill-tag { margin: 0 6px 4px 0; }
.empty { color: var(--muted); padding: 24px 0; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }

.upload-title { font-weight: 600; color: var(--text); }
.upload-hint { color: var(--muted); font-size: 12px; margin-top: 4px; }
.tip { margin: 10px 0 0; font-size: 12px; color: var(--muted); }

.result-list { margin-top: 18px; }
.result-title { font-weight: 650; margin-bottom: 8px; }
.result-item {
  display: flex; justify-content: space-between; gap: 12px;
  padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; margin-bottom: 8px;
}
.result-main { min-width: 0; }
.result-name { font-weight: 600; word-break: break-all; }
.result-msg { font-size: 12px; color: #8a6d3b; margin-top: 4px; }
.result-msg.error { color: #dc2626; }
.result-side { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; column-gap: 10px; }
.conf-alert { margin-bottom: 14px; }

/* 低置信度字段：橙色底 */
:deep(.el-form-item.low .el-input__wrapper),
:deep(.el-form-item.low .el-select__wrapper),
:deep(.el-form-item.low .el-input-number .el-input__wrapper) {
  background: #fff7e8;
  box-shadow: 0 0 0 1px #f0b95a inset;
}

.section-title {
  margin: 18px 0 8px; font-weight: 650; font-size: 13.5px;
  padding-left: 9px; border-left: 3px solid #c7cbf8;
}
.timeline { display: flex; flex-direction: column; gap: 10px; }
.timeline-item {
  border: 1px solid var(--line); border-radius: 10px; padding: 9px 12px; background: #fafbff;
}
.timeline-head { display: flex; justify-content: space-between; gap: 10px; font-weight: 600; font-size: 13px; }
.desc { margin-top: 4px; font-size: 12.5px; color: #475467; white-space: pre-wrap; }
.empty-line { padding: 4px 0 2px; }
.raw-text { margin-top: 18px; }
.raw { white-space: pre-wrap; font-size: 12.5px; line-height: 1.7; color: #475467; margin: 0; }

.file-row {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  padding: 9px 12px; border: 1px solid var(--line); border-radius: 10px; margin-bottom: 8px;
}
.file-name { font-weight: 600; word-break: break-all; }
.file-actions { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }

.drawer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.actions { display: flex; gap: 10px; }

@media (max-width: 760px) {
  .grid2 { grid-template-columns: 1fr; }
  .page-head { flex-direction: column; }
}
</style>
