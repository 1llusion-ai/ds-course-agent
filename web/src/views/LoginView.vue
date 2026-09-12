<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-copy">
        <p class="login-kicker">数据科学导论</p>
        <h1>欢迎回来</h1>
        <p>登录后继续课程对话、会话历史和学习画像。</p>
      </div>

      <el-card class="login-card" shadow="never">
        <template #header>
          <div class="login-card__header">
            <span>账号登录</span>
            <small>课程工作区</small>
          </div>
        </template>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
          <el-form-item label="用户名 / 学号" prop="username">
            <el-input
              v-model.trim="form.username"
              autocomplete="username"
              placeholder="请输入用户名或学号"
              size="large"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              autocomplete="current-password"
              placeholder="请输入密码"
              show-password
              size="large"
              type="password"
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-alert
            v-if="errorMessage"
            :title="errorMessage"
            class="login-error"
            show-icon
            type="error"
            :closable="false"
          />

          <el-button class="login-submit" type="primary" size="large" :loading="authStore.loading" @click="handleLogin">
            登录
          </el-button>
        </el-form>
      </el-card>
    </section>
  </main>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
const errorMessage = ref('')

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名或学号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function handleLogin() {
  errorMessage.value = ''
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  try {
    await authStore.login({ ...form })
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
    await router.replace(redirect)
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.response?.data?.message || '登录失败，请检查账号和密码。'
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100%;
  display: grid;
  place-items: center;
  padding: 32px;
  background: var(--app-bg);
}

.login-panel {
  width: min(100%, 980px);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: 32px;
  align-items: center;
}

.login-copy {
  color: #1c1917;
}

.login-kicker {
  margin: 0 0 16px;
  color: #78716c;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: 0.16em;
}

.login-copy h1 {
  margin: 0 0 16px;
  font-size: clamp(36px, 6vw, 64px);
  line-height: 1.05;
  letter-spacing: -0.05em;
}

.login-copy p:last-child {
  max-width: 560px;
  margin: 0;
  color: #57534e;
  font-size: 16px;
  line-height: 1.8;
}

.login-card {
  border: 1px solid rgba(120, 113, 108, 0.18);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-md);
}

.login-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: #1c1917;
  font-weight: 760;
}

.login-card__header small {
  color: #a8a29e;
  font-size: 12px;
  font-weight: 700;
}

.login-error {
  margin-bottom: 18px;
}

.login-submit {
  width: 100%;
  margin-top: 4px;
  border-radius: var(--radius-md);
  font-weight: 750;
}

:global(html.theme-dark) .login-page { background: var(--app-bg); }
:global(html.theme-dark) .login-copy,
:global(html.theme-dark) .login-card__header { color: var(--text); }
:global(html.theme-dark) .login-copy p:last-child,
:global(html.theme-dark) .login-card__header small { color: var(--text-muted); }

@media (max-width: 820px) {
  .login-panel {
    grid-template-columns: 1fr;
  }
}
</style>
