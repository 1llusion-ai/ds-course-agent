<template>
  <details class="assessment-source">
    <summary>
      <span>{{ source.source || '课程教材' }}</span>
      <small v-if="source.page">第 {{ source.page }} 页</small>
    </summary>
    <blockquote>{{ source.text }}</blockquote>
  </details>
</template>

<script setup>
defineProps({ source: { type: Object, required: true } })
</script>
