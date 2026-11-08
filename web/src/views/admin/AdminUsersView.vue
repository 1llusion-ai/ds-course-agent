<template>
  <section class="admin-page">
    <header class="admin-page__header">
      <div>
        <h1>账号管理</h1>
        <p class="admin-page__description">查看账号信息、学习活动与访问权限。</p>
      </div>
      <button type="button" class="admin-button admin-button--primary" @click="openCreate">
        <el-icon aria-hidden="true"><Plus /></el-icon>
        创建账号
      </button>
    </header>
    <form class="admin-toolbar" @submit.prevent="search">
      <label class="admin-field admin-field--search">
        搜索账号
        <input v-model="filters.q" class="admin-input" type="search" placeholder="用户名、显示名称或账号 ID" />
      </label>
      <label class="admin-field">
        角色
        <select v-model="filters.role" class="admin-select">
          <option value="">全部角色</option>
          <option v-for="(label, role) in roleLabels" :key="role" :value="role">{{ label }}</option>
        </select>
      </label>
      <label class="admin-field">
        状态
        <select v-model="filters.status" class="admin-select">
          <option value="">全部状态</option>
          <option value="active">正常</option>
          <option value="disabled">已停用</option>
        </select>
      </label>
      <label class="admin-field">
        注册开始日期
        <input v-model="filters.created_from" class="admin-input" type="date" />
      </label>
      <label class="admin-field">
        注册结束日期
        <input v-model="filters.created_to" class="admin-input" type="date" />
      </label>
      <button class="admin-button" type="submit" :disabled="loading">查询</button>
    </form>
    <p v-if="error || filterError" class="admin-error" role="alert">
      {{ error || filterError }}
      <button v-if="error" type="button" class="admin-link" @click="load">重试</button>
    </p>
    <div class="admin-card">
      <div v-if="loading" class="admin-loading" role="status">正在加载账号…</div>
      <template v-else-if="data">
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>账号</th>
                <th>角色 / 状态</th>
                <th>注册时间</th>
                <th>最近登录</th>
                <th>最近学习</th>
                <th class="admin-numeric">提问 / 练习</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in data.items" :key="user.id">
                <td>
                  <router-link :to="`/admin/users/${user.id}`" class="admin-link">{{ user.display_name }}</router-link>
                  <small>{{ user.username }} · {{ user.student_id }}</small>
                </td>
                <td>
                  {{ roleLabels[user.role] }}
                  <small>
                    <span class="admin-pill" :class="`admin-pill--${user.status}`">
                      {{ user.status === 'active' ? '正常' : '已停用' }}
                    </span>
                  </small>
                </td>
                <td>{{ formatDate(user.created_at) }}</td>
                <td>{{ formatDate(user.last_login_at) }}</td>
                <td>{{ formatDate(user.last_learning_at) }}</td>
                <td class="admin-numeric">{{ formatNumber(user.questions) }} / {{ formatNumber(user.submissions) }}</td>
                <td><router-link :to="`/admin/users/${user.id}`" class="admin-link">查看详情</router-link></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!data.items.length" class="admin-empty">没有符合筛选条件的账号</p>
        <AdminPagination :page="page" :total="data.total" :loading="loading" @update:page="changePage" />
      </template>
    </div>
    <el-dialog
      v-model="createVisible"
      class="admin-dialog"
      title="创建账号"
      width="min(480px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      @closed="clearCreate"
    >
      <form class="admin-form" @submit.prevent="createUser">
        <label class="admin-field">
          用户名
          <input v-model.trim="form.username" class="admin-input" autocomplete="off" required maxlength="128" />
        </label>
        <label class="admin-field">
          显示名称
          <input v-model.trim="form.display_name" class="admin-input" required maxlength="128" />
        </label>
        <label class="admin-field">
          角色
          <select v-model="form.role" class="admin-select">
            <option v-for="(label, role) in roleLabels" :key="role" :value="role">{{ label }}</option>
          </select>
        </label>
        <p class="admin-note">{{ roleDescription[form.role] }}</p>
        <div class="admin-form-grid">
          <label class="admin-field">
            登录密码
            <input
              v-model="form.password"
              class="admin-input"
              type="password"
              autocomplete="new-password"
              required
              minlength="8"
              maxlength="256"
            />
          </label>
          <label class="admin-field">
            确认密码
            <input
              v-model="form.confirmPassword"
              class="admin-input"
              type="password"
              autocomplete="new-password"
              required
            />
          </label>
        </div>
        <p v-if="createError" class="admin-error" role="alert">{{ createError }}</p>
        <div class="admin-form-actions">
          <button type="button" class="admin-button" :disabled="saving" @click="createVisible = false">取消</button>
          <button type="submit" class="admin-button admin-button--primary" :disabled="saving">
            {{ saving ? '创建中…' : '确认创建' }}
          </button>
        </div>
      </form>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../../api/admin'
import { useAdminResource } from '../../composables/useAdminResource'
import { errorMessage, formatDate, formatNumber, roleLabels, roleDescription } from '../../utils/admin'
import AdminPagination from '../../components/admin/AdminPagination.vue'

const router = useRouter()
const filters = reactive({ q: '', role: '', status: '', created_from: '', created_to: '' })
const appliedFilters = ref({})
const filterError = ref('')
const page = ref(1)
const { data, loading, error, load } = useAdminResource(() =>
  adminApi.users({ ...appliedFilters.value, page: page.value, page_size: 20 })
)
const createVisible = ref(false)
const saving = ref(false)
const createError = ref('')
const form = reactive({ username: '', display_name: '', role: 'student', password: '', confirmPassword: '' })
function search() {
  filterError.value = ''
  if (filters.created_from && filters.created_to && filters.created_from > filters.created_to) {
    filterError.value = '注册开始日期不能晚于结束日期。'
    return
  }
  appliedFilters.value = Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
  page.value = 1
  load()
}
function changePage(value) {
  page.value = value
  load()
}
function clearCreate() {
  Object.assign(form, { username: '', display_name: '', role: 'student', password: '', confirmPassword: '' })
  createError.value = ''
}
function openCreate() {
  clearCreate()
  createVisible.value = true
}
async function createUser() {
  if (saving.value) return
  createError.value = ''
  if (form.password !== form.confirmPassword) {
    createError.value = '两次输入的密码不一致。'
    return
  }
  saving.value = true
  try {
    const user = await adminApi.createUser({
      username: form.username,
      display_name: form.display_name,
      role: form.role,
      password: form.password
    })
    createVisible.value = false
    ElMessage.success('账号已创建。')
    await router.push(`/admin/users/${user.id}`)
  } catch (cause) {
    createError.value = errorMessage(cause)
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>
