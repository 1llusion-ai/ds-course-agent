<template>
  <nav v-if="total > 0" class="admin-pagination" aria-label="分页">
    <span>共 {{ total }} 条 · 第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
    <div class="admin-actions">
      <button
        class="admin-button"
        type="button"
        :disabled="loading || page <= 1"
        @click="$emit('update:page', page - 1)"
      >
        上一页
      </button>
      <button
        class="admin-button"
        type="button"
        :disabled="loading || page * pageSize >= total"
        @click="$emit('update:page', page + 1)"
      >
        下一页
      </button>
    </div>
  </nav>
</template>

<script setup>
defineProps({
  page: { type: Number, required: true },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  loading: Boolean
})
defineEmits(['update:page'])
</script>
