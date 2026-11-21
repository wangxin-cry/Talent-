<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import * as ragApi from '@/api/rag'
import type { RagHealth, ResumeHit } from '@/api/rag'
import * as jobsApi from '@/api/jobs'
import type { Job } from '@/api/jobs'
import * as appApi from '@/api/applications'

const router = useRouter()

const query = ref('')
const loading = ref(false)
const searched = ref(false)
const hits = ref<ResumeHit[]>([])
const health = ref<RagHealth | null>(null)

const dialogVisible = ref(false)
const selected = ref<ResumeHit | null>(null)
const jobs = ref<Job[]>([])
const selectedJobId = ref<number | null>(null)
const adding = ref(false)

const EXAMPLES = [
  '做过高并发订单系统',
  '熟悉 Kafka 实时计算',
  '有从 0 到 1 搭建团队经验',
  '做过推荐算法与特征工程',
]

const available = ref(false)

async function loadHealth() {
  try {
    health.value = await ragApi.getRagHealth()
    available.value = health.value.enabled && health.value.embedding_configured
  } catch {
    health.value = null
    available.value = false
  }
}

async function search() {
  const value = query.value.trim()
  if (!value) return
  loading.value = true
  try {
    const result = await ragApi.searchResumes({ query: value, top_k: 12 })
    hits.value = result.items
    available.value = result.available
    searched.value = true
    if (!result.available) {
      ElMessage.warning('知识库未启用，已降级为空结果')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '语义搜索失败')
  } finally {
    loading.value = false
  }
}

function useExample(text: string) {
  query.value = text
  search()
}

async function openAdd(hit: ResumeHit) {
  selected.value = hit
  selectedJobId.value = null
  dialogVisible.value = true
  if (!jobs.value.length) {
    try {
      const data = await jobsApi.listJobs({ status: 'published', page_size: 100 })
      jobs.value = data.items
    } catch (e: any) {
      ElMessage.error(e.message || '加载在招职位失败')
    }
  }
}

async function confirmAdd() {
  if (!selected.value || !selectedJobId.value) {
    ElMessage.warning('请选择要加入的职位')
    return
  }
  adding.value = true
  try {
    await appApi.createApplication({
      job_id: selectedJobId.value,
      candidate_id: selected.value.candidate_id,
      source: 'talent_pool',
    })
    ElMessage.success('已加入招聘流程')
    dialogVisible.value = false
    router.push('/board')
  } catch (e: any) {
    ElMessage.error(e.message || '加入流程失败')
  } finally {
    adding.value = false
  }
}

function scorePercent(score: number): string {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`
}

onMounted(loadHealth)
</script>

<template>
  <div class="talent-page">
    <header class="page-header">
      <div>
        <h2>人才库 · 语义搜索</h2>
        <p class="subtitle">
          用自然语言描述经历，按简历语义相似度召回，不受关键词字面限制
        </p>
      </div>
      <div v-if="health" class="health">
        <el-tag size="small" effect="plain">{{ health.backend === 'faiss' ? 'FAISS' : 'Numpy' }} 检索</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ health.embedding_model }}</el-tag>
        <span class="count">简历片段 {{ health.collections.resume || 0 }}</span>
      </div>
    </header>

    <el-alert
      v-if="health && !available"
      type="warning"
      :closable="false"
      show-icon
      title="知识库不可用"
      description="RAG 未启用或未配置 Embedding Key，搜索会返回空结果；面试题生成仍会正常降级。"
      class="alert"
    />

    <div class="search-bar">
      <el-input
        v-model="query"
        size="large"
        placeholder="例如：做过高并发订单系统，熟悉 Kafka 和 Flink"
        clearable
        @keyup.enter="search"
      />
      <el-button type="primary" size="large" :loading="loading" @click="search">搜索</el-button>
    </div>

    <div class="examples">
      <span class="examples-label">试试：</span>
      <el-button
        v-for="text in EXAMPLES"
        :key="text"
        link
        type="primary"
        @click="useExample(text)"
      >
        {{ text }}
      </el-button>
    </div>

    <div v-loading="loading" class="results">
      <div v-if="hits.length" class="grid">
        <article v-for="hit in hits" :key="hit.candidate_id" class="card">
          <div class="card-head">
            <div>
              <div class="name">{{ hit.name }}</div>
              <div class="title">
                {{ hit.current_title || '职位未知' }}
                <span v-if="hit.current_company"> · {{ hit.current_company }}</span>
              </div>
            </div>
            <div class="score">
              <span class="score-value">{{ scorePercent(hit.score) }}</span>
              <span class="score-label">相似度</span>
            </div>
          </div>

          <div class="facts">
            <span v-if="hit.years_experience !== null">{{ hit.years_experience }} 年经验</span>
            <span v-if="hit.city">{{ hit.city }}</span>
          </div>

          <div v-if="hit.skills.length" class="skills">
            <el-tag v-for="skill in hit.skills" :key="skill" size="small" effect="plain">
              {{ skill }}
            </el-tag>
          </div>

          <div class="snippets">
            <p v-for="(snippet, index) in hit.snippets" :key="index" class="snippet">
              {{ snippet }}
            </p>
          </div>

          <div class="card-actions">
            <el-button type="primary" plain size="small" @click="openAdd(hit)">加入流程</el-button>
          </div>
        </article>
      </div>

      <el-empty
        v-else-if="searched"
        description="没有召回到相似简历，换个描述试试"
      />
      <el-empty v-else description="输入一段经历描述，搜索相似候选人" />
    </div>

    <el-dialog v-model="dialogVisible" title="加入招聘流程" width="460px">
      <div v-if="selected" class="dialog-candidate">
        <strong>{{ selected.name }}</strong>
        <span>{{ selected.current_title || '职位未知' }}</span>
      </div>
      <el-select v-model="selectedJobId" placeholder="选择在招职位" style="width: 100%">
        <el-option
          v-for="job in jobs"
          :key="job.id"
          :label="`${job.title}${job.department ? ` · ${job.department}` : ''}`"
          :value="job.id"
        />
      </el-select>
      <p v-if="!jobs.length" class="dialog-hint">暂无在招职位，请先发布职位</p>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="confirmAdd">确认加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.talent-page {
  max-width: 1180px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
.subtitle {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 13px;
}
.health {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.count {
  font-size: 12px;
  color: var(--muted);
}
.alert {
  margin-bottom: 14px;
}
.search-bar {
  display: flex;
  gap: 10px;
}
.search-bar :deep(.el-input) {
  flex: 1;
}
.examples {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin: 10px 0 18px;
}
.examples-label {
  font-size: 12px;
  color: var(--muted);
}
.results {
  min-height: 220px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.name {
  font-size: 16px;
  font-weight: 700;
}
.title {
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--muted);
}
.score {
  text-align: right;
}
.score-value {
  display: block;
  font-size: 20px;
  font-weight: 750;
  color: var(--primary);
  line-height: 1.1;
}
.score-label {
  font-size: 11px;
  color: var(--muted);
}
.facts {
  display: flex;
  gap: 12px;
  font-size: 12.5px;
  color: var(--muted);
}
.skills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.snippets {
  border-top: 1px dashed var(--line);
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.snippet {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text);
}
.card-actions {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
}
.dialog-candidate {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-bottom: 14px;
  font-size: 13px;
}
.dialog-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--muted);
}
</style>
