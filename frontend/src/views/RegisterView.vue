<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import AuthShell from '@/components/AuthShell.vue'
import { lookupCompany } from '@/api/company'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({
  name: '',
  email: '',
  password: '',
  confirm: '',
  mode: 'create' as 'create' | 'join',
  companyName: '',
  inviteCode: '',
  role: 'recruiter' as 'recruiter' | 'manager',
})

const companyPreview = ref<{ name: string; slug: string } | null>(null)
const lookupLoading = ref(false)

async function lookupInvite() {
  companyPreview.value = null
  const code = form.inviteCode.trim()
  if (code.length < 4) return
  lookupLoading.value = true
  try {
    companyPreview.value = await lookupCompany(code)
  } catch {
    ElMessage.error('邀请码无效或公司已停用，请向公司管理员确认')
  } finally {
    lookupLoading.value = false
  }
}

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
  if (form.mode === 'create' && !form.companyName.trim()) {
    ElMessage.warning('请填写公司名称')
    return
  }
  if (form.mode === 'join' && !form.inviteCode.trim()) {
    ElMessage.warning('请填写公司邀请码')
    return
  }

  loading.value = true
  try {
    const result = await auth.register({
      name: form.name.trim(),
      email: form.email.trim(),
      password: form.password,
      mode: form.mode,
      company_name: form.mode === 'create' ? form.companyName.trim() : undefined,
      invite_code: form.mode === 'join' ? form.inviteCode.trim().toUpperCase() : undefined,
      role: form.mode === 'join' ? form.role : undefined,
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
  <AuthShell title="注册" subtitle="注册后需完成邮箱验证才能登录">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onSubmit">
      <el-form-item label="登录名" prop="name">
        <el-input v-model="form.name" placeholder="用于登录，2~50 位，不含空格" />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="form.email" placeholder="用于验证与找回密码" autocomplete="email" />
      </el-form-item>
      <el-form-item label="公司归属" prop="mode">
        <el-radio-group v-model="form.mode">
          <el-radio value="create">创建新公司</el-radio>
          <el-radio value="join">用邀请码加入</el-radio>
        </el-radio-group>
        <div class="role-hint">
          一家公司一套数据：职位、候选人、对话与成本仅在所属公司内可见
        </div>
      </el-form-item>
      <el-form-item v-if="form.mode === 'create'" label="公司名称" prop="companyName">
        <el-input v-model="form.companyName" maxlength="100" placeholder="如：某某科技有限公司" />
        <div class="role-hint">创建者将自动成为该公司管理员，可生成邀请码邀请同事加入</div>
      </el-form-item>
      <template v-else>
        <el-form-item label="公司邀请码" prop="inviteCode">
          <el-input
            v-model="form.inviteCode"
            maxlength="16"
            placeholder="向公司管理员获取邀请码"
            @blur="lookupInvite"
          />
          <div v-if="lookupLoading" class="role-hint">正在查询公司…</div>
          <div v-else-if="companyPreview" class="company-preview">
            加入公司：<strong>{{ companyPreview.name }}</strong>
          </div>
          <div v-else class="role-hint">输入后会自动校验邀请码对应的公司</div>
        </el-form-item>
        <el-form-item label="注册身份" prop="role">
          <el-radio-group v-model="form.role">
            <el-radio value="recruiter">招聘专员</el-radio>
            <el-radio value="manager">用人经理</el-radio>
          </el-radio-group>
          <div class="role-hint">
            招聘专员管理自己的职位与候选人；用人经理还可审批职位、查看全量数据
          </div>
        </el-form-item>
      </template>
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

.role-hint {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.company-preview {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--el-color-primary);
}
</style>
