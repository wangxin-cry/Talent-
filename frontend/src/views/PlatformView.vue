<script setup lang="ts">
/**
 * 平台超管后台：公司（租户）列表、新建与启停。
 * 只管理公司本身，不进入任何公司的业务数据。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import * as companyApi from '@/api/company'
import type { PlatformCompany } from '@/api/company'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const companies = ref<PlatformCompany[]>([])
const loading = ref(false)
const creating = ref(false)
const createVisible = ref(false)
const createForm = reactive({ name: '' })

function fmt(value: string | null | undefined): string {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

async function loadCompanies() {
  loading.value = true
  try {
    companies.value = await companyApi.listPlatformCompanies()
  } catch (e: any) {
    ElMessage.error(e.message || '加载公司列表失败')
  } finally {
    loading.value = false
  }
}

async function createCompany() {
  const name = createForm.name.trim()
  if (name.length < 2) {
    ElMessage.warning('公司名称至少 2 个字')
    return
  }
  creating.value = true
  try {
    const company = await companyApi.createPlatformCompany(name)
    ElMessage.success(`已创建「${company.name}」，邀请码 ${company.invite_code}`)
    createVisible.value = false
    createForm.name = ''
    await loadCompanies()
  } catch (e: any) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function toggleStatus(company: PlatformCompany) {
  const next = company.status === 'disabled' ? 'active' : 'disabled'
  if (next === 'disabled') {
    try {
      await ElMessageBox.confirm(
        `停用后「${company.name}」的所有成员将无法登录和访问数据。确定停用？`,
        '停用公司',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  try {
    const updated = await companyApi.updatePlatformCompany(company.id, next)
    Object.assign(company, updated)
    ElMessage.success(next === 'active' ? '已启用' : '已停用')
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
    await loadCompanies()
  }
}

onMounted(loadCompanies)
</script>

<template>
  <div class="platform-page">
    <header class="page-head">
      <div>
        <h1>平台管理</h1>
        <p>管理入驻公司（租户）。超管不参与任何公司的业务数据。</p>
      </div>
      <el-button v-if="auth.isSuperAdmin" type="primary" @click="createVisible = true">
        新建公司
      </el-button>
    </header>

    <div v-if="!auth.isSuperAdmin" class="no-access">
      <el-result icon="warning" title="无权访问" sub-title="该页面仅平台超级管理员可见" />
    </div>

    <div v-else v-loading="loading" class="card">
      <el-table :data="companies" stripe>
        <el-table-column label="公司" min-width="180">
          <template #default="{ row }">
            <div class="company-cell">
              <strong>{{ row.name }}</strong>
              <span>{{ row.slug }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="邀请码" width="140">
          <template #default="{ row }">
            <code>{{ row.invite_code }}</code>
          </template>
        </el-table-column>
        <el-table-column label="成员数" width="90" prop="member_count" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'danger'" effect="plain">
              {{ row.status === 'active' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ fmt(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              :type="row.status === 'active' ? 'danger' : 'success'"
              plain
              @click="toggleStatus(row)"
            >
              {{ row.status === 'active' ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createVisible" title="新建公司" width="420px">
      <el-form label-position="top" @submit.prevent="createCompany">
        <el-form-item label="公司名称">
          <el-input v-model="createForm.name" maxlength="100" placeholder="如：某某科技有限公司" />
        </el-form-item>
        <p class="tip">创建后会自动生成邀请码，可交给该公司管理员招募成员。</p>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createCompany">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.platform-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 4px 4px 40px;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
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
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 18px;
  box-shadow: var(--shadow-sm);
}
.company-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.company-cell span {
  color: var(--faint);
  font-size: 12.5px;
}
code {
  background: #f4f5ff;
  border-radius: 6px;
  padding: 2px 8px;
  color: #4338ca;
}
.tip {
  margin: 0;
  color: var(--faint);
  font-size: 12.5px;
  line-height: 1.6;
}
</style>
