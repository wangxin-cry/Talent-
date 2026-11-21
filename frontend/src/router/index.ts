import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      // 工作台 = 对话式三栏（对齐 docs/TalentMatch_界面原型.html）
      component: () => import('@/views/WorkbenchView.vue'),
    },
    {
      path: '/board',
      name: 'board',
      // 看板：当前为 KPI 概览占位，阶段七补齐漏斗/周期/渠道
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/jobs',
      name: 'jobs',
      component: () => import('@/views/JobsView.vue'),
    },
    {
      path: '/candidates',
      name: 'candidates',
      component: () => import('@/views/CandidatesView.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { public: true },
    },
    {
      path: '/forgot-password',
      name: 'forgot-password',
      component: () => import('@/views/ForgotPasswordView.vue'),
      meta: { public: true },
    },
    {
      path: '/reset-password',
      name: 'reset-password',
      component: () => import('@/views/ResetPasswordView.vue'),
      meta: { public: true },
    },
    {
      path: '/verify-email',
      name: 'verify-email',
      component: () => import('@/views/VerifyEmailView.vue'),
      meta: { public: true },
    },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  const isPublic = to.meta.public === true

  if (!isPublic && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (isPublic && token && (to.name === 'login' || to.name === 'register')) {
    return { name: 'home' }
  }
  return true
})

export default router
