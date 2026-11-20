<script setup lang="ts">
import { reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import AuthShell from '@/components/AuthShell.vue'
import client from '@/api/client'

const formRef = ref<FormInstance>()
const loading = ref(false)
const sent = ref('')
const form = reactive({ email: '' })

const rules: FormRules = {
  email: [
    { required: true, message: '请输入注册邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
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
    const { data } = await client.post<{ message: string }>('/auth/forgot-password', {
      email: form.email.trim(),
    })
    sent.value = data.message
    ElMessage.success('请求已提交')
  } catch (e: any) {
    ElMessage.error(e?.message || '提交失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthShell title="忘记密码" subtitle="填写注册邮箱，我们会发送一封重置密码邮件">
    <el-alert
      v-if="sent"
      :title="sent"
      type="success"
      :closable="false"
      show-icon
      class="alert"
    />

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onSubmit">
      <el-form-item label="注册邮箱" prop="email">
        <el-input v-model="form.email" placeholder="请输入注册时使用的邮箱" autocomplete="email" />
      </el-form-item>
      <el-button type="primary" class="submit" :loading="loading" @click="onSubmit">
        发送重置邮件
      </el-button>
    </el-form>

    <p class="hint">
      未配置 SMTP 时（开发模式），重置链接会打印在后端日志中。
    </p>

    <div class="auth-footer">
      <RouterLink to="/login">返回登录</RouterLink>
      <RouterLink to="/register">去注册</RouterLink>
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
.hint {
  margin: 14px 0 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}
</style>
