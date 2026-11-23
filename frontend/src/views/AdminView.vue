<script setup lang="ts">
/**
 * 管理后台：用户 / 系统配置 / API Key / 审计日志
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import * as adminApi from '@/api/admin'
import type { AdminUser, ApiKey, AuditLog, SystemConfig } from '@/api/admin'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const TABS = ['users', 'config', 'keys', 'audit'] as const
const tab = ref<string>('users')

const roleLabels: Record<string, string> = {
  recruiter: '招聘专员',
  manager: '用人经理',
  admin: '管理员',
}
const userStatusLabels: Record<string, string> = {
  active: '启用',
  disabled: '禁用',
  deleted: '已删除',
}
const keyStatusLabels: Record<string, string> = {
  active: '有效',
  expired: '已过期',
  revoked: '已吊销',
}

function fmt(value: string | null | undefined): string {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

// ---------------------------------------------------------------- 用户
const users = ref<AdminUser[]>([])
const usersLoading = ref(false)
const userFilters = reactive({ q: '', role: '', status: '', include_deleted: false })

async function loadUsers() {
  usersLoading.value = true
  try {
    users.value = await adminApi.listUsers({
      q: userFilters.q || undefined,
      role: userFilters.role || undefined,
      status: userFilters.status || undefined,
      include_deleted: userFilters.include_deleted,
      limit: 200,
    })
  } catch (e: any) {
    ElMessage.error(e.message || '加载用户失败')
  } finally {
    usersLoading.value = false
  }
}

const editVisible = ref(false)
const editSaving = ref(false)
const editing = reactive({ id: 0, name: '', role: 'recruiter', department: '', status: 'active' })

function openEdit(user: AdminUser) {
  editing.id = user.id
  editing.name = user.name
  editing.role = user.role
  editing.department = user.department || ''
  editing.status = user.status === 'disabled' ? 'disabled' : 'active'
  editVisible.value = true
}

async function saveEdit() {
  if (!editing.id) return
  editSaving.value = true
  try {
    await adminApi.updateUser(editing.id, {
      role: editing.role,
      department: editing.department.trim() || null,
      status: editing.status,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    editSaving.value = false
  }
}

async function toggleUser(user: AdminUser) {
  const next = user.status === 'disabled' ? 'active' : 'disabled'
  try {
    await adminApi.updateUser(user.id, { status: next })
    ElMessage.success(next === 'active' ? '已启用' : '已禁用')
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
  }
}

async function removeUser(user: AdminUser) {
  try {
    await ElMessageBox.confirm(
      `删除后该账号立即失效，且列表默认不再显示「${user.name}」。确定删除？`,
      '删除用户',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await adminApi.deleteUser(user.id)
    ElMessage.success('已删除')
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

// ---------------------------------------------------------------- 系统配置
const configs = ref<SystemConfig[]>([])
const configsLoading = ref(false)
const savingKey = ref('')

async function loadConfigs() {
  configsLoading.value = true
  try {
    configs.value = await adminApi.listConfigs()
  } catch (e: any) {
    ElMessage.error(e.message || '加载配置失败')
  } finally {
    configsLoading.value = false
  }
}

async function saveConfig(row: SystemConfig) {
  savingKey.value = row.key
  try {
    await adminApi.updateConfig(row.key, row.value, row.description || undefined)
    ElMessage.success('配置已保存')
    await loadConfigs()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    savingKey.value = ''
  }
}

// ---------------------------------------------------------------- API Key
const myKeys = ref<ApiKey[]>([])
const allKeys = ref<ApiKey[]>([])
const keysLoading = ref(false)
const keyDialog = ref(false)
const keyForm = reactive({ name: '', expires_in_days: undefined as number | undefined })
const newKey = ref('')
const newKeyVisible = ref(false)

async function loadKeys() {
  keysLoading.value = true
  try {
    const [mine, all] = await Promise.all([adminApi.listMyApiKeys(), adminApi.listAllApiKeys()])
    myKeys.value = mine
    allKeys.value = all
  } catch (e: any) {
    ElMessage.error(e.message || '加载 API Key 失败')
  } finally {
    keysLoading.value = false
  }
}

async function createKey() {
  if (!keyForm.name.trim()) {
    ElMessage.warning('请填写用途名称')
    return
  }
  try {
    const created = await adminApi.createMyApiKey({
      name: keyForm.name.trim(),
      expires_in_days: keyForm.expires_in_days || null,
    })
    newKey.value = created.key
    newKeyVisible.value = true
    keyDialog.value = false
    keyForm.name = ''
    keyForm.expires_in_days = undefined
    await loadKeys()
  } catch (e: any) {
    ElMessage.error(e.message || '创建失败')
  }
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(newKey.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

async function revokeKey(key: ApiKey, admin = false) {
  try {
    await ElMessageBox.confirm(`吊销后使用该 Key 的调用会立即失败，确定吊销「${key.name}」？`, '吊销 API Key', {
      type: 'warning',
      confirmButtonText: '吊销',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    if (admin) await adminApi.revokeAdminApiKey(key.id)
    else await adminApi.revokeMyApiKey(key.id)
    ElMessage.success('已吊销')
    await loadKeys()
  } catch (e: any) {
    ElMessage.error(e.message || '吊销失败')
  }
}

// ---------------------------------------------------------------- 审计
const logs = ref<AuditLog[]>([])
const auditTotal = ref(0)
const auditPage = ref(1)
const auditLoading = ref(false)
const auditFilters = reactive({ action: '', target_type: '', user_id: '' })

async function loadAudit() {
  auditLoading.value = true
  try {
    const data = await adminApi.listAudit({
      action: auditFilters.action || undefined,
      target_type: auditFilters.target_type || undefined,
      user_id: auditFilters.user_id ? Number(auditFilters.user_id) : undefined,
      skip: (auditPage.value - 1) * 20,
      limit: 20,
    })
    logs.value = data.items
    auditTotal.value = data.total
  } catch (e: any) {
    ElMessage.error(e.message || '加载审计日志失败')
  } finally {
    auditLoading.value = false
  }
}

function searchAudit() {
  auditPage.value = 1
  void loadAudit()
}

function changeAuditPage(page: number) {
  auditPage.value = page
  void loadAudit()
}

// ---------------------------------------------------------------- 切换
async function loadTab(name: string) {
  if (name === 'users') await loadUsers()
  if (name === 'config') await loadConfigs()
  if (name === 'keys') await loadKeys()
  if (name === 'audit') await loadAudit()
}

watch(tab, (name) => {
  if (!auth.isAdmin) return
  router.replace({ query: { tab: name } })
  void loadTab(name)
})

const selfId = computed(() => auth.user?.id)

onMounted(async () => {
  if (!auth.user) await auth.fetchMe()
  if (!auth.isAdmin) return
  const requested = String(route.query.tab || 'users')
  tab.value = TABS.includes(requested as any) ? requested : 'users'
  await loadTab(tab.value)
})
</script>

<template>
  <div class="admin-page">
    <header class="page-head">
      <div>
        <h1>管理后台</h1>
        <p>用户、角色与数据范围、系统参数、API Key 和审计日志。</p>
      </div>
    </header>

    <div v-if="!auth.isAdmin" class="no-access">
      <el-result icon="warning" title="无权访问" sub-title="该页面仅管理员可见" />
    </div>

    <el-tabs v-else v-model="tab" class="admin-tabs">
      <!-- 用户 -->
      <el-tab-pane label="用户管理" name="users">
        <div class="toolbar">
          <el-input
            v-model="userFilters.q"
            placeholder="搜索姓名 / 邮箱"
            clearable
            style="width: 220px"
            @keyup.enter="loadUsers"
          />
          <el-select v-model="userFilters.role" placeholder="全部角色" clearable style="width: 130px">
            <el-option label="招聘专员" value="recruiter" />
            <el-option label="用人经理" value="manager" />
            <el-option label="管理员" value="admin" />
          </el-select>
          <el-select v-model="userFilters.status" placeholder="全部状态" clearable style="width: 130px">
            <el-option label="启用" value="active" />
            <el-option label="禁用" value="disabled" />
            <el-option label="已删除" value="deleted" />
          </el-select>
          <el-checkbox v-model="userFilters.include_deleted">包含已删除</el-checkbox>
          <el-button type="primary" @click="loadUsers">查询</el-button>
          <span class="spacer" />
          <span class="hint">manager 的数据范围：本部门 + 自己创建/审批的职位；未分配部门 = 全公司</span>
        </div>

        <el-table v-loading="usersLoading" :data="users" stripe>
          <el-table-column label="用户" min-width="190">
            <template #default="{ row }">
              <div class="user-cell">
                <strong>{{ row.name }}</strong>
                <span>{{ row.email }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="110">
            <template #default="{ row }">
              <el-tag effect="plain">{{ roleLabels[row.role] || row.role }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="部门" width="130">
            <template #default="{ row }">{{ row.department || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag
                :type="row.status === 'active' ? 'success' : row.status === 'deleted' ? 'info' : 'warning'"
                effect="light"
              >
                {{ userStatusLabels[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近登录" width="150">
            <template #default="{ row }">{{ fmt(row.last_login_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="row.id === selfId" @click="openEdit(row)">
                编辑
              </el-button>
              <el-button
                link
                :type="row.status === 'disabled' ? 'success' : 'warning'"
                :disabled="row.id === selfId || row.status === 'deleted'"
                @click="toggleUser(row)"
              >
                {{ row.status === 'disabled' ? '启用' : '禁用' }}
              </el-button>
              <el-button
                link
                type="danger"
                :disabled="row.id === selfId || row.status === 'deleted'"
                @click="removeUser(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 系统配置 -->
      <el-tab-pane label="系统配置" name="config">
        <el-table v-loading="configsLoading" :data="configs" stripe>
          <el-table-column label="配置项" min-width="240">
            <template #default="{ row }">
              <div class="user-cell">
                <strong>{{ row.key }}</strong>
                <span>{{ row.description || '—' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="值" min-width="220">
            <template #default="{ row }">
              <el-switch v-if="typeof row.value === 'boolean'" v-model="row.value" />
              <el-input-number
                v-else-if="typeof row.value === 'number'"
                v-model="row.value"
                :min="1"
                :max="1000"
                controls-position="right"
              />
              <el-input v-else v-model="row.value" />
            </template>
          </el-table-column>
          <el-table-column label="最近修改" width="160">
            <template #default="{ row }">{{ fmt(row.update_time) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :loading="savingKey === row.key" @click="saveConfig(row)">
                保存
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- API Key -->
      <el-tab-pane label="API Key" name="keys">
        <div class="section-head">
          <div>
            <h3>我的 API Key</h3>
            <p>用于脚本或外部系统调用，请求头传 <code>X-API-Key: tm_xxx</code>。</p>
          </div>
          <el-button type="primary" @click="keyDialog = true">新建 Key</el-button>
        </div>

        <el-table v-loading="keysLoading" :data="myKeys" stripe>
          <el-table-column prop="name" label="用途" min-width="160" />
          <el-table-column label="前缀" width="150">
            <template #default="{ row }"><code>{{ row.prefix }}…</code></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="light">
                {{ keyStatusLabels[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近使用" width="150">
            <template #default="{ row }">{{ fmt(row.last_used_at) }}</template>
          </el-table-column>
          <el-table-column label="过期时间" width="150">
            <template #default="{ row }">{{ fmt(row.expires_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="danger"
                :disabled="row.status !== 'active'"
                @click="revokeKey(row)"
              >
                吊销
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="section-head all-keys">
          <div>
            <h3>全部 API Key</h3>
            <p>管理员可查看并吊销所有用户的 Key。</p>
          </div>
        </div>
        <el-table v-loading="keysLoading" :data="allKeys" stripe>
          <el-table-column label="用户" width="140">
            <template #default="{ row }">{{ row.user_name || `#${row.user_id}` }}</template>
          </el-table-column>
          <el-table-column prop="name" label="用途" min-width="150" />
          <el-table-column label="前缀" width="150">
            <template #default="{ row }"><code>{{ row.prefix }}…</code></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="light">
                {{ keyStatusLabels[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近使用" width="150">
            <template #default="{ row }">{{ fmt(row.last_used_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="danger"
                :disabled="row.status !== 'active'"
                @click="revokeKey(row, true)"
              >
                吊销
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 审计 -->
      <el-tab-pane label="审计日志" name="audit">
        <div class="toolbar">
          <el-input
            v-model="auditFilters.action"
            placeholder="动作，如 admin.user.update"
            clearable
            style="width: 240px"
            @keyup.enter="searchAudit"
          />
          <el-input
            v-model="auditFilters.target_type"
            placeholder="对象类型，如 user"
            clearable
            style="width: 180px"
            @keyup.enter="searchAudit"
          />
          <el-input
            v-model="auditFilters.user_id"
            placeholder="操作人 ID"
            clearable
            style="width: 130px"
            @keyup.enter="searchAudit"
          />
          <el-button type="primary" @click="searchAudit">查询</el-button>
          <span class="spacer" />
          <span class="hint">共 {{ auditTotal }} 条</span>
        </div>

        <el-table v-loading="auditLoading" :data="logs" stripe>
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmt(row.create_time) }}</template>
          </el-table-column>
          <el-table-column label="操作人" width="130">
            <template #default="{ row }">{{ row.user_name || (row.user_id ? `#${row.user_id}` : '系统') }}</template>
          </el-table-column>
          <el-table-column prop="action" label="动作" width="190" />
          <el-table-column label="对象" width="160">
            <template #default="{ row }">{{ row.target_type }} #{{ row.target_id ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="明细" min-width="280">
            <template #default="{ row }">
              <span class="detail-json" :title="JSON.stringify(row.detail)">
                {{ JSON.stringify(row.detail) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          class="pager"
          layout="prev, pager, next"
          :total="auditTotal"
          :page-size="20"
          :current-page="auditPage"
          @current-change="changeAuditPage"
        />
      </el-tab-pane>
    </el-tabs>

    <!-- 编辑用户 -->
    <el-dialog v-model="editVisible" title="编辑用户" width="420px">
      <el-form label-width="80px">
        <el-form-item label="用户">
          <span>{{ editing.name }}</span>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editing.role" :disabled="editing.id === selfId" style="width: 100%">
            <el-option label="招聘专员" value="recruiter" />
            <el-option label="用人经理" value="manager" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-input v-model="editing.department" placeholder="如 技术部；留空表示未分配" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editing.status" :disabled="editing.id === selfId" style="width: 100%">
            <el-option label="启用" value="active" />
            <el-option label="禁用" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建 Key -->
    <el-dialog v-model="keyDialog" title="新建 API Key" width="420px">
      <el-form label-width="90px">
        <el-form-item label="用途名称">
          <el-input v-model="keyForm.name" placeholder="如 数据同步脚本" maxlength="100" />
        </el-form-item>
        <el-form-item label="有效期">
          <el-input-number
            v-model="keyForm.expires_in_days"
            :min="1"
            :max="3650"
            placeholder="留空表示不过期"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="keyDialog = false">取消</el-button>
        <el-button type="primary" @click="createKey">创建</el-button>
      </template>
    </el-dialog>

    <!-- 仅显示一次 -->
    <el-dialog v-model="newKeyVisible" title="API Key 已创建" width="560px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        :closable="false"
        title="请立即复制保存，关闭后无法再次查看完整 Key"
        show-icon
      />
      <div class="raw-key">{{ newKey }}</div>
      <template #footer>
        <el-button @click="copyKey">复制</el-button>
        <el-button type="primary" @click="newKeyVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-page {
  max-width: 1280px;
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
.admin-tabs {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 6px 20px 20px;
  box-shadow: var(--shadow-sm);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 6px 0 16px;
}
.spacer {
  flex: 1;
}
.hint {
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
.section-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin: 6px 0 14px;
}
.section-head h3 {
  margin: 0;
  font-size: 15px;
}
.section-head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12.5px;
}
.all-keys {
  margin-top: 28px;
}
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.detail-json {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
.raw-key {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--primary-soft);
  color: var(--primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  word-break: break-all;
}
.no-access {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 40px;
}
</style>
