<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

import * as publicApi from '@/api/public'
import type { Progress } from '@/api/public'

const route = useRoute()
const form = reactive({ token: '', email: '' })
const loading = ref(false)
const progress = ref<Progress | null>(null)

function formatTime(value?: string | null): string {
  if (!value) return ''
  return value.replace('T', ' ').slice(0, 16)
}

async function query() {
  if (!form.token.trim() || !form.email.trim()) {
    ElMessage.warning('请输入查询码与投递邮箱')
    return
  }
  loading.value = true
  progress.value = null
  try {
    progress.value = await publicApi.getProgress(form.token.trim(), form.email.trim())
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '查询失败，请核对查询码与邮箱')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (typeof route.query.token === 'string') form.token = route.query.token
  if (typeof route.query.email === 'string') form.email = route.query.email
  if (form.token && form.email) void query()
})
</script>

<template>
  <div class="status-page">
    <div class="status-card">
      <header class="head">
        <p class="tag">TalentMatch · 招聘官网</p>
        <h1>投递进度查询</h1>
        <p class="sub">输入投递成功后获得的查询码与邮箱，查看当前进度。</p>
      </header>

      <div class="query-form">
        <div class="field">
          <label>进度查询码</label>
          <el-input v-model="form.token" placeholder="投递成功后生成的查询码" clearable @keyup.enter="query" />
        </div>
        <div class="field">
          <label>投递邮箱</label>
          <el-input v-model="form.email" placeholder="投递时填写的邮箱" clearable @keyup.enter="query" />
        </div>
        <el-button type="primary" :loading="loading" @click="query">查询进度</el-button>
      </div>

      <div v-if="progress" class="result">
        <div class="result-head">
          <div>
            <h2>{{ progress.job_title }}</h2>
            <p class="sub">
              投递人：{{ progress.candidate_name || '-' }}
              <template v-if="progress.applied_at"> · 投递于 {{ formatTime(progress.applied_at) }}</template>
            </p>
          </div>
          <el-tag type="primary" effect="light">{{ progress.status_label }}</el-tag>
        </div>

        <div class="notice" v-if="progress.interview_at">
          <strong>面试安排</strong>
          <span>{{ formatTime(progress.interview_at) }}，请留意邮件通知并提前 10 分钟准备。</span>
        </div>
        <div class="notice done" v-if="progress.message">
          <span>{{ progress.message }}</span>
        </div>

        <ol class="steps">
          <li
            v-for="step in progress.steps"
            :key="step.status"
            :class="{ reached: step.reached, current: step.current, end: step.status === 'rejected' }"
          >
            <span class="dot"></span>
            <div class="step-body">
              <span class="step-label">{{ step.label }}</span>
              <span class="step-time">{{ formatTime(step.time) || '—' }}</span>
            </div>
          </li>
        </ol>
      </div>

      <router-link class="back" :to="{ name: 'careers' }">← 返回在招职位</router-link>
    </div>
  </div>
</template>

<style scoped>
.status-page {
  min-height: 100%;
  background: #f6f7fb;
  padding: 46px 20px 70px;
}
.status-card {
  max-width: 680px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #e8eaf3;
  border-radius: 16px;
  padding: 34px 34px 28px;
  box-shadow: 0 24px 60px -46px rgba(31, 35, 51, 0.35);
}
.tag {
  margin: 0 0 10px;
  font-size: 12px;
  letter-spacing: 0.16em;
  color: #6366f1;
  font-weight: 700;
}
.head h1 {
  margin: 0;
  font-size: 25px;
  color: #1f2333;
}
.sub {
  margin: 8px 0 0;
  font-size: 13px;
  color: #7a8091;
}
.query-form {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 12px;
  align-items: end;
  margin: 22px 0 6px;
}
.field label {
  display: block;
  font-size: 12.5px;
  color: #5b6172;
  margin-bottom: 6px;
}
.result {
  margin-top: 22px;
  border-top: 1px solid #eef0f6;
  padding-top: 20px;
}
.result-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.result-head h2 {
  margin: 0;
  font-size: 18px;
  color: #1f2333;
}
.notice {
  margin-top: 14px;
  background: #eef2ff;
  border: 1px solid #dbe2ff;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 13px;
  color: #3f4a86;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.notice.done {
  background: #fff7ed;
  border-color: #fed7aa;
  color: #9a3412;
}
.steps {
  list-style: none;
  margin: 20px 0 0;
  padding: 0 0 0 6px;
}
.steps li {
  position: relative;
  padding: 0 0 20px 26px;
  border-left: 2px solid #e6e9f5;
  margin-left: 6px;
}
.steps li:last-child {
  border-left-color: transparent;
  padding-bottom: 0;
}
.steps .dot {
  position: absolute;
  left: -8px;
  top: 1px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #d4d9ea;
}
.steps li.reached .dot {
  border-color: #6366f1;
  background: #6366f1;
}
.steps li.current .dot {
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.16);
}
.steps li.end .dot {
  border-color: #f97316;
  background: #f97316;
}
.step-body {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.step-label {
  font-size: 13.5px;
  color: #8a90a0;
  font-weight: 600;
}
.steps li.reached .step-label {
  color: #1f2333;
}
.step-time {
  font-size: 11.5px;
  color: #9aa0af;
}
.back {
  display: inline-block;
  margin-top: 22px;
  font-size: 12.5px;
  color: #6366f1;
  text-decoration: none;
}
@media (max-width: 700px) {
  .status-card {
    padding: 24px 20px;
  }
  .query-form {
    grid-template-columns: 1fr;
  }
}
</style>
