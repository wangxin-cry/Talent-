<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import AuthShell from '@/components/AuthShell.vue'
import client from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ password: '', confirm: '' })

const rules: FormRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 64, message: '密码长度需在 8~64 位之间', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (value && (!/[A-Za-z]/.test(value) || !/\d/.test(value))) {
          return callback(new Error('密码需同时包含字母和数字'))
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (value !== form.password) return callback(new Error('两次输入的密码不一致'))
        callback()
      },
      trigger: 'blur',
    },
  ],
}

async function onSubmit() {
  if (!formRef.value || loading.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  loading.value = true
  try {
    await client.post('/auth/reset-password', { token: token.value, new_password: form.password })
    ElMessage.success('密码已重置，请使用新密码登录')
    // 密码已变更，清掉旧会话，确保能停留在登录页重新登录
    await auth.logout()
    router.replace('/login')
  } catch (e: any) {
    ElMessage.error(e?.message || '重置失败，链接可能已过期')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthShell title="重置密码" subtitle="请设置新的登录密码，链接仅可使用一次">
    <el-alert
      v-if="!token"
      title="链接缺少 token，请重新发起找回密码"
      type="error"
      :closable="false"
      show-icon
      class="alert"
    />

    <el-form
      v-else
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      @submit.prevent="onSubmit"
    >
      <el-form-item label="新密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          show-password
          placeholder="8~64 位，需含字母和数字"
          autocomplete="new-password"
        />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirm">
        <el-input
          v-model="form.confirm"
          type="password"
          show-password
          placeholder="再次输入新密码"
          autocomplete="new-password"
          @keyup.enter="onSubmit"
        />
      </el-form-item>
      <el-button type="primary" class="submit" :loading="loading" @click="onSubmit">
        确认重置
      </el-button>
    </el-form>

    <div class="auth-footer">
      <RouterLink to="/forgot-password">重新获取链接</RouterLink>
      <RouterLink to="/login">返回登录</RouterLink>
    </div>
  </AuthShell>
</template>

<style scoped>
.alert {
  margin-bottom: 16px;
}
.submit {
  width: 100%;
  height: 40px;
  margin-top: 4px;
}
</style>
