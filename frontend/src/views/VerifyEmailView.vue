<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'

import AuthShell from '@/components/AuthShell.vue'
import client from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))

const state = ref<'loading' | 'success' | 'error'>('loading')
const message = ref('')

async function goLogin() {
  // 验证的是新账号，清掉浏览器里可能残留的旧会话，避免守卫把 /login 重定向到首页
  await auth.logout()
  router.push('/login')
}

onMounted(async () => {
  if (!token.value) {
    state.value = 'error'
    message.value = '链接缺少 token，请从邮件中重新打开'
    return
  }
  try {
    const { data } = await client.post<{ message: string }>('/auth/verify-email', {
      token: token.value,
    })
    state.value = 'success'
    message.value = data.message
  } catch (e: any) {
    state.value = 'error'
    message.value = e?.message || '验证失败，链接可能已过期'
  }
})
</script>

<template>
  <AuthShell title="邮箱验证" subtitle="正在确认你的邮箱归属">
    <el-skeleton v-if="state === 'loading'" :rows="2" animated />

    <el-result
      v-else-if="state === 'success'"
      icon="success"
      title="验证成功"
      :sub-title="message"
    />

    <el-result v-else icon="error" title="验证失败" :sub-title="message" />

    <div class="auth-footer">
      <a href="#" @click.prevent="goLogin">去登录</a>
      <RouterLink to="/forgot-password">找回密码</RouterLink>
    </div>
  </AuthShell>
</template>
