<template>
  <section class="admin-page">
    <header class="admin-page__header">
      <div>
        <h1>注册管理</h1>
        <p class="admin-page__description">按班级或用途创建和管理注册码。</p>
      </div>
      <button type="button" class="admin-button admin-button--primary" @click="openInvitation()">
        <el-icon aria-hidden="true"><Plus /></el-icon>
        创建注册码
      </button>
    </header>
    <p v-if="listError || actionError" class="admin-error" role="alert">
      {{ listError || actionError }}
      <button v-if="listError" class="admin-link" type="button" @click="loadInvitations">重新加载</button>
    </p>
    <section class="admin-card" aria-labelledby="invitations-title">
      <div class="admin-card__header">
        <div>
          <h2 id="invitations-title">注册码</h2>
          <p>注册码仅授予注册资格，新用户统一为学生。</p>
        </div>
        <span v-if="invitations" class="admin-note">共 {{ invitations.total }} 个</span>
      </div>
      <p v-if="listLoading" class="admin-loading" role="status">正在加载注册码…</p>
      <template v-else-if="invitations">
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>名称 / 注册码</th>
                <th>状态</th>
                <th>已注册人数</th>
                <th>有效期至</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="invitation in invitations.items" :key="invitation.id">
                <td>
                  <strong>{{ invitation.name }}</strong>
                  <code v-if="invitation.code" class="admin-invitation-code">{{ invitation.code }}</code>
                  <small v-else>旧码待补录</small>
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
                <td>{{ invitation.used_count }}</td>
                <td>{{ invitation.expires_at ? formatDate(invitation.expires_at) : '长期有效' }}</td>
                <td>
                  <div class="admin-actions">
                    <button v-if="invitation.code" class="admin-link" type="button" @click="copyCode(invitation.code)">
                      复制注册码
                    </button>
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
                    <button
                      class="admin-link admin-link--danger"
                      type="button"
                      :disabled="changingId !== null"
                      @click="deleteInvitation(invitation)"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!invitations.items.length" class="admin-empty">
          尚无注册码，创建后即可发放给学生。
          <button class="admin-link" type="button" @click="openInvitation()">立即创建</button>
        </p>
        <AdminPagination :page="page" :total="invitations.total" :loading="listLoading" @update:page="changePage" />
      </template>
    </section>
    <el-dialog
      v-model="editorVisible"
      class="admin-dialog"
      :title="editingId ? '编辑注册码' : '创建注册码'"
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
        <label v-if="!editingId || canRestoreCode" class="admin-field">
          {{ editingId ? '补录原注册码（选填）' : '注册码（选填）' }}
          <input
            v-model.trim="form.code"
            class="admin-input"
            :placeholder="editingId ? '输入原码，通过校验后显示在列表' : '留空则自动生成'"
            autocomplete="off"
            autocapitalize="none"
            spellcheck="false"
          />
        </label>
        <label class="admin-field">
          备注
          <textarea v-model.trim="form.note" class="admin-textarea" maxlength="1000" placeholder="发放用途或其他说明" />
        </label>
        <label class="admin-field">
          有效期至（上海时间）
          <input v-model="form.expires_at" class="admin-input" type="datetime-local" />
        </label>
        <p class="admin-note">有效期留空表示长期有效。</p>
        <p v-if="editorError" class="admin-error" role="alert">{{ editorError }}</p>
        <div class="admin-form-actions">
          <button class="admin-button" type="button" :disabled="savingInvitation" @click="editorVisible = false">
            取消
          </button>
          <button class="admin-button admin-button--primary" type="submit" :disabled="savingInvitation">
            {{ savingInvitation ? '保存中…' : editingId ? '保存修改' : '创建注册码' }}
          </button>
        </div>
      </form>
    </el-dialog>
    <el-dialog
      v-model="usesVisible"
      class="admin-dialog"
      :title="`${selectedInvitation?.name || '注册码'} · 使用记录`"
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
        <p v-if="!uses.items.length" class="admin-empty">暂无使用记录</p>
        <AdminPagination :page="usesPage" :total="uses.total" :loading="usesLoading" @update:page="changeUsesPage" />
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { adminApi } from '../../api/admin'
import { useAdminResource } from '../../composables/useAdminResource'
import { confirmAdminDeletion, errorMessage, formatDate, inviteStatusLabels } from '../../utils/admin'
import AdminPagination from '../../components/admin/AdminPagination.vue'

const page = ref(1)
const {
  data: invitations,
  loading: listLoading,
  error: listError,
  load: loadInvitations
} = useAdminResource(() => adminApi.invitations({ page: page.value, page_size: 20 }))
const actionError = ref('')
const changingId = ref(null)
const editorVisible = ref(false)
const editingId = ref(null)
const canRestoreCode = ref(false)
const savingInvitation = ref(false)
const editorError = ref('')
const form = reactive({ name: '', code: '', note: '', expires_at: '' })
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
function changePage(value) {
  page.value = value
  loadInvitations()
}
function shanghaiLocalInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 16)
}
function openInvitation(invitation = null) {
  editingId.value = invitation?.id || null
  canRestoreCode.value = Boolean(invitation && !invitation.code)
  Object.assign(form, {
    name: invitation?.name || '',
    code: '',
    note: invitation?.note || '',
    expires_at: shanghaiLocalInput(invitation?.expires_at)
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
    expires_at: form.expires_at ? `${form.expires_at}:00+08:00` : null
  }
  try {
    if (editingId.value) {
      if (canRestoreCode.value && form.code) payload.code = form.code
      await adminApi.updateInvitation(editingId.value, payload)
      ElMessage.success('注册码已更新。')
    } else {
      await adminApi.createInvitation({ ...payload, code: form.code })
      ElMessage.success('注册码已创建。')
      page.value = 1
    }
    form.code = ''
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
      `${verb}「${invitation.name}」？此操作仅影响后续注册。`,
      `${verb}注册码`,
      { confirmButtonText: `确认${verb}`, cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  changingId.value = invitation.id
  actionError.value = ''
  try {
    await adminApi.updateInvitation(invitation.id, { enabled: !invitation.enabled })
    ElMessage.success(`注册码已${verb}。`)
    await loadInvitations()
  } catch (cause) {
    actionError.value = errorMessage(cause)
  } finally {
    changingId.value = null
  }
}
async function deleteInvitation(invitation) {
  if (
    !(await confirmAdminDeletion(
      `删除注册码「${invitation.name}」？删除后该码会失效，且无法在管理台恢复。使用过该码的账号仍可登录。`,
      '删除注册码'
    ))
  ) return
  changingId.value = invitation.id
  actionError.value = ''
  try {
    await adminApi.deleteInvitation(invitation.id)
    ElMessage.success('注册码已删除。')
    if (invitations.value?.items.length === 1 && page.value > 1) page.value--
    await loadInvitations()
  } catch (cause) {
    actionError.value = errorMessage(cause)
  } finally {
    changingId.value = null
  }
}
async function copyCode(code) {
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success('注册码已复制。')
  } catch {
    ElMessage.warning('浏览器暂不支持复制，请选中列表中的注册码手动复制。')
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
onMounted(loadInvitations)
</script>
