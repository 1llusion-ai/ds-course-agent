<template>
  <section class="admin-page">
    <header class="admin-page__header">
      <div>
        <h1>注册与邀请码</h1>
        <p class="admin-page__description">控制注册入口，按班级或用途发放邀请。</p>
      </div>
      <button type="button" class="admin-button admin-button--primary" @click="openInvitation()">
        <el-icon aria-hidden="true"><Plus /></el-icon>
        创建邀请码
      </button>
    </header>
    <p v-if="policyError || listError || actionError" class="admin-error" role="alert">
      {{ policyError || listError || actionError }}
      <button v-if="policyError || listError" class="admin-link" type="button" @click="reload">重新加载</button>
    </p>
    <section class="admin-card" aria-labelledby="registration-policy-title">
      <div class="admin-card__header">
        <div>
          <h2 id="registration-policy-title">注册设置</h2>
          <p>关闭注册只影响新账号，已有账号可以正常登录。</p>
        </div>
      </div>
      <p v-if="policyLoading" class="admin-loading">正在加载注册设置…</p>
      <form v-else-if="policy" class="admin-form" @submit.prevent="savePolicy">
        <div class="admin-form-grid">
          <label class="admin-field">
            注册方式
            <select v-model="policyForm.mode" class="admin-select">
              <option v-if="policy.mode === 'open'" value="open" disabled>当前为开发环境开放注册</option>
              <option value="invite">开放邀请注册</option>
              <option value="closed">关闭注册</option>
            </select>
          </label>
          <label class="admin-field">
            全站账号容量
            <input v-model.number="policyForm.max_users" class="admin-input" type="number" min="0" step="1" required />
          </label>
        </div>
        <div class="admin-actions">
          <p class="admin-note">
            0 表示不限。当前 {{ policy.total_users }} 个账号，剩余
            {{ policy.remaining_capacity == null ? '不限' : `${policy.remaining_capacity} 个名额` }}。
          </p>
          <button class="admin-button" type="submit" :disabled="savingPolicy || policyForm.mode === 'open'">
            {{ savingPolicy ? '保存中…' : '保存注册设置' }}
          </button>
        </div>
      </form>
    </section>
    <section class="admin-card" aria-labelledby="invitations-title">
      <div class="admin-card__header">
        <div>
          <h2 id="invitations-title">邀请码</h2>
          <p>邀请码仅授予注册资格，新用户统一为学生。</p>
        </div>
        <span v-if="invitations" class="admin-note">共 {{ invitations.total }} 个</span>
      </div>
      <p v-if="listLoading" class="admin-loading" role="status">正在加载邀请码…</p>
      <template v-else-if="invitations">
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>名称 / 标识</th>
                <th>状态</th>
                <th>使用次数</th>
                <th>有效期至</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="invitation in invitations.items" :key="invitation.id">
                <td>
                  <strong>{{ invitation.name }}</strong>
                  <small>{{ invitation.code_hint }}</small>
                  <small v-if="invitation.note" class="admin-wrap">{{ invitation.note }}</small>
                </td>
                <td>
                  <span
                    class="admin-pill"
                    :class="
                      invitation.status === 'active'
                        ? 'admin-pill--active'
                        : invitation.status === 'disabled'
                          ? 'admin-pill--disabled'
                          : ''
                    "
                  >
                    {{ inviteStatusLabels[invitation.status] }}
                  </span>
                </td>
                <td>{{ invitation.used_count }} / {{ invitation.max_uses || '不限' }}</td>
                <td>{{ invitation.expires_at ? formatDate(invitation.expires_at) : '长期有效' }}</td>
                <td>
                  <div class="admin-actions">
                    <button class="admin-link" type="button" @click="openInvitation(invitation)">编辑</button>
                    <button class="admin-link" type="button" @click="showUses(invitation)">使用记录</button>
                    <button
                      class="admin-link"
                      type="button"
                      :disabled="changingId === invitation.id"
                      @click="toggleInvitation(invitation)"
                    >
                      {{ invitation.enabled ? '停用' : '恢复' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!invitations.items.length" class="admin-empty">
          尚无邀请码，创建后即可发放给学生。
          <button class="admin-link" type="button" @click="openInvitation()">立即创建</button>
        </p>
        <AdminPagination :page="page" :total="invitations.total" :loading="listLoading" @update:page="changePage" />
      </template>
    </section>
    <el-dialog
      v-model="editorVisible"
      class="admin-dialog"
      :title="editingId ? '编辑邀请码' : '创建邀请码'"
      width="min(500px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <form class="admin-form" @submit.prevent="saveInvitation">
        <label class="admin-field">
          名称
          <input
            v-model.trim="form.name"
            class="admin-input"
            placeholder="例如：2026 秋季一班"
            required
            maxlength="128"
          />
        </label>
        <label class="admin-field">
          备注
          <textarea v-model.trim="form.note" class="admin-textarea" maxlength="1000" placeholder="发放用途或其他说明" />
        </label>
        <div class="admin-form-grid">
          <label class="admin-field">
            有效期至（上海时间）
            <input v-model="form.expires_at" class="admin-input" type="datetime-local" />
          </label>
          <label class="admin-field">
            使用次数上限
            <input v-model.number="form.max_uses" class="admin-input" type="number" min="0" step="1" required />
          </label>
        </div>
        <p class="admin-note">有效期留空表示长期有效，次数设为 0 表示不限。</p>
        <p v-if="editorError" class="admin-error" role="alert">{{ editorError }}</p>
        <div class="admin-form-actions">
          <button class="admin-button" type="button" :disabled="savingInvitation" @click="editorVisible = false">
            取消
          </button>
          <button class="admin-button admin-button--primary" type="submit" :disabled="savingInvitation">
            {{ savingInvitation ? '保存中…' : editingId ? '保存修改' : '生成邀请码' }}
          </button>
        </div>
      </form>
    </el-dialog>
    <el-dialog
      v-model="codeVisible"
      class="admin-dialog"
      title="邀请码已创建"
      width="min(480px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="false"
      @closed="createdCode = ''"
    >
      <p class="admin-note">完整邀请码仅展示这一次。请复制保存后发放，之后可在列表中管理有效期和使用次数。</p>
      <div class="admin-code" data-testid="created-invitation-code">{{ createdCode }}</div>
      <p v-if="copyError" class="admin-error" role="alert">{{ copyError }}</p>
      <div class="admin-form-actions">
        <button type="button" class="admin-button" @click="copyCode">{{ copied ? '已复制' : '复制邀请码' }}</button>
        <button type="button" class="admin-button admin-button--primary" @click="codeVisible = false">
          已保存，关闭
        </button>
      </div>
    </el-dialog>
    <el-dialog
      v-model="usesVisible"
      class="admin-dialog"
      :title="`${selectedInvitation?.name || '邀请码'} · 使用记录`"
      width="min(650px, calc(100vw - 32px))"
    >
      <p v-if="usesError" class="admin-error" role="alert">
        {{ usesError }}
        <button type="button" class="admin-link" @click="loadUses">重试</button>
      </p>
      <p v-if="usesLoading" class="admin-loading">正在加载使用记录…</p>
      <template v-else-if="uses">
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>账号</th>
                <th>注册时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="usage in uses.items" :key="usage.user_id">
                <td>
                  <router-link class="admin-link" :to="`/admin/users/${usage.user_id}`" @click="usesVisible = false">
                    {{ usage.display_name }}
                  </router-link>
                  <small>{{ usage.username }}</small>
                </td>
                <td>{{ formatDate(usage.registered_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!uses.items.length" class="admin-empty">该邀请码尚未用于注册</p>
        <AdminPagination :page="usesPage" :total="uses.total" :loading="usesLoading" @update:page="changeUsesPage" />
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { adminApi } from '../../api/admin'
import { useAdminResource } from '../../composables/useAdminResource'
import { errorMessage, formatDate, inviteStatusLabels } from '../../utils/admin'
import AdminPagination from '../../components/admin/AdminPagination.vue'

const page = ref(1)
const {
  data: policy,
  loading: policyLoading,
  error: policyError,
  load: loadPolicy
} = useAdminResource(adminApi.registrationPolicy)
const {
  data: invitations,
  loading: listLoading,
  error: listError,
  load: loadInvitations
} = useAdminResource(() => adminApi.invitations({ page: page.value, page_size: 20 }))
const policyForm = reactive({ mode: 'invite', max_users: 0 })
const savingPolicy = ref(false)
const actionError = ref('')
const changingId = ref(null)
const editorVisible = ref(false)
const editingId = ref(null)
const savingInvitation = ref(false)
const editorError = ref('')
const form = reactive({ name: '', note: '', expires_at: '', max_uses: 0 })
const codeVisible = ref(false)
const createdCode = ref('')
const copied = ref(false)
const copyError = ref('')
const usesVisible = ref(false)
const selectedInvitation = ref(null)
const usesPage = ref(1)
const {
  data: uses,
  loading: usesLoading,
  error: usesError,
  load: loadUses
} = useAdminResource(() =>
  adminApi.invitationUses(selectedInvitation.value.id, { page: usesPage.value, page_size: 20 })
)
watch(policy, (value) => {
  if (value) Object.assign(policyForm, { mode: value.mode, max_users: value.max_users })
})
function reload() {
  loadPolicy()
  loadInvitations()
}
function changePage(value) {
  page.value = value
  loadInvitations()
}
async function savePolicy() {
  actionError.value = ''
  try {
    await ElMessageBox.confirm(
      `将注册方式设为「${policyForm.mode === 'closed' ? '关闭注册' : '邀请注册'}」，账号容量设为 ${policyForm.max_users || '不限'}。`,
      '保存注册设置',
      { confirmButtonText: '确认保存', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  savingPolicy.value = true
  try {
    await adminApi.updateRegistrationPolicy({ ...policyForm })
    ElMessage.success('注册设置已更新。')
    await loadPolicy()
  } catch (cause) {
    actionError.value = errorMessage(cause)
  } finally {
    savingPolicy.value = false
  }
}
function shanghaiLocalInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 16)
}
function openInvitation(invitation = null) {
  editingId.value = invitation?.id || null
  Object.assign(form, {
    name: invitation?.name || '',
    note: invitation?.note || '',
    expires_at: shanghaiLocalInput(invitation?.expires_at),
    max_uses: invitation?.max_uses || 0
  })
  editorError.value = ''
  editorVisible.value = true
}
async function saveInvitation() {
  if (savingInvitation.value) return
  savingInvitation.value = true
  editorError.value = ''
  const payload = {
    name: form.name,
    note: form.note,
    expires_at: form.expires_at ? `${form.expires_at}:00+08:00` : null,
    max_uses: form.max_uses
  }
  try {
    if (editingId.value) {
      await adminApi.updateInvitation(editingId.value, payload)
      ElMessage.success('邀请码已更新。')
    } else {
      const result = await adminApi.createInvitation(payload)
      createdCode.value = result.code
      copied.value = false
      copyError.value = ''
      codeVisible.value = true
      page.value = 1
    }
    editorVisible.value = false
    await loadInvitations()
  } catch (cause) {
    editorError.value = errorMessage(cause)
  } finally {
    savingInvitation.value = false
  }
}
async function toggleInvitation(invitation) {
  const verb = invitation.enabled ? '停用' : '恢复'
  try {
    await ElMessageBox.confirm(
      `${verb}「${invitation.name}」？已有账号不会受到影响，有效期和次数限制仍然生效。`,
      `${verb}邀请码`,
      { confirmButtonText: `确认${verb}`, cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  changingId.value = invitation.id
  actionError.value = ''
  try {
    await adminApi.updateInvitation(invitation.id, { enabled: !invitation.enabled })
    ElMessage.success(`邀请码已${verb}。`)
    await loadInvitations()
  } catch (cause) {
    actionError.value = errorMessage(cause)
  } finally {
    changingId.value = null
  }
}
async function copyCode() {
  try {
    await navigator.clipboard.writeText(createdCode.value)
    copied.value = true
    copyError.value = ''
  } catch {
    copyError.value = '浏览器暂不支持复制，请选中上方邀请码手动复制。'
  }
}
function showUses(invitation) {
  selectedInvitation.value = invitation
  usesPage.value = 1
  usesVisible.value = true
  loadUses()
}
function changeUsesPage(value) {
  usesPage.value = value
  loadUses()
}
onMounted(reload)
</script>
