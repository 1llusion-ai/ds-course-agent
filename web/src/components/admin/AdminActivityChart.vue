<template>
  <div v-if="rows.length" role="img" :aria-label="`每日提问趋势，${rows.length} 天，共 ${total} 次提问`">
    <svg class="admin-chart" viewBox="0 0 840 180" preserveAspectRatio="none" aria-hidden="true">
      <line
        v-for="y in [20, 90, 160]"
        :key="y"
        x1="0"
        :y1="y"
        x2="840"
        :y2="y"
        stroke="var(--admin-border)"
        stroke-dasharray="3 5"
      />
      <rect
        v-for="(row, index) in rows"
        :key="row.date"
        :x="index * step + 3"
        :y="160 - height(row.questions)"
        :width="Math.max(2, step - 6)"
        :height="height(row.questions)"
        rx="3"
        fill="var(--admin-accent)"
        :opacity="index === rows.length - 1 ? 1 : 0.55"
      >
        <title>{{ row.date }}：{{ row.questions }} 次提问</title>
      </rect>
    </svg>
    <div class="admin-chart__axis">
      <span>{{ rows[0].date }}</span>
      <span>单日最高 {{ maximum }} 次</span>
      <span>{{ rows[rows.length - 1].date }}</span>
    </div>
  </div>
  <p v-else class="admin-empty">所选时间内暂无提问记录</p>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ rows: { type: Array, default: () => [] } })
const maximum = computed(() => Math.max(0, ...props.rows.map((row) => row.questions)))
const total = computed(() => props.rows.reduce((sum, row) => sum + row.questions, 0))
const step = computed(() => 840 / Math.max(1, props.rows.length))
function height(value) {
  return value ? (140 * value) / Math.max(1, maximum.value) : 1
}
</script>
