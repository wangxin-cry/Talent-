<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import * as analyticsApi from '@/api/analytics'
import type { Dashboard, SlaResult } from '@/api/analytics'

const data = ref<Dashboard | null>(null)
const sla = ref<SlaResult | null>(null)
const loading = ref(false)
const exporting = ref(false)

const overview = computed(() => data.value?.overview)
const forwardStages = computed(
  () => data.value?.funnel.filter((stage) => stage.status !== 'rejected') || [],
)
const rejectedStage = computed(() => data.value?.funnel.find((stage) => stage.status === 'rejected'))

const cycleStages = computed(() => data.value?.cycle || [])
const channels = computed(() => data.value?.channels || [])

const funnelMax = computed(() =>
  Math.max(1, ...forwardStages.value.map((stage) => stage.count)),
)
const channelMax = computed(() =>
  Math.max(1, ...channels.value.map((channel) => channel.total)),
)
const cycleMax = computed(() =>
  Math.max(1, ...cycleStages.value.map((stage) => stage.avg_hours || 0)),
)

function barWidth(count: number, max: number): string {
  return `${Math.max(4, (count / max) * 100)}%`
}

function percent(value: number | null): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(0)}%`
}

function avgTime(hours: number | null): string {
  if (hours === null || hours === undefined) return '—'
  if (hours < 24) return `${hours.toFixed(1)} 小时`
  return `${(hours / 24).toFixed(1)} 天`
}

function cycleDays(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(1)} 天`
}

async function load() {
  loading.value = true
  try {
    const [dashboard, slaResult] = await Promise.all([
      analyticsApi.getDashboard(),
      analyticsApi.getSla(),
    ])
    data.value = dashboard
    sla.value = slaResult
  } catch (e: any) {
    ElMessage.error(e.message || '加载数据看板失败')
  } finally {
    loading.value = false
  }
}

async function exportReport() {
  exporting.value = true
  try {
    const blob = await analyticsApi.downloadReport()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `talentmatch-report-${new Date().toISOString().slice(0, 10)}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('报表已开始下载')
  } catch (e: any) {
    ElMessage.error(e.message || '导出报表失败')
  } finally {
    exporting.value = false
  }
}

function hoursText(hours: number): string {
  if (hours < 24) return `${hours.toFixed(1)} 小时`
  return `${(hours / 24).toFixed(1)} 天`
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="dashboard-page">
    <div class="page-header">
      <div>
        <h2>招聘数据看板</h2>
        <p class="subtitle">指标、漏斗、渠道与周期均来自数据库实时统计</p>
      </div>
      <div class="header-actions">
        <el-button @click="load">刷新</el-button>
        <el-button :loading="exporting" @click="exportReport">导出 Excel</el-button>
        <el-button type="primary" plain @click="$router.push('/costs')">查看成本</el-button>
      </div>
    </div>

    <template v-if="overview">
      <section class="kpi-grid">
        <article class="kpi">
          <span class="kpi-label">在招职位</span>
          <span class="kpi-value">{{ overview.open_jobs }}</span>
          <span class="kpi-hint">状态为招聘中</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">投递总数</span>
          <span class="kpi-value">{{ overview.total_applications }}</span>
          <span class="kpi-hint">全部应聘记录</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">待面试</span>
          <span class="kpi-value accent">{{ overview.pending_interview }}</span>
          <span class="kpi-hint">当前处于面试阶段</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">平均招聘周期</span>
          <span class="kpi-value">{{ cycleDays(overview.avg_cycle_days) }}</span>
          <span class="kpi-hint">投递到入职，已入职样本</span>
        </article>
      </section>

      <section v-if="sla && sla.total" class="sla-panel">
        <div class="panel-head">
          <h3>SLA 超时提醒（{{ sla.total }}）</h3>
          <span class="panel-hint">超过阶段阈值仍未推进，建议优先处理</span>
        </div>
        <div class="sla-list">
          <div
            v-for="item in sla.items.slice(0, 8)"
            :key="item.application_id"
            class="sla-item"
            @click="$router.push(`/applications/${item.application_id}/prep`)"
          >
            <div class="sla-main">
              <strong>{{ item.candidate_name || '候选人' }}</strong>
              <span class="sla-job">{{ item.job_title || '职位已下线' }}</span>
            </div>
            <el-tag size="small" type="warning" effect="plain">{{ item.status_label }}</el-tag>
            <span class="sla-time">
              已停留 {{ hoursText(item.hours_in_stage) }}
              <em>超 {{ hoursText(item.overdue_hours) }}</em>
            </span>
          </div>
        </div>
        <p v-if="sla.total > 8" class="muted">仅展示超时最久的 8 条，完整数据见导出的 Excel。</p>
      </section>

      <div class="panel-grid">
        <section class="panel">
          <div class="panel-head">
            <h3>招聘漏斗</h3>
            <span class="panel-hint">转化率相对上一阶段</span>
          </div>
          <div class="funnel-head">
            <span>阶段</span>
            <span>人数分布</span>
            <span class="num">人数</span>
            <span class="num">转化</span>
          </div>
          <div v-for="stage in forwardStages" :key="stage.status" class="funnel-row">
            <span class="funnel-label">{{ stage.label }}</span>
            <div class="funnel-track">
              <div class="funnel-fill" :style="{ width: barWidth(stage.count, funnelMax) }">
                <span class="funnel-share">{{ (stage.share * 100).toFixed(0) }}%</span>
              </div>
            </div>
            <span class="num strong">{{ stage.count }}</span>
            <span class="num">{{ percent(stage.conversion) }}</span>
          </div>
          <div v-if="rejectedStage" class="rejected-row">
            <span class="rejected-dot"></span>
            {{ rejectedStage.label }} {{ rejectedStage.count }} 人
            <span class="muted">（占全部 {{ (rejectedStage.share * 100).toFixed(0) }}%）</span>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h3>阶段平均停留</h3>
            <span class="panel-hint">来自流转历史</span>
          </div>
          <div v-for="stage in cycleStages" :key="stage.stage" class="cycle-row">
            <div class="cycle-main">
              <span class="cycle-label">{{ stage.label }}</span>
              <span class="cycle-value">{{ avgTime(stage.avg_hours) }}</span>
            </div>
            <div class="cycle-bar">
              <div
                class="cycle-bar-fill"
                :style="{ width: barWidth(stage.avg_hours || 0, cycleMax) }"
              ></div>
            </div>
            <span class="cycle-samples">{{ stage.samples }} 个样本</span>
          </div>
          <p v-if="!cycleStages.length" class="muted">暂无流转数据</p>
        </section>
      </div>

      <section class="panel">
        <div class="panel-head">
          <h3>渠道对比</h3>
          <span class="panel-hint">投递量 · 入职量 · 转化率</span>
        </div>
        <div v-if="channels.length" class="channel-list">
          <div v-for="channel in channels" :key="channel.source" class="channel-row">
            <span class="channel-name">{{ channel.source }}</span>
            <div class="channel-track">
              <div class="channel-fill" :style="{ width: barWidth(channel.total, channelMax) }">
                <div
                  class="channel-hired"
                  :style="{ width: channel.total ? `${(channel.hired / channel.total) * 100}%` : '0%' }"
                ></div>
              </div>
            </div>
            <span class="channel-stat">
              <strong>{{ channel.total }}</strong> 投递
              <span class="ok">· {{ channel.hired }} 入职</span>
              <span class="miss">· {{ channel.rejected }} 淘汰</span>
            </span>
            <span class="channel-conv">{{ (channel.conversion * 100).toFixed(1) }}%</span>
          </div>
        </div>
        <p v-else class="muted">暂无投递数据</p>
        <div v-if="channels.length" class="legend">
          <span><i class="dot total"></i>投递总数</span>
          <span><i class="dot hired"></i>已入职</span>
        </div>
      </section>
    </template>

    <el-empty v-else-if="!loading" description="暂无数据" />
  </div>
</template>

<style scoped>
.dashboard-page {
  max-width: 1280px;
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
  margin-bottom: 16px;
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
  font-size: 28px;
  font-weight: 750;
  letter-spacing: -0.02em;
}
.kpi-value.accent {
  color: var(--primary);
}
.kpi-hint {
  font-size: 11.5px;
  color: var(--faint);
}
.panel-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}
.sla-panel {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: var(--radius);
  padding: 14px 18px;
  margin-bottom: 14px;
}
.sla-list {
  display: flex;
  flex-direction: column;
}
.sla-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px dashed #fde68a;
  cursor: pointer;
  font-size: 12.5px;
}
.sla-item:first-child {
  border-top: none;
  padding-top: 0;
}
.sla-item:hover .sla-main strong {
  color: var(--primary);
}
.sla-main {
  flex: 1;
  min-width: 0;
  display: flex;
  gap: 8px;
  align-items: baseline;
}
.sla-main strong {
  font-size: 13px;
}
.sla-job {
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sla-time {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}
.sla-time em {
  color: #b45309;
  font-style: normal;
  font-weight: 650;
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
  gap: 10px;
  margin-bottom: 14px;
}
.panel-head h3 {
  margin: 0;
  font-size: 14.5px;
}
.panel-hint {
  font-size: 11.5px;
  color: var(--faint);
}
.funnel-head,
.funnel-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 44px 48px;
  align-items: center;
  gap: 10px;
}
.funnel-head {
  font-size: 11px;
  color: var(--faint);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}
.funnel-row {
  margin-bottom: 9px;
}
.funnel-label {
  font-size: 12.5px;
  color: var(--muted);
}
.funnel-track {
  height: 22px;
  background: #f4f5fa;
  border-radius: 6px;
  overflow: hidden;
}
.funnel-fill {
  height: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, #6366f1, #a78bfa);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 6px;
  transition: width 0.4s ease;
}
.funnel-share {
  font-size: 10.5px;
  color: #fff;
  font-weight: 650;
}
.num {
  text-align: right;
  font-size: 12.5px;
  color: var(--muted);
}
.num.strong {
  color: var(--text);
  font-weight: 700;
}
.rejected-row {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  font-size: 12.5px;
  color: var(--muted);
}
.rejected-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--danger);
  margin-right: 6px;
}
.cycle-row {
  margin-bottom: 12px;
}
.cycle-main {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.cycle-label {
  font-size: 12.5px;
  color: var(--muted);
}
.cycle-value {
  font-size: 13.5px;
  font-weight: 700;
}
.cycle-bar {
  height: 6px;
  background: #f4f5fa;
  border-radius: 4px;
  margin: 5px 0 3px;
  overflow: hidden;
}
.cycle-bar-fill {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, #0ea5e9, #38bdf8);
  transition: width 0.4s ease;
}
.cycle-samples {
  font-size: 11px;
  color: var(--faint);
}
.channel-list {
  display: flex;
  flex-direction: column;
  gap: 11px;
}
.channel-row {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) 240px 56px;
  align-items: center;
  gap: 12px;
}
.channel-name {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.channel-track {
  height: 20px;
  background: #f4f5fa;
  border-radius: 6px;
  overflow: hidden;
}
.channel-fill {
  height: 100%;
  background: linear-gradient(90deg, #c7d2fe, #a5b4fc);
  border-radius: 6px;
  display: flex;
  justify-content: flex-end;
  transition: width 0.4s ease;
}
.channel-hired {
  height: 100%;
  background: linear-gradient(90deg, #34d399, #10b981);
  border-radius: 0 6px 6px 0;
}
.channel-stat {
  font-size: 12px;
  color: var(--muted);
}
.channel-stat strong {
  color: var(--text);
  font-size: 13px;
}
.channel-stat .ok {
  color: var(--success);
}
.channel-stat .miss {
  color: var(--danger);
}
.channel-conv {
  text-align: right;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.legend {
  display: flex;
  gap: 18px;
  margin-top: 14px;
  font-size: 11.5px;
  color: var(--muted);
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 5px;
}
.dot.total {
  background: #a5b4fc;
}
.dot.hired {
  background: #10b981;
}
.muted {
  color: var(--muted);
  font-size: 12.5px;
}
@media (max-width: 960px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .panel-grid {
    grid-template-columns: 1fr;
  }
  .channel-row {
    grid-template-columns: 90px minmax(0, 1fr);
  }
  .channel-stat,
  .channel-conv {
    grid-column: 2;
  }
}
</style>
