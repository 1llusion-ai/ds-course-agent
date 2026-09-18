<template>
  <main class="login-page">
    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-copy">
        <div class="login-brand">
          <img src="/icon/thought_mark.png" alt="" />
          <strong>数据科学导论</strong>
        </div>
        <h1>
          <span>让每一次提问，</span>
          <span>都走向更好的理解。</span>
        </h1>
      </div>

      <el-card class="login-card" shadow="never">
        <div class="login-card__header">
          <h2 id="login-title">欢迎回来</h2>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
          <el-form-item label="用户名" prop="username" for="login-username" :show-message="false">
            <el-input
              id="login-username"
              ref="usernameInputRef"
              v-model.trim="form.username"
              autocomplete="username"
              placeholder="请输入用户名"
              size="large"
            />
          </el-form-item>

          <el-form-item prop="password" for="login-password" :show-message="false">
            <template #label>
              <span>密码</span>
              <button type="button" class="forgot-link" @click.stop="showPendingHelp('password')">
                忘记密码？
              </button>
            </template>
            <el-input
              id="login-password"
              v-model="form.password"
              autocomplete="current-password"
              placeholder="请输入密码"
              show-password
              size="large"
              type="password"
              @keydown.enter.prevent="handleLogin"
              @keydown="checkCapsLock"
              @keyup="checkCapsLock"
              @blur="capsLock = false"
            />
          </el-form-item>

          <p v-if="capsLock" class="login-hint" role="status">大写锁定已开启</p>

          <el-alert
            v-if="errorMessage"
            :title="errorMessage"
            class="login-error"
            show-icon
            type="error"
            :closable="false"
          />

          <el-button class="login-submit" native-type="submit" type="primary" size="large" :loading="authStore.loading">
            登录
          </el-button>
        </el-form>

        <button type="button" class="login-register" @click="goToRegister">
          <span>还没有账号？</span>
          <strong>立即注册</strong>
        </button>
      </el-card>
    </section>
  </main>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
const usernameInputRef = ref(null)
const errorMessage = ref('')
const capsLock = ref(false)

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [{ required: true, message: '用户名不能为空', trigger: 'blur' }],
  password: [{ required: true, message: '密码不能为空', trigger: 'blur' }]
}

async function handleLogin() {
  if (authStore.loading) return
  errorMessage.value = ''
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  try {
    await authStore.login({ ...form })
    await router.replace(getLoginRedirect(route.query.redirect))
  } catch (error) {
    const status = error?.response?.status
    errorMessage.value = status === 401 || status === 403
      ? '用户名或密码不正确，请检查后重试。'
      : status === 429
        ? '尝试次数较多，请稍后再试。'
        : '暂时无法登录，请检查网络或稍后重试。'
  }
}

function checkCapsLock(event) {
  capsLock.value = event.getModifierState?.('CapsLock') || false
}

function showPendingHelp() {
  ElMessage.info('请联系管理员重置密码。')
}

function goToRegister() {
  const query = typeof route.query.redirect === 'string' ? { redirect: route.query.redirect } : undefined
  router.push({ name: 'Register', query })
}

function getLoginRedirect(value) {
  if (typeof value !== 'string') return '/chat'
  const isInternalRoute = /^\/(chat|profile|knowledge-map|assessments)(?:[/?#]|$)/.test(value)
  return isInternalRoute ? value : '/chat'
}

onMounted(() => {
  nextTick(() => usernameInputRef.value?.focus())
})
</script>

<style scoped>
.login-page {
  --login-accent: #4f5f96;
  --login-accent-hover: #3f4e82;
  --login-border: #e3e5eb;
  --login-muted: #737784;
  --login-text: #242631;
  min-height: 100%;
  overflow-y: auto;
  display: grid;
  place-items: center;
  padding: 40px clamp(24px, 6vw, 88px);
  background: #f7f7f8;
  color: var(--login-text);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 34px;
}

.login-brand img {
  width: 40px;
  height: 40px;
  object-fit: contain;
}

.login-brand strong {
  display: block;
  color: #2d303a;
  font-size: 17px;
  font-weight: 700;
}

.login-panel {
  width: min(1080px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  gap: clamp(56px, 7vw, 96px);
  align-items: center;
}

.login-copy {
  position: relative;
  color: var(--login-text);
}
.login-copy h1 {
  margin: 0 0 18px;
  font-family: 'Noto Serif SC', 'Songti SC', serif;
  color: #293764;
  font-size: 46px;
  font-weight: 500;
  line-height: 1.42;
}

.login-copy h1 span {
  display: block;
}

.login-card {
  border: 1px solid var(--login-border);
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 14px 30px -5px rgba(32, 36, 54, 0.11), 0 4px 10px rgba(32, 36, 54, 0.04);
}

.login-card :deep(.el-card__body) {
  padding: 28px;
}

.login-card__header {
  margin-bottom: 28px;
}

.login-card__header h2 {
  margin: 0;
  color: var(--login-text);
  font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.35;
}

.login-card :deep(.el-form-item) {
  margin-bottom: 26px;
}

.login-card :deep(.el-form-item__label) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: auto;
  padding: 0 0 9px;
  color: #464a57;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.login-card :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: 7px;
  background: #ffffff;
  box-shadow: 0 0 0 1px #dfe2e8 inset;
  transition: box-shadow 0.2s ease;
}

.login-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c9cdd8 inset;
}

.login-card :deep(.el-input__wrapper.is-focus) {
  background: #ffffff;
  box-shadow: 0 0 0 1px var(--login-accent) inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.login-card :deep(.el-form-item.is-error .el-input__wrapper) {
  box-shadow: 0 0 0 1px #dfe2e8 inset;
}

.login-card :deep(.el-form-item.is-error .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c9cdd8 inset;
}

.login-card :deep(.el-form-item.is-error .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--login-accent) inset, 0 0 0 3px rgba(79, 95, 150, 0.1);
}

.login-card :deep(.el-form-item__error) {
  display: none;
  color: #c24141;
  font-size: 12px;
  line-height: 1.4;
}

.login-card :deep(.el-input__inner) {
  color: var(--login-text);
  background: transparent;
  caret-color: var(--login-accent);
}

.login-card :deep(.el-input__inner:-webkit-autofill),
.login-card :deep(.el-input__inner:-webkit-autofill:hover),
.login-card :deep(.el-input__inner:-webkit-autofill:focus) {
  -webkit-text-fill-color: var(--login-text);
  -webkit-box-shadow: 0 0 0 1000px #ffffff inset;
  caret-color: var(--login-text);
  transition: background-color 9999s ease-out 0s;
}

.login-card :deep(.el-input__password) {
  color: #858b9a;
}

.login-card :deep(.el-input__password:hover),
.login-card :deep(.el-input__password:focus-visible) {
  color: var(--login-accent);
}

.forgot-link {
  padding: 0;
  color: var(--login-accent);
  background: transparent;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
}

.forgot-link:hover,
.forgot-link:focus-visible {
  color: var(--login-accent-hover);
}

.forgot-link:focus-visible {
  outline: 2px solid rgba(79, 95, 150, 0.3);
  outline-offset: 3px;
}

.login-error {
  margin: -4px 0 18px;
}

.login-hint {
  margin: -14px 0 18px;
  color: #8a651d;
  font-size: 12px;
}

.login-submit {
  width: 100%;
  min-height: 44px;
  margin-top: 2px;
  border: 0;
  border-radius: 7px;
  background: var(--login-accent);
  font-weight: 700;
  box-shadow: 0 5px 12px rgba(79, 95, 150, 0.18);
  transition: background-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.login-submit:hover,
.login-submit:focus {
  background: var(--login-accent-hover);
  box-shadow: 0 7px 16px rgba(63, 78, 130, 0.22);
}

.login-submit:active {
  transform: translateY(1px);
}

.login-register {
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

.login-register strong {
  margin-left: 4px;
  color: var(--login-accent);
  font-weight: 700;
}

.login-register:hover,
.login-register:focus-visible {
  color: var(--login-accent);
}

.login-register:hover strong,
.login-register:focus-visible strong {
  color: var(--login-accent-hover);
}

.login-register:focus-visible {
  outline: 2px solid rgba(79, 95, 150, 0.35);
  outline-offset: 4px;
}

@media (max-width: 820px) {
  .login-page {
    padding: 32px 20px;
  }

  .login-panel {
    grid-template-columns: 1fr;
    gap: 30px;
    max-width: 430px;
    padding: 48px 0 24px;
  }

  .login-copy h1 {
    font-size: 36px;
  }

  .login-card :deep(.el-card__body) {
    padding: 26px;
  }
}

@media (max-width: 480px) {
  .login-page {
    padding-inline: 16px;
  }

  .login-panel {
    width: 100%;
  }

  .login-panel {
    padding-top: 40px;
  }

  .login-copy h1 {
    font-size: 32px;
  }

  .login-card :deep(.el-card__body) {
    padding: 24px 22px;
  }
}
</style>
