<template>
  <section class="admin-page">
    <header class="admin-page__header">
      <div>
        <h1>操作记录</h1>
        <p class="admin-page__description">追溯账号、权限、注册设置和邀请码的管理变更。</p>
      </div>
    </header>
    <form class="admin-toolbar" @submit.prevent="search">
      <label class="admin-field admin-field--search">
        搜索记录
        <input v-model.trim="query" type="search" class="admin-input" placeholder="操作者、目标或操作类型" />
      </label>
      <button class="admin-button" type="submit" :disabled="loading">查询</button>
    </form>
    <p v-if="error" class="admin-error" role="alert">
      {{ error }}
      <button class="admin-link" type="button" @click="load">重试</button>
    </p>
    <section class="admin-card">
      <p v-if="loading" class="admin-loading" role="status">正在加载操作记录…</p>
      <template v-else-if="data">
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作者</th>
                <th>操作</th>
                <th>目标</th>
                <th>变更内容</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in data.items" :key="entry.id">
                <td>{{ formatDate(entry.created_at) }}</td>
                <td>{{ entry.actor }}</td>
                <td>{{ actionLabel(entry.action) }}</td>
                <td class="admin-wrap">{{ entry.target }}</td>
                <td><button class="admin-link" type="button" @click="selectedEntry = entry">查看变更</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!data.items.length" class="admin-empty">暂无符合条件的操作记录</p>
        <AdminPagination :page="page" :total="data.total" :loading="loading" @update:page="changePage" />
      </template>
    </section>
    <el-dialog
      :model-value="Boolean(selectedEntry)"
      class="admin-dialog"
      title="变更详情"
      width="min(640px, calc(100vw - 32px))"
      @update:model-value="selectedEntry = null"
    >
      <template v-if="selectedEntry">
        <p class="admin-note">
          {{ selectedEntry.actor }} · {{ actionLabel(selectedEntry.action) }} ·
          {{ formatDate(selectedEntry.created_at) }}
        </p>
        <div v-if="changeRows.length" class="admin-table-wrap" style="margin-top: 20px">
          <table class="admin-table admin-audit-changes">
            <thead>
              <tr>
                <th>字段</th>
                <th>变更前</th>
                <th>变更后</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in changeRows" :key="row.key">
                <th>{{ row.label }}</th>
                <td class="admin-wrap">{{ row.before }}</td>
                <td class="admin-wrap">{{ row.after }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="admin-note" style="margin-top: 20px">操作已完成，无可展示的字段变更。</p>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { adminApi } from '../../api/admin'
import { useAdminResource } from '../../composables/useAdminResource'
import { formatDate, roleLabels, inviteStatusLabels } from '../../utils/admin'
import AdminPagination from '../../components/admin/AdminPagination.vue'

const query = ref('')
const appliedQuery = ref('')
const page = ref(1)
const selectedEntry = ref(null)
const { data, loading, error, load } = useAdminResource(() =>
  adminApi.audit({ q: appliedQuery.value, page: page.value, page_size: 20 })
)
const actionLabels = {
  'account.create': '创建账号',
  'account.update': '修改账号',
  'account.password_reset': '重置密码',
  'account.revoke_sessions': '撤销登录',
  'invitation.create': '创建邀请码',
  'invitation.update': '修改邀请码',
  'registration.update': '修改注册设置',
  'registration.import_legacy': '迁移注册配置',
  'account.provision': '本地创建或更新账号',
  'account.bootstrap_admin': '初始化管理员'
}
const fieldLabels = {
  id: '记录 ID',
  display_name: '显示名称',
  role: '角色',
  status: '状态',
  mode: '注册方式',
  max_users: '账号容量',
  name: '名称',
  note: '备注',
  expires_at: '有效期',
  max_uses: '次数上限',
  enabled: '启用',
  used_count: '已使用次数',
  created_at: '创建时间',
  code_hint: '邀请码标识'
}
const changeRows = computed(() => {
  if (!selectedEntry.value) return []
  const before = selectedEntry.value.before || {}
  const after = selectedEntry.value.after || {}
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].map((key) => ({
    key,
    label: fieldLabels[key] || key,
    before: fieldValue(key, before[key]),
    after: fieldValue(key, after[key])
  }))
})
function fieldValue(key, value) {
  if (value == null) return key === 'expires_at' && value === null ? '长期有效' : '—'
  if (key === 'role') return roleLabels[value] || value
  if (key === 'status') return { ...inviteStatusLabels, active: '正常', disabled: '已停用' }[value] || value
  if (key === 'mode') return { invite: '邀请注册', closed: '关闭注册', open: '开放注册' }[value] || value
  if (key === 'max_users' || key === 'max_uses') return value === 0 ? '不限' : String(value)
  if (key === 'created_at' || key === 'expires_at') return formatDate(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return value === '' ? '—' : String(value)
}
function actionLabel(action) {
  return actionLabels[action] || action
}
function search() {
  appliedQuery.value = query.value
  page.value = 1
  load()
}
function changePage(value) {
  page.value = value
  load()
}
onMounted(load)
</script>
