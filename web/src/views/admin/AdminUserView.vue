<template>
  <section class="admin-page">
    <router-link to="/admin/users" class="admin-detail-back">← 返回账号列表</router-link>
    <header class="admin-page__header">
      <div>
        <h1>{{ data?.user.display_name || '账号详情' }}</h1>
        <p class="admin-page__description">维护账号信息，查看该用户的课程使用情况。</p>
      </div>
      <span v-if="data" class="admin-pill" :class="`admin-pill--${data.user.status}`">
        {{ data.user.status === 'active' ? '正常' : '已停用' }}
      </span>
    </header>
    <p v-if="error || actionError" class="admin-error" role="alert">
      {{ error || actionError }}
      <button v-if="error" class="admin-link" type="button" @click="load">重试</button>
    </p>
    <div v-if="loading" class="admin-loading" role="status">正在加载账号详情…</div>
    <template v-else-if="data">
      <div class="admin-two-columns">
        <section class="admin-card">
          <div class="admin-card__header"><h2>基本信息</h2></div>
          <dl class="admin-definition-list">
            <div>
              <dt>用户名</dt>
              <dd>{{ data.user.username }}</dd>
            </div>
            <div>
              <dt>账号 ID</dt>
              <dd>{{ data.user.student_id }}</dd>
            </div>
            <div>
              <dt>注册时间</dt>
              <dd>{{ formatDate(data.user.created_at) }}</dd>
            </div>
            <div>
              <dt>最近登录</dt>
              <dd>{{ formatDate(data.user.last_login_at) }}</dd>
            </div>
            <div>
              <dt>注册来源</dt>
              <dd>{{ data.user.invite_name || registrationSourceLabels[data.user.registration_source] }}</dd>
            </div>
            <div>
              <dt>最近学习</dt>
              <dd>{{ formatDate(data.user.last_learning_at) }}</dd>
            </div>
          </dl>
        </section>
        <section class="admin-card">
          <div class="admin-card__header"><h2>信息与权限</h2></div>
          <form class="admin-form" @submit.prevent="saveUser">
            <label class="admin-field">
              显示名称
              <input v-model.trim="form.display_name" class="admin-input" required maxlength="128" />
            </label>
            <label class="admin-field">
              账号角色
              <select v-model="form.role" class="admin-select">
                <option v-for="(label, role) in roleLabels" :key="role" :value="role">{{ label }}</option>
              </select>
            </label>
            <p class="admin-note">{{ roleDescription[form.role] }}</p>
            <div class="admin-form-actions">
              <button type="submit" class="admin-button admin-button--primary" :disabled="saving || !changed">
                {{ saving ? '处理中…' : '保存修改' }}
              </button>
            </div>
          </form>
        </section>
      </div>
      <section class="admin-card">
        <div class="admin-card__header">
          <div>
            <h2>课程使用情况</h2>
            <p>
              提问 {{ formatNumber(data.user.questions) }} 次 · 提交练习 {{ formatNumber(data.user.submissions) }} 份
            </p>
          </div>
        </div>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>课程</th>
                <th class="admin-numeric">提问次数</th>
                <th class="admin-numeric">已提交练习</th>
                <th>最近学习</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="course in data.courses" :key="course.course_id">
                <td>{{ course.display_name }}</td>
                <td class="admin-numeric">{{ formatNumber(course.questions) }}</td>
                <td class="admin-numeric">{{ formatNumber(course.submissions) }}</td>
                <td>{{ formatDate(course.last_learning_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!data.courses.length" class="admin-empty">该账号尚无课程学习记录</p>
      </section>
      <section class="admin-card">
        <div class="admin-card__header">
          <div>
            <h2>账号安全</h2>
            <p>重置密码、撤销登录或停用账号后，已有登录会话将失效。</p>
          </div>
        </div>
        <div class="admin-actions">
          <button type="button" class="admin-button" :disabled="saving" @click="resetVisible = true">重置密码</button>
          <button type="button" class="admin-button" :disabled="saving" @click="revokeSessions">撤销所有登录</button>
          <button
            type="button"
            class="admin-button"
            :class="{ 'admin-button--danger': data.user.status === 'active' }"
            :disabled="saving"
            @click="toggleStatus"
          >
            {{ data.user.status === 'active' ? '停用账号' : '恢复账号' }}
          </button>
        </div>
      </section>
    </template>
    <el-dialog
      v-model="resetVisible"
      class="admin-dialog"
      title="重置登录密码"
      width="min(440px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      @closed="clearPassword"
    >
      <form class="admin-form" @submit.prevent="resetPassword">
        <p class="admin-note">为 {{ data?.user.username }} 设置新密码，并撤销该账号的已有登录。</p>
        <label class="admin-field">
          新密码
          <input
            v-model="password"
            class="admin-input"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
            maxlength="256"
          />
        </label>
        <label class="admin-field">
          确认新密码
          <input v-model="confirmPassword" class="admin-input" type="password" autocomplete="new-password" required />
        </label>
        <p v-if="passwordError" class="admin-error" role="alert">{{ passwordError }}</p>
        <div class="admin-form-actions">
          <button class="admin-button" type="button" :disabled="saving" @click="resetVisible = false">取消</button>
          <button class="admin-button admin-button--primary" type="submit" :disabled="saving">
            {{ saving ? '处理中…' : '确认重置' }}
          </button>
        </div>
      </form>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '../../api/admin'
import { useAuthStore } from '../../stores/auth'
import { useAdminResource } from '../../composables/useAdminResource'
import {
  errorMessage,
  formatDate,
  formatNumber,
  registrationSourceLabels,
  roleDescription,
  roleLabels
} from '../../utils/admin'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { data, loading, error, load } = useAdminResource(() => adminApi.user(route.params.userId))
const form = reactive({ display_name: '', role: 'student' })
const saving = ref(false)
const actionError = ref('')
const resetVisible = ref(false)
const password = ref('')
const confirmPassword = ref('')
const passwordError = ref('')
const changed = computed(
  () => data.value && (form.display_name !== data.value.user.display_name || form.role !== data.value.user.role)
)
watch(data, (value) => {
  if (value) Object.assign(form, { display_name: value.user.display_name, role: value.user.role })
})
watch(
  () => route.params.userId,
  () => {
    actionError.value = ''
    load()
  },
  { immediate: true }
)
function clearPassword() {
  password.value = ''
  confirmPassword.value = ''
  passwordError.value = ''
}
async function confirmAction(message, title) {
  try {
    await ElMessageBox.confirm(message, title, { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' })
    return true
  } catch {
    return false
  }
}
async function perform(operation, message) {
  if (saving.value) return
  saving.value = true
  actionError.value = ''
  try {
    await operation()
    ElMessage.success(message)
    if (data.value.user.student_id === authStore.user?.student_id) {
      try {
        await authStore.fetchMe()
      } catch (cause) {
        if (cause?.response?.status === 401) {
          await router.replace({ name: 'Login' })
          return
        }
        throw cause
      }
      if (!authStore.isAdmin) {
        await router.replace(authStore.canViewAdmin ? '/admin' : '/chat')
        return
      }
    }
    await load()
  } catch (cause) {
    actionError.value = errorMessage(cause)
  } finally {
    saving.value = false
  }
}
async function saveUser() {
  if (
    form.role !== data.value.user.role &&
    !(await confirmAction(
      `将 ${data.value.user.username} 的角色调整为「${roleLabels[form.role]}」？新权限会及时生效。`,
      '调整账号权限'
    ))
  )
    return
  await perform(
    () => adminApi.updateUser(route.params.userId, { display_name: form.display_name, role: form.role }),
    '账号信息已更新。'
  )
}
async function toggleStatus() {
  const disabled = data.value.user.status === 'active'
  if (
    !(await confirmAction(
      disabled ? '停用后，该账号将无法登录，已有登录会话也将失效。' : '恢复后，该账号可以重新登录。',
      disabled ? '停用账号' : '恢复账号'
    ))
  )
    return
  await perform(
    () => adminApi.updateUser(route.params.userId, { status: disabled ? 'disabled' : 'active' }),
    disabled ? '账号已停用。' : '账号已恢复。'
  )
}
async function revokeSessions() {
  if (!(await confirmAction('该账号在所有设备上都需要重新登录。', '撤销所有登录'))) return
  await perform(() => adminApi.revokeSessions(route.params.userId), '已有登录已撤销。')
}
async function resetPassword() {
  passwordError.value = ''
  if (password.value !== confirmPassword.value) {
    passwordError.value = '两次输入的密码不一致。'
    return
  }
  if (saving.value) return
  saving.value = true
  try {
    await adminApi.resetPassword(route.params.userId, password.value)
    resetVisible.value = false
    ElMessage.success('密码已重置，已有登录已撤销。')
    await load()
  } catch (cause) {
    passwordError.value = errorMessage(cause)
  } finally {
    saving.value = false
  }
}
</script>
