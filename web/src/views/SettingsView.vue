<template>
  <main class="settings-page">
    <header class="settings-header">
      <h1>设置</h1>
    </header>

    <div class="settings-content">
      <section class="settings-group" aria-labelledby="account-settings-title">
        <h2 id="account-settings-title">账号</h2>
        <div class="settings-list">
          <div class="settings-row">
            <div class="settings-row__copy">
              <strong>用户名</strong>
              <span>当前登录账号</span>
            </div>
            <span class="settings-row__value">{{ accountName }}</span>
          </div>
        </div>
      </section>

      <section class="settings-group" aria-labelledby="security-settings-title">
        <h2 id="security-settings-title">安全</h2>
        <div class="settings-list">
          <div class="settings-row">
            <div class="settings-row__copy">
              <strong>登录密码</strong>
              <span>修改当前账号的登录密码</span>
            </div>
            <button type="button" class="settings-row__action" @click="openPasswordDialog">
              <span>更改</span>
              <el-icon aria-hidden="true"><ArrowRight /></el-icon>
            </button>
          </div>
        </div>
      </section>

      <section class="settings-group" aria-labelledby="appearance-settings-title">
        <h2 id="appearance-settings-title">外观</h2>
        <div class="settings-list">
          <div class="settings-row">
            <div class="settings-row__copy">
              <strong>{{ isDarkTheme ? '深色模式' : '浅色模式' }}</strong>
              <span>{{ isDarkTheme ? '界面使用深色背景' : '界面使用浅色背景' }}</span>
            </div>
            <el-switch
              :model-value="isDarkTheme"
              :aria-label="isDarkTheme ? '关闭深色模式' : '开启深色模式'"
              @change="toggleTheme"
            />
          </div>
        </div>
      </section>

      <section class="settings-group" aria-labelledby="session-settings-title">
        <h2 id="session-settings-title">当前会话</h2>
        <div class="settings-list">
          <div class="settings-row">
            <div class="settings-row__copy">
              <strong>退出登录</strong>
              <span>退出后需要重新输入用户名和密码</span>
            </div>
            <button type="button" class="settings-row__action settings-row__action--danger" @click="handleLogout">
              <span>退出</span>
              <el-icon aria-hidden="true"><ArrowRight /></el-icon>
            </button>
          </div>
        </div>
      </section>
    </div>

    <el-dialog
      v-model="passwordDialogVisible"
      class="password-dialog"
      title="修改登录密码"
      width="min(440px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      @closed="resetPasswordForm"
    >
      <p class="password-dialog__intro">请输入当前密码，再设置一个新的登录密码。</p>

      <el-form
        ref="formRef"
        class="settings-form"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleChangePassword"
      >
        <el-form-item label="当前密码" prop="currentPassword" for="settings-current-password" :show-message="false">
          <el-input
            id="settings-current-password"
            v-model="form.currentPassword"
            autocomplete="current-password"
            placeholder="请输入当前密码"
            show-password
            size="large"
            type="password"
          />
        </el-form-item>

        <el-form-item label="新密码" prop="newPassword" for="settings-new-password" :show-message="false">
          <el-input
            id="settings-new-password"
            v-model="form.newPassword"
            autocomplete="new-password"
            placeholder="至少 8 位字符"
            show-password
            size="large"
            type="password"
          />
        </el-form-item>

        <el-form-item label="确认新密码" prop="confirmPassword" for="settings-confirm-password" :show-message="false">
          <el-input
            id="settings-confirm-password"
            v-model="form.confirmPassword"
            autocomplete="new-password"
            placeholder="请再次输入新密码"
            show-password
            size="large"
            type="password"
            @keydown.enter.prevent="handleChangePassword"
          />
        </el-form-item>

        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          class="settings-alert"
          show-icon
          type="error"
          :closable="false"
        />
        <el-alert
          v-if="successMessage"
          :title="successMessage"
          class="settings-alert"
          show-icon
          type="success"
          :closable="false"
        />

        <div class="password-dialog__actions">
          <el-button class="settings-cancel" size="large" @click="passwordDialogVisible = false">
            取消
          </el-button>
          <el-button
            class="settings-submit"
            native-type="submit"
            type="primary"
            size="large"
            :disabled="authStore.loading"
            :loading="authStore.loading"
          >
            更新密码
          </el-button>
        </div>
      </el-form>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, inject, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'

import { useAuthStore } from '../stores/auth'

const APP_SHELL_CONTEXT_KEY = 'ds-course-agent.app-shell'
const appShell = inject(APP_SHELL_CONTEXT_KEY, null)
const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
const passwordDialogVisible = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const form = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const accountName = computed(() => authStore.user?.student_id || authStore.user?.display_name || '未设置')
const isDarkTheme = computed(() => Boolean(appShell?.isDarkTheme?.value))

const validateConfirmPassword = (_rule, value, callback) => {
  if (!value) {
    callback(new Error('请再次输入新密码'))
  } else if (value !== form.newPassword) {
    callback(new Error('两次输入的新密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '新密码至少需要 8 位字符', trigger: 'blur' }
  ],
  confirmPassword: [{ validator: validateConfirmPassword, trigger: 'blur' }]
}

function openPasswordDialog() {
  errorMessage.value = ''
  successMessage.value = ''
  passwordDialogVisible.value = true
}

async function handleChangePassword() {
  if (authStore.loading) return
  errorMessage.value = ''
  successMessage.value = ''

  const validationMessage = getValidationMessage()
  if (validationMessage) {
    errorMessage.value = validationMessage
    return
  }

  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) {
    errorMessage.value = '请检查密码输入后再试。'
    return
  }

  try {
    await authStore.changePassword({
      current_password: form.currentPassword,
      new_password: form.newPassword
    })
    successMessage.value = '密码已修改成功。'
  } catch (error) {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    errorMessage.value = status === 401 || status === 403
      ? '当前密码不正确，请检查后重试。'
      : status === 422 && typeof detail === 'string'
        ? detail
        : '暂时无法修改密码，请稍后重试。'
  }
}

function getValidationMessage() {
  if (!form.currentPassword) return '请输入当前密码。'
  if (!form.newPassword) return '请输入新密码。'
  if (form.newPassword.length < 8) return '新密码至少需要 8 位字符。'
  if (!form.confirmPassword) return '请再次输入新密码。'
  if (form.newPassword !== form.confirmPassword) return '两次输入的新密码不一致，请重新确认。'
  if (form.currentPassword === form.newPassword) return '新密码不能与当前密码相同。'
  return ''
}

function resetPasswordForm() {
  form.currentPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''
  errorMessage.value = ''
  successMessage.value = ''
  formRef.value?.resetFields()
}

function toggleTheme() {
  appShell?.toggleTheme?.()
}

async function handleLogout() {
  try {
    await ElMessageBox.confirm('退出后需要重新登录，确定退出当前账号吗？', '退出登录', {
      confirmButtonText: '退出登录',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await authStore.logout()
    await router.replace('/login')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error('退出登录失败，请稍后重试。')
  }
}
</script>

<style scoped>
.settings-page {
  --settings-border: #e5e7eb;
  --settings-surface: #ffffff;
  --settings-text: #202124;
  --settings-muted: #8a8a8a;
  --settings-action: #4f5f96;
  width: 100%;
  min-height: 100%;
  overflow-y: auto;
  padding: 32px 24px 64px;
  color: var(--settings-text);
  background: #ffffff;
}

.settings-header {
  width: min(100%, 800px);
  margin-inline: auto;
}

.settings-header {
  margin-bottom: 0;
}

.settings-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  line-height: 1.25;
}

.settings-content {
  width: min(100%, 600px);
  margin: 32px auto 0;
  display: grid;
  gap: 42px;
}

.settings-group h2 {
  margin: 0 0 12px;
  color: var(--settings-text);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.settings-list {
  overflow: hidden;
  background: var(--settings-surface);
  border: 1px solid var(--settings-border);
  border-radius: 12px;
}

.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 56px;
  padding: 14px;
}

.settings-row__copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-row__copy strong {
  color: var(--settings-text);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
}

.settings-row__copy span {
  color: var(--settings-muted);
  font-size: 12px;
  line-height: 1.4;
}

.settings-row__value {
  max-width: 48%;
  overflow: hidden;
  color: var(--settings-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-row__action {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 3px;
  padding: 4px 0 4px 8px;
  color: var(--settings-action);
  background: transparent;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
}

.settings-row__action:hover,
.settings-row__action:focus-visible {
  color: #3f4e82;
}

.settings-row__action:focus-visible {
  outline: 2px solid rgba(79, 95, 150, 0.24);
  outline-offset: 3px;
  border-radius: 4px;
}

.settings-row__action--danger {
  color: #9b3d35;
}

.settings-row__action--danger:hover,
.settings-row__action--danger:focus-visible {
  color: #7f2d27;
}

.password-dialog__intro {
  margin: -4px 0 22px;
  color: var(--settings-muted);
  font-size: 13px;
  line-height: 1.5;
}

.settings-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.settings-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 8px;
  color: #4b4d52;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.settings-form :deep(.el-input__wrapper) {
  min-height: 42px;
  border-radius: 8px;
  background: var(--settings-surface);
  box-shadow: 0 0 0 1px #dfe2e8 inset;
  transition: box-shadow 0.2s ease;
}

.settings-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c9cdd8 inset;
}

.settings-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--settings-action) inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.settings-form :deep(.el-form-item.is-error .el-input__wrapper),
.settings-form :deep(.el-form-item.is-error .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #dfe2e8 inset;
}

.settings-form :deep(.el-form-item.is-error .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--settings-action) inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.settings-form :deep(.el-form-item__error) {
  display: none;
}

.settings-form :deep(.el-input__inner) {
  color: var(--settings-text);
  caret-color: var(--settings-action);
}

.settings-alert {
  margin: -2px 0 18px;
}

.password-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}

.settings-cancel,
.settings-submit {
  min-height: 38px;
  border-radius: 8px;
  font-weight: 600;
}

.settings-cancel {
  color: #45484f;
  background: #ffffff;
  border-color: #d9dce2;
}

.settings-cancel:hover,
.settings-cancel:focus {
  color: #202124;
  background: #f7f7f8;
  border-color: #c7cbd2;
}

.settings-submit {
  border: 0;
  background: var(--settings-action);
}

.settings-submit:hover,
.settings-submit:focus {
  background: #3f4e82;
}

:global(.password-dialog .el-dialog) {
  border-radius: 12px;
}

:global(.password-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 22px 24px 0;
}

:global(.password-dialog .el-dialog__title) {
  color: var(--settings-text);
  font-size: 17px;
  font-weight: 600;
}

:global(.password-dialog .el-dialog__body) {
  padding: 20px 24px 24px;
}

:global(html.theme-dark) .settings-page {
  --settings-border: var(--dark-border);
  --settings-surface: var(--dark-panel);
  --settings-text: var(--dark-text);
  --settings-muted: var(--dark-text-muted);
  background: var(--dark-bg);
}

:global(html.theme-dark) .settings-form :deep(.el-form-item__label) {
  color: var(--dark-text-muted);
}

:global(html.theme-dark) .settings-form :deep(.el-input__wrapper) {
  background: var(--dark-panel);
  box-shadow: 0 0 0 1px var(--dark-border) inset;
}

:global(html.theme-dark) .settings-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #666 inset;
}

:global(html.theme-dark) .settings-form :deep(.el-input__wrapper.is-focus),
:global(html.theme-dark) .settings-form :deep(.el-form-item.is-error .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #8e9bd0 inset, 0 0 0 3px rgba(142, 155, 208, 0.14);
}

:global(html.theme-dark) .settings-form :deep(.el-form-item.is-error .el-input__wrapper),
:global(html.theme-dark) .settings-form :deep(.el-form-item.is-error .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--dark-border) inset;
}

:global(html.theme-dark) .settings-cancel {
  color: var(--dark-text);
  background: var(--dark-panel);
  border-color: var(--dark-border);
}

:global(html.theme-dark) .settings-cancel:hover,
:global(html.theme-dark) .settings-cancel:focus {
  background: var(--dark-hover);
  border-color: #666;
}

@media (max-width: 560px) {
  .settings-page {
    padding: 24px 18px 48px;
  }

  .settings-header {
    margin-bottom: 32px;
  }

  .settings-content {
    gap: 34px;
  }

  .settings-row {
    gap: 12px;
  }

  .settings-row__value {
    max-width: 42%;
  }
}
</style>
