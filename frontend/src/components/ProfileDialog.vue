<script setup lang="ts">
/**
 * 个人资料编辑：昵称 / 手机号 / 头像 / 简介
 * 登录名与邮箱只读，避免影响登录与邮箱验证。
 * 头像以文件形式上传，后端校验格式与大小、统一裁成 256×256 后存入 MinIO。
 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const MAX_AVATAR_BYTES = 2 * 1024 * 1024
const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp']

const auth = useAuthStore()
const router = useRouter()
const saving = ref(false)
const cancelling = ref(false)
const avatarError = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const previewUrl = ref('')
const selectedFile = ref<File | null>(null)
const removingAvatar = ref(false)
let objectUrl = ''

const form = reactive({
  nickname: '',
  phone: '',
  bio: '',
})

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const initial = computed(() => (auth.displayName || '?').trim().slice(0, 1).toUpperCase())

// 仅招聘专员 / 用人经理可自助注销；管理员与超管需联系平台
const canCancel = computed(() => auth.isRecruiter || auth.isManager)

async function cancelAccount() {
  if (cancelling.value) return
  let password = ''
  try {
    const result = await ElMessageBox.prompt(
      '注销后将删除你创建的职位、候选人及相关投递/面试数据，且无法恢复。请输入登录密码确认：',
      '注销账号',
      {
        inputType: 'password',
        inputPlaceholder: '登录密码',
        confirmButtonText: '确认注销',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
    password = result.value || ''
  } catch {
    return
  }
  if (!password) {
    ElMessage.warning('请输入登录密码')
    return
  }

  cancelling.value = true
  try {
    const result = await auth.cancelAccount(password)
    ElMessage.success(
      `账号已注销：清理职位 ${result.deleted_jobs} 个、候选人 ${result.deleted_candidates} 位、投递 ${result.deleted_applications} 条`,
    )
    visible.value = false
    await auth.logout()
    router.push('/login')
  } catch (e: any) {
    ElMessage.error(e.message || '注销失败')
  } finally {
    cancelling.value = false
  }
}

function releaseObjectUrl() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = ''
  }
}

function reset() {
  const user = auth.user
  form.nickname = user?.nickname || ''
  form.phone = user?.phone || ''
  form.bio = user?.bio || ''
  releaseObjectUrl()
  selectedFile.value = null
  removingAvatar.value = false
  avatarError.value = false
  previewUrl.value = user?.avatar_url || ''
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) reset()
    else releaseObjectUrl()
  },
)

onBeforeUnmount(releaseObjectUrl)

function pickFile() {
  fileInput.value?.click()
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // 清空 value，允许再次选择同一张图片
  input.value = ''
  if (!file) return

  if (!ALLOWED_TYPES.includes(file.type)) {
    ElMessage.warning('仅支持 PNG / JPEG / WebP 图片')
    return
  }
  if (file.size > MAX_AVATAR_BYTES) {
    ElMessage.warning('头像不能超过 2MB')
    return
  }

  releaseObjectUrl()
  objectUrl = URL.createObjectURL(file)
  previewUrl.value = objectUrl
  selectedFile.value = file
  removingAvatar.value = false
  avatarError.value = false
}

function clearAvatar() {
  releaseObjectUrl()
  selectedFile.value = null
  previewUrl.value = ''
  // 已有头像才需要调删除接口
  removingAvatar.value = Boolean(auth.user?.avatar_url)
  avatarError.value = false
}

async function save() {
  saving.value = true
  try {
    if (selectedFile.value) {
      await auth.uploadAvatar(selectedFile.value)
    } else if (removingAvatar.value) {
      await auth.removeAvatar()
    }
    await auth.updateProfile({
      nickname: form.nickname.trim() || null,
      phone: form.phone.trim() || null,
      bio: form.bio.trim() || null,
    })
    ElMessage.success('个人资料已更新')
    visible.value = false
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="个人资料" width="540px" append-to-body>
    <div class="profile-top">
      <img
        v-if="previewUrl && !avatarError"
        :src="previewUrl"
        class="avatar-img"
        alt="头像"
        @error="avatarError = true"
      />
      <div v-else class="avatar-fallback">{{ initial }}</div>
      <div class="profile-id">
        <strong>{{ auth.user?.name }}</strong>
        <span>{{ auth.roleLabel }}<template v-if="auth.user?.department"> · {{ auth.user.department }}</template></span>
      </div>
    </div>

    <el-form label-width="86px" class="profile-form">
      <el-form-item label="登录名">
        <el-input :model-value="auth.user?.name" disabled />
      </el-form-item>
      <el-form-item label="邮箱">
        <el-input :model-value="auth.user?.email" disabled />
      </el-form-item>
      <el-form-item label="昵称">
        <el-input v-model="form.nickname" maxlength="50" placeholder="展示在顶栏，留空则显示登录名" />
      </el-form-item>
      <el-form-item label="手机号">
        <el-input v-model="form.phone" maxlength="30" placeholder="选填" />
      </el-form-item>
      <el-form-item label="头像">
        <div class="avatar-row">
          <el-button @click="pickFile">选择图片</el-button>
          <el-button v-if="previewUrl" link @click="clearAvatar">移除</el-button>
          <span class="avatar-hint">PNG / JPEG / WebP，不超过 2MB</span>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          @change="onFileChange"
        />
      </el-form-item>
      <el-form-item label="个人简介">
        <el-input
          v-model="form.bio"
          type="textarea"
          :rows="3"
          maxlength="255"
          show-word-limit
          placeholder="一句话介绍自己，选填"
        />
      </el-form-item>
    </el-form>

    <div v-if="canCancel" class="danger-zone">
      <div class="danger-text">
        <strong>注销账号</strong>
        <p>注销后将删除你创建的职位、候选人及相关投递数据，且无法恢复。</p>
      </div>
      <el-button type="danger" plain :loading="cancelling" @click="cancelAccount">
        注销账号
      </el-button>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.profile-top {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 2px 0 18px;
}
.avatar-img,
.avatar-fallback {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.avatar-img {
  object-fit: cover;
  box-shadow: 0 0 0 2px #fff, 0 0 0 3.5px #e4e7f6;
}
.avatar-fallback {
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  box-shadow: 0 0 0 2px #fff, 0 0 0 3.5px #e4e7f6;
}
.profile-id {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.profile-id strong {
  font-size: 15px;
}
.profile-id span {
  color: var(--muted);
  font-size: 12.5px;
}
.profile-form {
  padding-top: 4px;
}
.avatar-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.avatar-hint {
  color: var(--muted);
  font-size: 12.5px;
}
.danger-zone {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 6px;
  padding: 12px 14px;
  border: 1px solid #fbcaca;
  background: #fff7f7;
  border-radius: 10px;
}
.danger-text strong {
  font-size: 13.5px;
  color: #b42318;
}
.danger-text p {
  margin: 3px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #9a5c5c;
}
</style>
