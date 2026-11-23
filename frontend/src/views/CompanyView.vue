<script setup lang="ts">
/**
 * 公司设置：公司信息、招聘官网链接、邀请码与成员管理（仅公司管理员）
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import * as companyApi from '@/api/company'
import type { CompanyCurrent, CompanyMember } from '@/api/company'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const company = ref<CompanyCurrent | null>(null)
const members = ref<CompanyMember[]>([])
const loading = ref(false)
const resetting = ref(false)

const ROLE_LABELS: Record<string, string> = {
  recruiter: '招聘专员',
  manager: '用人经理',
  admin: '公司管理员',
}

const publicLink = computed(() =>
  company.value ? `${window.location.origin}/careers/${company.value.slug}` : '',
)

function fmt(value: string | null | undefined): string {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

async function loadAll() {
  loading.value = true
  try {
    const [info, list] = await Promise.all([companyApi.currentCompany(), companyApi.listMembers()])
    company.value = info
    members.value = list
  } catch (e: any) {
    ElMessage.error(e.message || '加载公司信息失败')
  } finally {
    loading.value = false
  }
}

async function copy(text: string, label: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

async function resetInvite() {
  try {
    await ElMessageBox.confirm(
      '重置后旧邀请码立即失效，已加入的成员不受影响。确定重置？',
      '重置邀请码',
      { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  resetting.value = true
  try {
    company.value = await companyApi.resetInviteCode()
    ElMessage.success('邀请码已重置')
  } catch (e: any) {
    ElMessage.error(e.message || '重置失败')
  } finally {
    resetting.value = false
  }
}

async function changeRole(member: CompanyMember, role: string) {
  try {
    const updated = await companyApi.updateMember(member.id, { role })
    Object.assign(member, updated)
    ElMessage.success('角色已更新')
  } catch (e: any) {
    ElMessage.error(e.message || '更新失败')
    await loadAll()
  }
}

async function toggleStatus(member: CompanyMember) {
  const next = member.status === 'disabled' ? 'active' : 'disabled'
  try {
    const updated = await companyApi.updateMember(member.id, { status: next })
    Object.assign(member, updated)
    ElMessage.success(next === 'active' ? '已启用' : '已停用')
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
    await loadAll()
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="company-page">
    <header class="page-head">
      <div>
        <h1>公司设置</h1>
        <p>公司内成员、邀请码与公开招聘链接。数据仅在本公司内可见。</p>
      </div>
    </header>

    <div v-if="!auth.isAdmin" class="no-access">
      <el-result icon="warning" title="无权访问" sub-title="该页面仅公司管理员可见" />
    </div>

    <div v-else v-loading="loading" class="content">
      <section v-if="company" class="card">
        <div class="card-head">
          <h3>{{ company.name }}</h3>
          <el-tag :type="company.status === 'active' ? 'success' : 'danger'" effect="plain">
            {{ company.status === 'active' ? '启用中' : '已停用' }}
          </el-tag>
        </div>
        <div class="info-row">
          <span class="label">公司标识</span>
          <code>{{ company.slug }}</code>
        </div>
        <div class="info-row">
          <span class="label">公开招聘页</span>
          <a :href="publicLink" target="_blank" rel="noopener">{{ publicLink }}</a>
          <el-button size="small" @click="copy(publicLink, '招聘链接')">复制</el-button>
        </div>
        <div class="info-row">
          <span class="label">成员数量</span>
          <span>{{ company.member_count }} 人</span>
        </div>
        <div class="info-row">
          <span class="label">公司邀请码</span>
          <code class="invite">{{ company.invite_code || '—' }}</code>
          <el-button size="small" @click="copy(company.invite_code || '', '邀请码')">复制</el-button>
          <el-button size="small" type="warning" plain :loading="resetting" @click="resetInvite">
            重置邀请码
          </el-button>
        </div>
        <p class="tip">同事注册时选择「用邀请码加入」，输入该邀请码即可加入本公司。</p>
      </section>

      <section class="card">
        <div class="card-head">
          <h3>成员管理</h3>
          <span class="tip">角色调整后立即生效；停用后该成员无法登录。</span>
        </div>
        <el-table :data="members" stripe>
          <el-table-column label="成员" min-width="200">
            <template #default="{ row }">
              <div class="user-cell">
                <strong>{{ row.name }}</strong>
                <span>{{ row.email }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="160">
            <template #default="{ row }">
              <el-select
                :model-value="row.role"
                size="small"
                :disabled="row.id === auth.user?.id"
                @change="(value: string) => changeRole(row, value)"
              >
                <el-option
                  v-for="(label, value) in ROLE_LABELS"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-switch
                :model-value="row.status === 'active'"
                :disabled="row.id === auth.user?.id"
                @change="toggleStatus(row)"
              />
            </template>
          </el-table-column>
          <el-table-column label="加入时间" width="170">
            <template #default="{ row }">{{ fmt(row.create_time) }}</template>
          </el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.company-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 4px 4px 40px;
}
.page-head h1 {
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.02em;
}
.page-head p {
  margin: 6px 0 18px;
  color: var(--muted);
  font-size: 13.5px;
}
.content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 18px 22px;
  box-shadow: var(--shadow-sm);
}
.card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.card-head h3 {
  margin: 0;
  font-size: 15.5px;
}
.info-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  font-size: 13.5px;
  flex-wrap: wrap;
}
.info-row .label {
  width: 92px;
  flex: 0 0 auto;
  color: var(--muted);
}
.info-row code {
  background: #f4f5ff;
  border-radius: 6px;
  padding: 2px 8px;
  color: #4338ca;
}
.info-row code.invite {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.info-row a {
  color: var(--primary);
  text-decoration: none;
  word-break: break-all;
}
.info-row a:hover {
  text-decoration: underline;
}
.tip {
  margin: 6px 0 0;
  color: var(--faint);
  font-size: 12.5px;
}
.user-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.user-cell span {
  color: var(--faint);
  font-size: 12.5px;
}
</style>
