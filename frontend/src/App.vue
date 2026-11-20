<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const AUTH_PAGES = ['login', 'register', 'forgot-password', 'reset-password', 'verify-email']
const isAuthPage = computed(() => AUTH_PAGES.includes(String(route.name)))
// 工作台是满屏三栏布局，需要去掉内容区 padding
const isFullBleed = computed(() => route.name === 'home')

const initial = computed(() => (auth.user?.name || '?').trim().slice(0, 1).toUpperCase())

onMounted(() => {
  if (auth.accessToken) void auth.fetchMe()
})

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <header v-if="!isAuthPage" class="topbar">
      <RouterLink class="brand" to="/">
        <span class="logo-mark">T</span>
        <span class="brand-name">TalentMatch</span>
      </RouterLink>

      <nav class="nav">
        <RouterLink to="/" exact-active-class="active">工作台</RouterLink>
        <RouterLink to="/jobs" active-class="active">职位</RouterLink>
        <span class="disabled">候选人</span>
        <RouterLink to="/board" active-class="active">看板</RouterLink>
        <span class="disabled">成本</span>
        <template v-if="auth.isAdmin">
          <span class="disabled">用户管理</span>
          <span class="disabled">审计</span>
        </template>
      </nav>

      <div class="right">
        <template v-if="auth.isLoggedIn">
          <span class="role-badge">{{ auth.roleLabel }}</span>
          <span class="user-name">{{ auth.user?.name }}</span>
          <span class="avatar">{{ initial }}</span>
          <button class="logout" @click="onLogout">退出</button>
        </template>
        <RouterLink v-else class="login-link" to="/login">登录</RouterLink>
      </div>
    </header>

    <main class="content" :class="{ 'is-auth': isAuthPage, 'is-full': isFullBleed }">
      <RouterView />
    </main>
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
.role-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #fff;
  border: 1px solid #e4e7f6;
  color: var(--primary);
  padding: 4px 11px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 550;
}
.role-badge::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
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
}
.logout {
  border: 1px solid var(--line);
  background: #fff;
  color: var(--muted);
  border-radius: 9px;
  padding: 5px 12px;
  font-size: 12.5px;
  cursor: pointer;
  transition: 0.16s;
}
.logout:hover {
  border-color: #c9cffa;
  color: var(--primary);
  box-shadow: var(--shadow-sm);
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

/* ---------------- 内容区 ---------------- */
.content {
  flex: 1;
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
  overflow: hidden;
}

@media (max-width: 900px) {
  .topbar {
    padding: 0 14px;
    gap: 14px;
  }
  .brand-name,
  .role-badge,
  .user-name {
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
