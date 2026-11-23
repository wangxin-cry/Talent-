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
      // 流程看板：按状态分列、拖拽流转、时间线
      component: () => import('@/views/BoardView.vue'),
    },
    {
      path: '/applications/:id/prep',
      name: 'interview-prep',
      component: () => import('@/views/InterviewPrepView.vue'),
    },
    {
      path: '/analytics',
      name: 'analytics',
      // 数据看板：指标卡 + 漏斗 + 渠道 + 周期
      component: () => import('@/views/DashboardView.vue'),
    },
    {
      path: '/costs',
      name: 'costs',
      // AI 成本监控：汇总、预算告警、调用明细分页
      component: () => import('@/views/CostView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      // 管理后台：用户 / 系统配置 / API Key / 审计
      component: () => import('@/views/AdminView.vue'),
    },
    {
      path: '/company',
      name: 'company',
      // 公司设置：邀请码与成员管理（公司管理员）
      component: () => import('@/views/CompanyView.vue'),
    },
    {
      path: '/platform',
      name: 'platform',
      // 平台超管：公司（租户）管理
      component: () => import('@/views/PlatformView.vue'),
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
      path: '/candidates/:id',
      name: 'candidate-detail',
      // 候选人 360°：档案 / 应聘记录 / 匹配 / 时间线
      component: () => import('@/views/CandidateDetailView.vue'),
    },
    {
      path: '/talent',
      name: 'talent',
      // 人才库：语义搜索相似简历
      component: () => import('@/views/TalentView.vue'),
    },
    {
      path: '/matching',
      name: 'matching',
      component: () => import('@/views/MatchingView.vue'),
    },
    {
      path: '/orchestration',
      name: 'orchestration',
      // 多 Agent 编排：一键评估 + 轨迹面板
      component: () => import('@/views/OrchestrationView.vue'),
    },
    {
      path: '/careers',
      name: 'careers',
      // 公开招聘官网入口：需带公司标识，见 /careers/:slug
      component: () => import('@/views/CareersView.vue'),
      meta: { public: true },
    },
    {
      path: '/careers/status',
      name: 'careers-status',
      // 投递进度查询（CE-02）
      component: () => import('@/views/CareerStatusView.vue'),
      meta: { public: true },
    },
    {
      path: '/careers/:slug',
      name: 'career-list',
      // 某家公司的公开招聘页
      component: () => import('@/views/CareersView.vue'),
      meta: { public: true },
    },
    {
      path: '/careers/:slug/:id',
      name: 'career-detail',
      component: () => import('@/views/CareersView.vue'),
      meta: { public: true },
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
