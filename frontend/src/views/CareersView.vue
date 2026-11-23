<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import * as publicApi from '@/api/public'
import type { PublicJob } from '@/api/public'

const route = useRoute()
const router = useRouter()

const jobs = ref<PublicJob[]>([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')

const job = ref<PublicJob | null>(null)
const detailLoading = ref(false)

const form = reactive({ name: '', email: '', phone: '', note: '' })
const resumeFile = ref<File | null>(null)
const submitting = ref(false)
const result = ref<{ tracking_token: string; job_title: string; message: string } | null>(null)

const jobId = computed(() => (route.params.id ? Number(route.params.id) : null))
const companySlug = computed(() => String(route.params.slug || ''))

async function loadJobs() {
  if (!companySlug.value) return
  loading.value = true
  try {
    const data = await publicApi.listJobs({
      slug: companySlug.value,
      keyword: keyword.value || undefined,
      page: 1,
      page_size: 50,
    })
    jobs.value = data.items
    total.value = data.total
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载在招职位失败')
  } finally {
    loading.value = false
  }
}

async function loadJob(id: number) {
  if (!companySlug.value) return
  detailLoading.value = true
  result.value = null
  try {
    job.value = await publicApi.getJob(companySlug.value, id)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '职位不存在或已下线')
    job.value = null
  } finally {
    detailLoading.value = false
  }
}

watch(
  jobId,
  (id) => {
    if (id) void loadJob(id)
    else {
      job.value = null
      result.value = null
    }
  },
  { immediate: true },
)

watch(companySlug, () => void loadJobs(), { immediate: true })

function salaryText(item: PublicJob): string {
  if (!item.salary_min && !item.salary_max) return '薪资面议'
  if (item.salary_min && item.salary_max) return `${item.salary_min}-${item.salary_max}K`
  return `${item.salary_min || item.salary_max}K`
}

function workModeText(mode: string | null): string {
  return { onsite: '现场办公', hybrid: '混合办公', remote: '远程' }[mode || ''] || '—'
}

function educationText(level: string | null): string {
  return { any: '不限', college: '大专', bachelor: '本科', master: '硕士', phd: '博士' }[level || ''] || '不限'
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  resumeFile.value = input.files?.[0] || null
}

async function submitApply() {
  if (!job.value) return
  if (!form.name.trim() || form.name.trim().length < 2) {
    ElMessage.warning('请填写真实姓名')
    return
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
    ElMessage.warning('请填写有效邮箱')
    return
  }
  if (form.phone && !/^1[3-9]\d{9}$/.test(form.phone.trim())) {
    ElMessage.warning('请输入 11 位手机号')
    return
  }
  submitting.value = true
  try {
    const data = await publicApi.applyJob({
      companySlug: companySlug.value,
      jobId: job.value.id,
      name: form.name.trim(),
      email: form.email.trim(),
      phone: form.phone.trim() || undefined,
      note: form.note.trim() || undefined,
      resume: resumeFile.value,
    })
    result.value = data
    ElMessage.success(data.message)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '投递失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

function goStatus() {
  router.push({
    name: 'careers-status',
    query: { token: result.value?.tracking_token, email: form.email.trim() },
  })
}
</script>

<template>
  <div class="careers">
    <header class="hero">
      <div class="hero-inner">
        <p class="hero-tag">TalentMatch · 招聘官网</p>
        <h1>和优秀的人，做有挑战的事</h1>
        <p class="hero-sub">在招 {{ total }} 个职位 · 投递后可凭查询码实时跟踪进度</p>
        <div class="hero-actions">
          <el-input
            v-model="keyword"
            class="search"
            placeholder="搜索职位名称，如 后端工程师"
            clearable
            @keyup.enter="loadJobs"
            @clear="loadJobs"
          >
            <template #append>
              <el-button @click="loadJobs">搜索</el-button>
            </template>
          </el-input>
          <router-link class="status-link" :to="{ name: 'careers-status' }">查询投递进度 →</router-link>
        </div>
      </div>
    </header>

    <main class="body">
      <el-empty
        v-if="!companySlug"
        description="请使用公司提供的招聘官网链接（包含公司标识）访问"
      />
      <!-- 职位列表 -->
      <template v-else-if="!jobId">
        <div v-loading="loading" class="job-grid">
          <article
            v-for="item in jobs"
            :key="item.id"
            class="job-card"
            @click="router.push({ name: 'career-detail', params: { slug: companySlug, id: item.id } })"
          >
            <div class="job-card-head">
              <h2>{{ item.title }}</h2>
              <span class="salary">{{ salaryText(item) }}</span>
            </div>
            <p class="job-meta">
              {{ item.department || '未分组' }} · {{ item.location || '地点待定' }} ·
              {{ workModeText(item.work_mode) }}
            </p>
            <p class="job-desc">{{ (item.description || '期待你的加入').slice(0, 90) }}</p>
            <div class="job-foot">
              <el-tag size="small" effect="plain">招 {{ item.headcount }} 人</el-tag>
              <el-tag size="small" effect="plain">{{ educationText(item.education_level) }}</el-tag>
              <el-tag v-if="item.min_years" size="small" effect="plain">{{ item.min_years }}+ 年</el-tag>
              <span class="arrow">查看详情 →</span>
            </div>
          </article>
          <el-empty v-if="!loading && !jobs.length" description="暂无在招职位，欢迎稍后再来看看" />
        </div>
      </template>

      <!-- 职位详情 + 投递 -->
      <template v-else>
        <button class="back" @click="router.push({ name: 'career-list', params: { slug: companySlug } })">← 返回职位列表</button>
        <div v-loading="detailLoading" class="detail-layout">
          <article v-if="job" class="detail">
            <div class="detail-head">
              <div>
                <h2>{{ job.title }}</h2>
                <p class="job-meta">
                  {{ job.department || '未分组' }} · {{ job.location || '地点待定' }} ·
                  {{ workModeText(job.work_mode) }} · {{ educationText(job.education_level) }}
                  <template v-if="job.min_years"> · {{ job.min_years }} 年以上</template>
                </p>
              </div>
              <span class="salary big">{{ salaryText(job) }}</span>
            </div>
            <section>
              <h3>职位描述</h3>
              <p class="plain">{{ job.description || '暂无描述' }}</p>
            </section>
            <section>
              <h3>任职要求</h3>
              <p class="plain">{{ job.requirements || '暂无要求' }}</p>
            </section>
          </article>

          <aside class="apply-panel">
            <div v-if="result" class="apply-result">
              <h3>投递成功</h3>
              <p>{{ result.message }}</p>
              <p class="result-job">{{ result.job_title }}</p>
              <div class="token-box">
                <span class="token-label">进度查询码</span>
                <code>{{ result.tracking_token }}</code>
              </div>
              <p class="tip">请保存查询码，与投递邮箱一起用于查询进度。</p>
              <el-button type="primary" class="full" @click="goStatus">查看投递进度</el-button>
            </div>

            <template v-else>
              <h3>立即投递</h3>
              <p class="panel-tip">填写信息并上传简历，我们会在 3 个工作日内反馈。</p>
              <div class="field">
                <label>姓名 *</label>
                <el-input v-model="form.name" maxlength="50" placeholder="你的姓名" />
              </div>
              <div class="field">
                <label>邮箱 *</label>
                <el-input v-model="form.email" maxlength="120" placeholder="用于接收进度通知" />
              </div>
              <div class="field">
                <label>手机号</label>
                <el-input v-model="form.phone" maxlength="11" placeholder="选填，便于联系" />
              </div>
              <div class="field">
                <label>简历附件</label>
                <input class="file-input" type="file" accept=".pdf,.docx,.doc,.jpg,.jpeg,.png" @change="onFileChange" />
                <p class="file-hint">支持 PDF / DOCX / 图片，单个不超过 10MB</p>
              </div>
              <div class="field">
                <label>补充说明</label>
                <el-input v-model="form.note" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="选填" />
              </div>
              <el-button type="primary" class="full" :loading="submitting" @click="submitApply">
                提交投递
              </el-button>
              <p class="privacy">提交即表示同意我们在招聘流程内使用你的信息。</p>
            </template>
          </aside>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
.careers {
  min-height: 100%;
  background: #f6f7fb;
}
.hero {
  background:
    radial-gradient(900px 320px at 12% -10%, rgba(99, 102, 241, 0.22), transparent 70%),
    radial-gradient(700px 260px at 88% 0%, rgba(139, 92, 246, 0.18), transparent 70%),
    #fff;
  border-bottom: 1px solid #e8eaf3;
}
.hero-inner {
  max-width: 1080px;
  margin: 0 auto;
  padding: 56px 24px 40px;
}
.hero-tag {
  margin: 0 0 12px;
  font-size: 12.5px;
  letter-spacing: 0.16em;
  color: #6366f1;
  font-weight: 700;
}
.hero h1 {
  margin: 0;
  font-size: 34px;
  letter-spacing: -0.02em;
  color: #1f2333;
}
.hero-sub {
  margin: 10px 0 22px;
  color: #6b7180;
  font-size: 14px;
}
.hero-actions {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}
.search {
  max-width: 420px;
}
.status-link {
  font-size: 13.5px;
  color: #4f46e5;
  font-weight: 600;
  text-decoration: none;
}
.status-link:hover {
  text-decoration: underline;
}
.body {
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}
.job-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
  min-height: 120px;
}
.job-card {
  background: #fff;
  border: 1px solid #e8eaf3;
  border-radius: 14px;
  padding: 18px 20px;
  cursor: pointer;
  transition: 0.18s;
}
.job-card:hover {
  border-color: #c7ccfa;
  box-shadow: 0 14px 30px -22px rgba(79, 70, 229, 0.5);
  transform: translateY(-2px);
}
.job-card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.job-card h2 {
  margin: 0;
  font-size: 16px;
  color: #1f2333;
}
.salary {
  color: #e0592a;
  font-weight: 700;
  font-size: 13.5px;
  white-space: nowrap;
}
.salary.big {
  font-size: 20px;
}
.job-meta {
  margin: 6px 0 0;
  color: #7a8091;
  font-size: 12.5px;
}
.job-desc {
  margin: 10px 0 0;
  color: #525869;
  font-size: 13px;
  line-height: 1.65;
  min-height: 42px;
}
.job-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
}
.arrow {
  margin-left: auto;
  font-size: 12px;
  color: #6366f1;
  opacity: 0;
  transition: 0.18s;
}
.job-card:hover .arrow {
  opacity: 1;
}
.back {
  border: none;
  background: transparent;
  color: #6366f1;
  font-size: 13px;
  cursor: pointer;
  padding: 0;
  margin-bottom: 14px;
}
.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, 1fr);
  gap: 18px;
  align-items: start;
}
.detail {
  background: #fff;
  border: 1px solid #e8eaf3;
  border-radius: 14px;
  padding: 24px 26px;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #eef0f6;
}
.detail h2 {
  margin: 0;
  font-size: 22px;
  color: #1f2333;
}
.detail section {
  margin-top: 20px;
}
.detail h3 {
  margin: 0 0 8px;
  font-size: 14.5px;
  color: #1f2333;
}
.plain {
  margin: 0;
  color: #4d5363;
  font-size: 13.5px;
  line-height: 1.85;
  white-space: pre-wrap;
}
.apply-panel {
  background: #fff;
  border: 1px solid #e8eaf3;
  border-radius: 14px;
  padding: 22px;
  position: sticky;
  top: 16px;
}
.apply-panel h3 {
  margin: 0 0 4px;
  font-size: 16px;
  color: #1f2333;
}
.panel-tip {
  margin: 0 0 16px;
  font-size: 12.5px;
  color: #7a8091;
}
.field {
  margin-bottom: 13px;
}
.field label {
  display: block;
  font-size: 12.5px;
  color: #5b6172;
  margin-bottom: 6px;
}
.file-input {
  width: 100%;
  font-size: 12.5px;
  color: #5b6172;
}
.file-hint {
  margin: 5px 0 0;
  font-size: 11.5px;
  color: #9aa0af;
}
.full {
  width: 100%;
  margin-top: 6px;
}
.privacy {
  margin: 10px 0 0;
  font-size: 11.5px;
  color: #9aa0af;
  line-height: 1.6;
}
.apply-result h3 {
  margin-bottom: 8px;
}
.apply-result p {
  font-size: 13px;
  color: #4d5363;
  line-height: 1.7;
}
.result-job {
  font-weight: 700;
  color: #1f2333 !important;
}
.token-box {
  margin: 14px 0;
  background: #f4f5ff;
  border: 1px dashed #c7ccfa;
  border-radius: 10px;
  padding: 12px 14px;
}
.token-label {
  display: block;
  font-size: 11.5px;
  color: #7a8091;
  margin-bottom: 5px;
}
.token-box code {
  font-size: 15px;
  font-weight: 700;
  color: #4338ca;
  word-break: break-all;
}
.tip {
  font-size: 12px;
  color: #9aa0af;
  margin: 0 0 12px;
}
@media (max-width: 900px) {
  .detail-layout {
    grid-template-columns: 1fr;
  }
  .apply-panel {
    position: static;
  }
  .hero h1 {
    font-size: 26px;
  }
}
</style>
