<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import AuthShell from '@/components/AuthShell.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ name: '', email: '', password: '', confirm: '' })

const rules: FormRules = {
  name: [
    { required: true, message: '请输入登录名', trigger: 'blur' },
    { min: 2, max: 50, message: '长度需在 2~50 位之间', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 64, message: '密码长度需在 8~64 位之间', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (!value) return callback()
        if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
          return callback(new Error('密码需同时包含字母和数字'))
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
  confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
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
    const result = await auth.register({
      name: form.name.trim(),
      email: form.email.trim(),
      password: form.password,
    })
    ElMessage.success(result.message)
    // 新注册账号尚未登录，清掉可能的旧会话，保证能进入登录页
    await auth.logout()
    router.push('/login')
  } catch (e: any) {
    ElMessage.error(e?.message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthShell title="注册" subtitle="注册后默认角色为招聘专员（recruiter）">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onSubmit">
      <el-form-item label="登录名" prop="name">
        <el-input v-model="form.name" placeholder="用于登录，2~50 位，不含空格" />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="form.email" placeholder="用于验证与找回密码" autocomplete="email" />
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          show-password
          placeholder="8~64 位，需含字母和数字"
          autocomplete="new-password"
        />
      </el-form-item>
      <el-form-item label="确认密码" prop="confirm">
        <el-input
          v-model="form.confirm"
          type="password"
          show-password
          placeholder="再次输入密码"
          autocomplete="new-password"
          @keyup.enter="onSubmit"
        />
      </el-form-item>
      <el-button type="primary" class="submit" :loading="loading" @click="onSubmit">注册</el-button>
    </el-form>

    <div class="auth-footer">
      <span>已有账号？<RouterLink to="/login">去登录</RouterLink></span>
    </div>
  </AuthShell>
</template>

<style scoped>
.submit {
  width: 100%;
  height: 40px;
  margin-top: 4px;
}
</style>
