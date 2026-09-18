<template>
  <main class="settings-page">
    <header class="settings-header">
      <div>
        <span class="settings-kicker">账号与偏好</span>
        <h1>设置</h1>
        <p>管理账号安全和学习界面的显示方式。</p>
      </div>
    </header>

    <div class="settings-content">
      <section class="settings-section" aria-labelledby="account-settings-title">
        <div class="settings-section__heading">
          <div>
            <h2 id="account-settings-title">账号</h2>
            <p>当前登录账号信息。</p>
          </div>
        </div>

        <div class="account-summary">
          <span class="account-summary__icon" aria-hidden="true">
            <el-icon><User /></el-icon>
          </span>
          <div>
            <span class="account-summary__label">用户名</span>
            <strong>{{ accountName }}</strong>
          </div>
        </div>
      </section>

      <section class="settings-section" aria-labelledby="password-settings-title">
        <div class="settings-section__heading">
          <div>
            <h2 id="password-settings-title">修改密码</h2>
            <p>请输入当前密码，再设置一个新的登录密码。</p>
          </div>
        </div>

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

          <el-button
            class="settings-submit"
            native-type="submit"
            type="primary"
            size="large"
            :disabled="authStore.loading"
            :loading="authStore.loading"
          >
            保存新密码
          </el-button>
        </el-form>
      </section>

      <section class="settings-section" aria-labelledby="appearance-settings-title">
        <div class="settings-section__heading">
          <div>
            <h2 id="appearance-settings-title">外观</h2>
            <p>选择学习工作区的显示主题。</p>
          </div>
        </div>

        <div class="settings-option">
          <span class="settings-option__icon" aria-hidden="true">
            <el-icon><component :is="isDarkTheme ? Moon : Sunny" /></el-icon>
          </span>
          <div class="settings-option__copy">
            <strong>{{ isDarkTheme ? '深色模式' : '浅色模式' }}</strong>
            <span>{{ isDarkTheme ? '界面使用深色背景' : '界面使用浅色背景' }}</span>
          </div>
          <el-switch
            :model-value="isDarkTheme"
            :aria-label="isDarkTheme ? '关闭深色模式' : '开启深色模式'"
            @change="toggleTheme"
          />
        </div>
      </section>

      <section class="settings-section settings-section--danger" aria-labelledby="session-settings-title">
        <div class="settings-section__heading">
          <div>
            <h2 id="session-settings-title">当前会话</h2>
            <p>退出后需要重新输入用户名和密码。</p>
          </div>
        </div>
        <button type="button" class="settings-logout" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon>
          <span>退出登录</span>
        </button>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, inject, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Moon, Sunny, SwitchButton, User } from '@element-plus/icons-vue'

import { useAuthStore } from '../stores/auth'

const APP_SHELL_CONTEXT_KEY = 'ds-course-agent.app-shell'
const appShell = inject(APP_SHELL_CONTEXT_KEY, null)
const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
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
    form.currentPassword = ''
    form.newPassword = ''
    form.confirmPassword = ''
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
  --settings-border: #e6e8f1;
  --settings-surface: #ffffff;
  --settings-surface-soft: #f8f9fd;
  --settings-text: #171a2b;
  --settings-muted: #70758b;
  --settings-faint: #9ba1b4;
  width: 100%;
  min-height: 100%;
  overflow-y: auto;
  padding: 32px clamp(24px, 5vw, 72px) 64px;
  color: var(--settings-text);
  background: #ffffff;
}

.settings-header,
.settings-content {
  width: min(100%, 820px);
  margin-inline: auto;
}

.settings-header {
  margin-bottom: 26px;
}

.settings-kicker {
  display: block;
  margin-bottom: 7px;
  color: var(--settings-muted);
  font-size: 12px;
  font-weight: 700;
}

.settings-header h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 760;
  line-height: 1.2;
}

.settings-header p {
  margin: 9px 0 0;
  color: var(--settings-muted);
  font-size: 14px;
}

.settings-content {
  display: grid;
  gap: 16px;
}

.settings-section {
  padding: 24px 26px 26px;
  background: var(--settings-surface);
  border: 1px solid var(--settings-border);
  border-radius: 10px;
  box-shadow: 0 6px 18px rgba(60, 67, 110, 0.025);
}

.settings-section__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 20px;
}

.settings-section__heading h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 760;
}

.settings-section__heading p {
  margin: 6px 0 0;
  color: var(--settings-muted);
  font-size: 13px;
  line-height: 1.5;
}

.account-summary,
.settings-option {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 58px;
  padding: 12px 14px;
  background: var(--settings-surface-soft);
  border: 1px solid var(--settings-border);
  border-radius: 8px;
}

.account-summary__icon,
.settings-option__icon {
  display: grid;
  place-items: center;
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  color: #4f5f96;
  background: rgba(79, 95, 150, 0.1);
  border-radius: 8px;
}

.account-summary > div,
.settings-option__copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.account-summary__label {
  color: var(--settings-muted);
  font-size: 12px;
}

.account-summary strong {
  overflow: hidden;
  color: var(--settings-text);
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-form {
  max-width: 520px;
}

.settings-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.settings-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 9px;
  color: #464a57;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.settings-form :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: 7px;
  background: var(--settings-surface);
  box-shadow: 0 0 0 1px #dfe2e8 inset;
  transition: box-shadow 0.2s ease;
}

.settings-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c9cdd8 inset;
}

.settings-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #4f5f96 inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.settings-form :deep(.el-form-item.is-error .el-input__wrapper),
.settings-form :deep(.el-form-item.is-error .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #dfe2e8 inset;
}

.settings-form :deep(.el-form-item.is-error .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #4f5f96 inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.settings-form :deep(.el-form-item__error) {
  display: none;
}

.settings-form :deep(.el-input__inner) {
  color: var(--settings-text);
  caret-color: #4f5f96;
}

.settings-alert {
  margin: -2px 0 18px;
}

.settings-submit {
  min-width: 132px;
  min-height: 42px;
  border: 0;
  border-radius: 7px;
  background: #4f5f96;
  font-weight: 700;
}

.settings-submit:hover,
.settings-submit:focus {
  background: #3f4e82;
}

.settings-option__copy {
  flex: 1;
}

.settings-option__copy strong {
  color: var(--settings-text);
  font-size: 14px;
}

.settings-option__copy span {
  color: var(--settings-muted);
  font-size: 12px;
}

.settings-logout {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px;
  color: #b42318;
  background: transparent;
  border: 1px solid #f0c7c2;
  border-radius: 7px;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
}

.settings-logout:hover,
.settings-logout:focus-visible {
  color: #8f1d13;
  background: #fff5f3;
  border-color: #eaa9a1;
}

.settings-logout:focus-visible {
  outline: 2px solid rgba(180, 35, 24, 0.25);
  outline-offset: 3px;
}

:global(html.theme-dark) .settings-page {
  --settings-border: var(--dark-border);
  --settings-surface: var(--dark-panel);
  --settings-surface-soft: var(--dark-panel-soft);
  --settings-text: var(--dark-text);
  --settings-muted: var(--dark-text-muted);
  --settings-faint: var(--dark-text-faint);
  background: var(--dark-bg);
}

:global(html.theme-dark) .settings-section {
  box-shadow: none;
}

:global(html.theme-dark) .settings-form :deep(.el-form-item__label) {
  color: var(--dark-text-muted);
}

:global(html.theme-dark) .settings-form :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--dark-border) inset;
}

:global(html.theme-dark) .settings-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #5a5a5a inset;
}

:global(html.theme-dark) .settings-form :deep(.el-input__wrapper.is-focus),
:global(html.theme-dark) .settings-form :deep(.el-form-item.is-error .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #91a1e2 inset, 0 0 0 3px rgba(145, 161, 226, 0.16);
}

:global(html.theme-dark) .settings-form :deep(.el-form-item.is-error .el-input__wrapper),
:global(html.theme-dark) .settings-form :deep(.el-form-item.is-error .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--dark-border) inset;
}

:global(html.theme-dark) .settings-logout {
  color: #ffaba3;
  background: transparent;
  border-color: rgba(255, 171, 163, 0.35);
}

:global(html.theme-dark) .settings-logout:hover,
:global(html.theme-dark) .settings-logout:focus-visible {
  color: #ffd2cd;
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(255, 171, 163, 0.55);
}

@media (max-width: 640px) {
  .settings-page {
    padding: 22px 16px 36px;
  }

  .settings-header h1 {
    font-size: 26px;
  }

  .settings-section {
    padding: 20px 18px 22px;
  }
}
</style>
