<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import * as appApi from '@/api/applications'
import type { NotificationItem } from '@/api/applications'
import { currentCompany } from '@/api/company'
import ProfileDialog from '@/components/ProfileDialog.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const AUTH_PAGES = ['login', 'register', 'forgot-password', 'reset-password', 'verify-email']
const isAuthPage = computed(() => AUTH_PAGES.includes(String(route.name)))
// 招聘官网等对外页面：不展示内部导航
const isPublicPage = computed(() => route.meta.public === true && !isAuthPage.value)
// 工作台是满屏三栏布局，需要去掉内容区 padding
const isFullBleed = computed(() => route.name === 'home' || isPublicPage.value)

const initial = computed(() =>
  (auth.displayName || '?').trim().slice(0, 1).toUpperCase(),
)

// 当前公司（超管不属于任何公司）
const companyName = ref('')

async function loadCompany() {
  if (!auth.isLoggedIn) {
    companyName.value = ''
    return
  }
  try {
    const company = await currentCompany()
    companyName.value = company.name
  } catch {
    companyName.value = ''
  }
}

// 对外招聘页带上公司标识
const publicCareersLink = computed(() =>
  route.params.slug
    ? { name: 'career-list', params: { slug: route.params.slug } }
    : { name: 'careers' },
)

// 头像图片加载失败时回退到首字母
const avatarError = ref(false)
watch(
  () => auth.user?.avatar_url,
  () => {
    avatarError.value = false
  },
)

// ---------------- 个人资料 ----------------
const profileOpen = ref(false)

function onUserCommand(command: string) {
  if (command === 'profile') profileOpen.value = true
  if (command === 'logout') void onLogout()
}

// ---------------- 站内通知 ----------------
const notifications = ref<NotificationItem[]>([])
const unread = ref(0)
const notifLoading = ref(false)

async function loadUnread() {
  if (!auth.isLoggedIn) return
  try {
    unread.value = await appApi.unreadCount()
  } catch {
    // 通知失败不打断主流程
  }
}

async function loadNotifications() {
  if (!auth.isLoggedIn) return
  notifLoading.value = true
  try {
    const data = await appApi.listNotifications({ limit: 20 })
    notifications.value = data.items
    unread.value = data.unread
  } catch (e: any) {
    ElMessage.error(e.message || '加载通知失败')
  } finally {
    notifLoading.value = false
  }
}

async function readNotification(item: NotificationItem) {
  if (item.status === 'read') return
  try {
    const updated = await appApi.markRead(item.id)
    item.status = updated.status
    unread.value = Math.max(0, unread.value - 1)
  } catch {
    // 忽略已读失败
  }
}

function openNotification(item: NotificationItem) {
  void readNotification(item)
  if (item.application_id) router.push(`/applications/${item.application_id}/prep`)
}

function formatTime(value: string): string {
  return value.replace('T', ' ').slice(5, 16)
}

watch(
  [() => auth.isSuperAdmin, () => route.path],
  ([isSuper]) => {
    // 超管只进入平台管理，避免落到无公司上下文的业务页
    if (isSuper && route.path !== '/platform' && route.meta.public !== true) {
      void router.replace('/platform')
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (auth.accessToken) {
    void auth.fetchMe()
    void loadUnread()
    void loadCompany()
  }
})

watch(
  () => auth.isLoggedIn,
  (logged) => {
    if (logged) {
      void loadUnread()
      void loadCompany()
    } else {
      companyName.value = ''
    }
  },
)

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <header v-if="isPublicPage" class="topbar public-topbar">
      <RouterLink class="brand" :to="publicCareersLink">
        <span class="logo-mark">T</span>
        <span class="brand-name">TalentMatch</span>
      </RouterLink>
      <nav class="nav">
        <RouterLink :to="publicCareersLink" active-class="active">在招职位</RouterLink>
        <RouterLink :to="{ name: 'careers-status' }" active-class="active">投递进度</RouterLink>
      </nav>
      <div class="right">
        <RouterLink v-if="auth.isLoggedIn" class="login-link" to="/">返回工作台</RouterLink>
        <RouterLink v-else class="login-link" to="/login">招聘者登录</RouterLink>
      </div>
    </header>

    <header v-else-if="!isAuthPage" class="topbar">
      <RouterLink class="brand" to="/">
        <span class="logo-mark">T</span>
        <span class="brand-name">TalentMatch</span>
        <span v-if="companyName" class="company-chip">{{ companyName }}</span>
      </RouterLink>

      <nav class="nav">
        <RouterLink to="/" exact-active-class="active">工作台</RouterLink>
        <RouterLink to="/jobs" active-class="active">职位</RouterLink>
        <RouterLink to="/candidates" active-class="active">候选人</RouterLink>
        <RouterLink to="/talent" active-class="active">人才库</RouterLink>
        <RouterLink to="/matching" active-class="active">智能匹配</RouterLink>
        <RouterLink to="/orchestration" active-class="active">Agent 编排</RouterLink>
        <RouterLink to="/board" active-class="active">流程看板</RouterLink>
        <RouterLink to="/analytics" active-class="active">数据看板</RouterLink>
        <RouterLink to="/costs" active-class="active">成本</RouterLink>
        <template v-if="auth.isAdmin">
          <RouterLink to="/company" active-class="active">公司设置</RouterLink>
          <RouterLink to="/admin" active-class="active">管理后台</RouterLink>
        </template>
        <template v-if="auth.isSuperAdmin">
          <RouterLink to="/platform" active-class="active">平台管理</RouterLink>
        </template>
      </nav>

      <div class="right">
        <template v-if="auth.isLoggedIn">
          <el-popover placement="bottom-end" :width="360" trigger="click" @show="loadNotifications">
            <template #reference>
              <button class="notif-btn" title="站内通知">
                通知
                <span v-if="unread" class="notif-badge">{{ unread > 99 ? '99+' : unread }}</span>
              </button>
            </template>
            <div v-loading="notifLoading" class="notif-panel">
              <div class="notif-head">
                <span>站内通知</span>
                <span v-if="unread" class="notif-unread">{{ unread }} 条未读</span>
              </div>
              <div v-if="notifications.length" class="notif-list">
                <button
                  v-for="item in notifications"
                  :key="item.id"
                  class="notif-item"
                  :class="{ unread: item.status !== 'read' }"
                  @click="openNotification(item)"
                >
                  <div class="notif-item-top">
                    <span class="notif-subject">{{ item.subject || item.template }}</span>
                    <span class="notif-time">{{ formatTime(item.create_time) }}</span>
                  </div>
                  <div class="notif-body">{{ item.body }}</div>
                </button>
              </div>
              <div v-else class="notif-empty">暂无通知</div>
            </div>
          </el-popover>

          <el-dropdown trigger="click" placement="bottom-end" @command="onUserCommand">
            <button class="user-chip" type="button">
              <img
                v-if="auth.user?.avatar_url && !avatarError"
                class="avatar-img"
                :src="auth.user.avatar_url"
                alt="头像"
                @error="avatarError = true"
              />
              <span v-else class="avatar">{{ initial }}</span>
              <span class="user-meta">
                <span class="user-name">{{ auth.displayName }}</span>
                <span class="user-role">{{ auth.roleLabel }}</span>
              </span>
              <span class="caret">▾</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人资料</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <RouterLink v-else class="login-link" to="/login">登录</RouterLink>
      </div>
    </header>

    <main
      class="content"
      :class="{ 'is-auth': isAuthPage, 'is-full': isFullBleed, 'is-public': isPublicPage }"
    >
      <RouterView />
    </main>

    <ProfileDialog v-model="profileOpen" />
  </div>
</template>

<style>
.app-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* ---------------- 顶栏 ---------------- */
.topbar {
  height: 56px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 26px;
  padding: 0 22px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 20;
}

.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  text-decoration: none;
  color: var(--text);
  font-weight: 700;
  font-size: 15.5px;
  letter-spacing: -0.01em;
}
.logo-mark {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
}
.company-chip {
  margin-left: 4px;
  padding: 2px 8px;
  border-radius: 7px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 600;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav {
  display: flex;
  align-items: center;
  gap: 4px;
}
.nav a,
.nav .disabled {
  padding: 7px 14px;
  border-radius: 9px;
  font-size: 13.5px;
  color: var(--muted);
  text-decoration: none;
  transition: background 0.16s, color 0.16s, box-shadow 0.16s;
}
.nav a:hover {
  background: rgba(242, 243, 248, 0.9);
  color: var(--text);
}
.nav a.active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.nav .disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.notif-btn {
  position: relative;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--muted);
  border-radius: 9px;
  padding: 5px 12px;
  font-size: 12.5px;
  cursor: pointer;
  transition: 0.16s;
}
.notif-btn:hover {
  border-color: #c9cffa;
  color: var(--primary);
  box-shadow: var(--shadow-sm);
}
.notif-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 17px;
  height: 17px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--danger);
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  line-height: 17px;
  text-align: center;
}
.notif-panel {
  min-height: 60px;
}
.notif-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 650;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.notif-unread {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--primary);
}
.notif-list {
  display: flex;
  flex-direction: column;
  max-height: 340px;
  overflow: auto;
}
.notif-item {
  text-align: left;
  border: none;
  background: transparent;
  border-bottom: 1px solid var(--line);
  padding: 10px 4px;
  cursor: pointer;
  font: inherit;
}
.notif-item:hover {
  background: #fafbff;
}
.notif-item.unread .notif-subject::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  margin-right: 6px;
  vertical-align: middle;
}
.notif-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.notif-subject {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.notif-time {
  font-size: 11px;
  color: var(--faint);
  flex: 0 0 auto;
}
.notif-body {
  margin-top: 3px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}
.notif-empty {
  padding: 26px 0;
  text-align: center;
  color: var(--faint);
  font-size: 12.5px;
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 12px;
  padding: 3px 7px 3px 3px;
  cursor: pointer;
  transition: 0.16s;
}
.user-chip:hover {
  background: #fff;
  border-color: var(--line);
  box-shadow: var(--shadow-sm);
}
.user-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  max-width: 120px;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-role {
  font-size: 11px;
  color: var(--faint);
  line-height: 1.1;
}
.caret {
  color: var(--faint);
  font-size: 11px;
  margin-left: 1px;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  box-shadow: 0 0 0 2px #fff, 0 0 0 3.5px #e4e7f6;
  flex: 0 0 auto;
}
.avatar-img {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
  box-shadow: 0 0 0 2px #fff, 0 0 0 3.5px #e4e7f6;
  flex: 0 0 auto;
}
.login-link {
  font-size: 13px;
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}
.login-link:hover {
  text-decoration: underline;
}
.public-topbar .brand {
  margin-right: 8px;
}

/* ---------------- 内容区 ---------------- */
.content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 26px 28px 40px;
}
.content.is-auth {
  padding: 0;
  display: flex;
  overflow: auto;
}
.content.is-full {
  padding: 0;
  min-height: 0;
  overflow: hidden;
}
.content.is-public {
  padding: 0;
  overflow: auto;
}

@media (max-width: 900px) {
  .topbar {
    padding: 0 14px;
    gap: 14px;
  }
  .brand-name,
  .company-chip,
  .user-meta {
    display: none;
  }
  .nav a,
  .nav .disabled {
    padding: 6px 10px;
    font-size: 13px;
  }
  .content {
    padding: 18px 14px 32px;
  }
}
</style>
