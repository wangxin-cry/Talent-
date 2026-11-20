<script setup lang="ts">
import { onMounted, ref } from 'vue'
import client from '@/api/client'

interface ComponentStatus {
  ok: boolean
  detail: string
  backend: string
}

interface HealthResponse {
  status: string
  app: string
  version: string
  env: string
  components: {
    database: ComponentStatus
    storage: ComponentStatus
  }
}

const health = ref<HealthResponse | null>(null)
const error = ref<string>('')
const loading = ref(true)

async function fetchHealth() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await client.get<HealthResponse>('/healthz')
    health.value = data
  } catch (e: any) {
    error.value = e?.message ?? '无法连接后端'
  } finally {
    loading.value = false
  }
}

onMounted(fetchHealth)

const nextSteps = [
  '阶段一：MinIO + PostgreSQL 就绪，13 张核心表（进行中）',
  '阶段二：注册登录与三角色权限',
  '阶段三：职位管理 + AI 生成 JD',
  '阶段四：简历上传（MinIO）与多格式解析',
  '阶段五：可解释的人岗匹配',
]
</script>

<template>
  <div class="home">
    <section class="hero">
      <h1>TalentMatch</h1>
      <p>AI 驱动的企业智能招聘 Agent 平台 · 阶段一骨架</p>
    </section>

    <section class="status-card">
      <div class="head">
        <span class="dot" :class="{ ok: health?.status === 'ok' }"></span>
        <strong>后端连通性</strong>
        <button class="refresh" @click="fetchHealth">重新检测</button>
      </div>

      <p v-if="loading" class="muted">检测中…</p>
      <p v-else-if="error" class="err">连接失败：{{ error }}（确认后端已在 8000 端口启动）</p>

      <div v-else-if="health" class="grid">
        <div class="item">
          <div class="label">整体状态</div>
          <div class="value" :class="health.status">{{ health.status }}</div>
        </div>
        <div class="item">
          <div class="label">版本 / 环境</div>
          <div class="value">{{ health.version }} · {{ health.env }}</div>
        </div>
        <div class="item">
          <div class="label">数据库（{{ health.components.database.backend }}）</div>
          <div class="value" :class="{ ok: health.components.database.ok }">
            {{ health.components.database.ok ? 'ok' : '异常' }}
          </div>
          <div class="detail">{{ health.components.database.detail }}</div>
        </div>
        <div class="item">
          <div class="label">对象存储（{{ health.components.storage.backend }}）</div>
          <div class="value" :class="{ ok: health.components.storage.ok }">
            {{ health.components.storage.ok ? 'ok' : '异常' }}
          </div>
          <div class="detail">{{ health.components.storage.detail }}</div>
        </div>
      </div>
    </section>

    <section class="steps">
      <h2>接下来</h2>
      <ul>
        <li v-for="s in nextSteps" :key="s">{{ s }}</li>
      </ul>
      <p class="muted small">
        设计文档见项目 docs/ 目录：项目设计方案、数据库设计、对话式交互设计。
      </p>
    </section>
  </div>
</template>

<style scoped>
.home { max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; }
.hero h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -.5px; }
.hero p { margin: 0; color: var(--muted); }

.status-card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 16px 18px; box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
}
.head { display: flex; align-items: center; gap: 9px; margin-bottom: 12px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: #d1d5db; }
.dot.ok { background: #16a34a; }
.refresh {
  margin-left: auto; border: 1px solid var(--line); background: #fff;
  border-radius: 8px; padding: 4px 11px; font-size: 12.5px; color: var(--muted); cursor: pointer;
}
.refresh:hover { border-color: var(--primary); color: var(--primary); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.item { background: #fafbfe; border: 1px solid var(--line); border-radius: 10px; padding: 11px 13px; }
.label { font-size: 12px; color: var(--muted); }
.value { font-size: 15px; font-weight: 700; margin-top: 4px; }
.value.ok { color: #16a34a; }
.value.degraded { color: #d97706; }
.detail { font-size: 11.5px; color: #9aa1ad; margin-top: 4px; word-break: break-all; }
.muted { color: var(--muted); }
.err { color: #dc2626; }
.small { font-size: 12px; }
.steps { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; }
.steps h2 { margin: 0 0 10px; font-size: 16px; }
.steps ul { margin: 0; padding-left: 20px; line-height: 2; color: #3b4152; }
</style>
