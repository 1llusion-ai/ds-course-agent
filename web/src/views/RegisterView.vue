<template>
  <main class="register-page">
    <section class="register-panel" aria-labelledby="register-title">
      <div class="register-copy">
        <div class="register-brand">
          <img src="/icon/thought_mark.png" alt="" />
          <strong>数据科学导论</strong>
        </div>
        <h1>
          <span>从一个账号开始，</span>
          <span>建立你的学习轨迹。</span>
        </h1>
      </div>

      <el-card class="register-card" shadow="never">
        <div class="register-card__header">
          <h2 id="register-title">创建账号</h2>
          <p>注册后即可开始课程学习</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="handleRegister"
        >
          <el-form-item label="用户名" prop="username" for="register-username" :show-message="false">
            <el-input
              id="register-username"
              ref="usernameInputRef"
              v-model.trim="form.username"
              autocomplete="username"
              placeholder="请输入用户名"
              size="large"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password" for="register-password" :show-message="false">
            <el-input
              id="register-password"
              v-model="form.password"
              autocomplete="new-password"
              placeholder="至少 8 位字符"
              show-password
              size="large"
              type="password"
              @keydown.enter.prevent="focusConfirmPassword"
            />
          </el-form-item>

          <el-form-item label="确认密码" prop="confirmPassword" for="register-confirm-password" :show-message="false">
            <el-input
              id="register-confirm-password"
              ref="confirmPasswordInputRef"
              v-model="form.confirmPassword"
              autocomplete="new-password"
              placeholder="请再次输入密码"
              show-password
              size="large"
              type="password"
              @keydown.enter.prevent="handleRegister"
            />
          </el-form-item>

          <el-form-item label="班级邀请码" prop="inviteCode" for="register-invite-code" :show-message="false">
            <el-input
              id="register-invite-code"
              v-model.trim="form.inviteCode"
              autocomplete="off"
              placeholder="如需邀请码，请输入老师提供的代码"
              size="large"
            />
          </el-form-item>

          <el-alert
            v-if="errorMessage"
            :title="errorMessage"
            class="register-error"
            show-icon
            type="error"
            :closable="false"
          />

          <el-button
            class="register-submit"
            native-type="submit"
            type="primary"
            size="large"
            :disabled="authStore.loading"
            :loading="authStore.loading"
          >
            注册
          </el-button>
        </el-form>

        <button type="button" class="register-login" @click="goToLogin">
          <span>已有账号？</span>
          <strong>返回登录</strong>
        </button>
      </el-card>
    </section>
  </main>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
const usernameInputRef = ref(null)
const confirmPasswordInputRef = ref(null)
const errorMessage = ref('')

const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  inviteCode: ''
})

const validateConfirmPassword = (_rule, value, callback) => {
  if (!value) {
    callback(new Error('请再次输入密码'))
  } else if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码至少需要 8 位字符', trigger: 'blur' }
  ],
  confirmPassword: [{ validator: validateConfirmPassword, trigger: 'blur' }]
}

async function handleRegister() {
  if (authStore.loading) return
  errorMessage.value = ''

  const validationMessage = getValidationMessage()
  if (validationMessage) {
    errorMessage.value = validationMessage
    return
  }

  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) {
    errorMessage.value = '请检查输入内容后再试。'
    return
  }

  try {
    await authStore.register({
      username: form.username,
      password: form.password,
      invite_code: form.inviteCode.trim()
    })
    await router.replace(getRegisterRedirect(route.query.redirect))
  } catch (error) {
    const status = error?.response?.status
    const detail = String(error?.response?.data?.detail || '')
    errorMessage.value = status === 409
      ? detail.includes('注册人数')
        ? '本班级注册人数已达到上限，请联系管理员。'
        : '该用户名已被使用，请换一个试试。'
      : status === 403
        ? '请输入有效的班级邀请码，请向老师获取。'
        : status === 503
          ? '当前暂未开放注册，请联系管理员。'
          : status === 422
            ? '请检查用户名和密码后再试。'
            : '暂时无法注册，请检查网络或稍后重试。'
  }
}

function getValidationMessage() {
  if (!form.username.trim()) return '请输入用户名。'
  if (!form.password) return '请输入密码。'
  if (form.password.length < 8) return '密码至少需要 8 位字符。'
  if (!form.confirmPassword) return '请再次输入密码。'
  if (form.password !== form.confirmPassword) return '两次输入的密码不一致，请重新确认。'
  return ''
}

function focusConfirmPassword() {
  nextTick(() => confirmPasswordInputRef.value?.focus())
}

function goToLogin() {
  const query = typeof route.query.redirect === 'string' ? { redirect: route.query.redirect } : undefined
  router.push({ name: 'Login', query })
}

function getRegisterRedirect(value) {
  if (typeof value !== 'string') return '/chat'
  const isInternalRoute = /^\/(chat|profile|knowledge-map|assessments)(?:[/?#]|$)/.test(value)
  return isInternalRoute ? value : '/chat'
}

onMounted(() => {
  nextTick(() => usernameInputRef.value?.focus())
})
</script>

<style scoped>
.register-page {
  --register-accent: #4f5f96;
  --register-accent-hover: #3f4e82;
  --register-border: #e3e5eb;
  --register-muted: #737784;
  --register-text: #242631;
  min-height: 100%;
  overflow-y: auto;
  display: grid;
  place-items: center;
  padding: 40px clamp(24px, 6vw, 88px);
  background: #f7f7f8;
  color: var(--register-text);
}

.register-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 34px;
}

.register-brand img {
  width: 40px;
  height: 40px;
  object-fit: contain;
}

.register-brand strong {
  display: block;
  color: #2d303a;
  font-size: 17px;
  font-weight: 700;
}

.register-panel {
  width: min(1080px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  gap: clamp(56px, 7vw, 96px);
  align-items: center;
}

.register-copy {
  position: relative;
  color: var(--register-text);
}

.register-copy h1 {
  margin: 0 0 18px;
  font-family: 'Noto Serif SC', 'Songti SC', serif;
  color: #293764;
  font-size: 46px;
  font-weight: 500;
  line-height: 1.42;
}

.register-copy h1 span {
  display: block;
}

.register-card {
  border: 1px solid var(--register-border);
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 14px 30px -5px rgba(32, 36, 54, 0.11), 0 4px 10px rgba(32, 36, 54, 0.04);
}

.register-card :deep(.el-card__body) {
  padding: 28px;
}

.register-card__header {
  margin-bottom: 28px;
}

.register-card__header h2 {
  margin: 0;
  color: var(--register-text);
  font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.35;
}

.register-card__header p {
  margin: 8px 0 0;
  color: var(--register-muted);
  font-size: 13px;
  line-height: 1.5;
}

.register-card :deep(.el-form-item) {
  margin-bottom: 20px;
}

.register-card :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 9px;
  color: #464a57;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.register-card :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: 7px;
  background: #ffffff;
  box-shadow: 0 0 0 1px #dfe2e8 inset;
  transition: box-shadow 0.2s ease;
}

.register-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c9cdd8 inset;
}

.register-card :deep(.el-input__wrapper.is-focus) {
  background: #ffffff;
  box-shadow: 0 0 0 1px var(--register-accent) inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.register-card :deep(.el-form-item.is-error .el-input__wrapper) {
  box-shadow: 0 0 0 1px #dfe2e8 inset;
}

.register-card :deep(.el-form-item.is-error .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c9cdd8 inset;
}

.register-card :deep(.el-form-item.is-error .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--register-accent) inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.register-card :deep(.el-form-item__error) {
  display: none;
}

.register-card :deep(.el-input__inner) {
  color: var(--register-text);
  background: transparent;
  caret-color: var(--register-accent);
}

.register-card :deep(.el-input__inner:-webkit-autofill),
.register-card :deep(.el-input__inner:-webkit-autofill:hover),
.register-card :deep(.el-input__inner:-webkit-autofill:focus) {
  -webkit-text-fill-color: var(--register-text);
  -webkit-box-shadow: 0 0 0 1000px #ffffff inset;
  caret-color: var(--register-text);
  transition: background-color 9999s ease-out 0s;
}

.register-card :deep(.el-input__password) {
  color: #858b9a;
}

.register-card :deep(.el-input__password:hover),
.register-card :deep(.el-input__password:focus-visible) {
  color: var(--register-accent);
}

.register-error {
  margin: -2px 0 18px;
}

.register-submit {
  width: 100%;
  min-height: 44px;
  margin-top: 2px;
  border: 0;
  border-radius: 7px;
  background: var(--register-accent);
  font-weight: 700;
  box-shadow: 0 5px 12px rgba(79, 95, 150, 0.18);
  transition: background-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.register-submit:hover,
.register-submit:focus {
  background: var(--register-accent-hover);
  box-shadow: 0 7px 16px rgba(63, 78, 130, 0.22);
}

.register-submit:active {
  transform: translateY(1px);
}

.register-login {
  display: block;
  width: 100%;
  margin-top: 20px;
  padding: 0;
  color: #666b78;
  text-align: center;
  background: transparent;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
}

.register-login strong {
  margin-left: 4px;
  color: var(--register-accent);
  font-weight: 700;
}

.register-login:hover,
.register-login:focus-visible {
  color: var(--register-accent);
}

.register-login:hover strong,
.register-login:focus-visible strong {
  color: var(--register-accent-hover);
}

.register-login:focus-visible {
  outline: 2px solid rgba(79, 95, 150, 0.35);
  outline-offset: 4px;
}

@media (max-width: 820px) {
  .register-page {
    padding: 32px 20px;
  }

  .register-panel {
    grid-template-columns: 1fr;
    gap: 30px;
    max-width: 430px;
    padding: 48px 0 24px;
  }

  .register-copy h1 {
    font-size: 36px;
  }

  .register-card :deep(.el-card__body) {
    padding: 26px;
  }
}

@media (max-width: 480px) {
  .register-page {
    padding-inline: 16px;
  }

  .register-panel {
    width: 100%;
    padding-top: 40px;
  }

  .register-copy h1 {
    font-size: 32px;
  }

  .register-card :deep(.el-card__body) {
    padding: 24px 22px;
  }
}
</style>
