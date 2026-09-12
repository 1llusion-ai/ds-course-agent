<template>
  <span
    class="panel-toggle-icon"
    :class="`panel-toggle-icon--${side}`"
    aria-hidden="true"
  />
</template>

<script setup>
defineProps({
  side: { type: String, required: true, validator: value => ['start', 'end'].includes(value) }
})
</script>

<style scoped>
.panel-toggle-icon {
  position: relative;
  display: block;
  width: 16px;
  height: 14px;
  border: 1px solid currentColor;
  border-radius: 3px;
}

.panel-toggle-icon::after {
  position: absolute;
  top: 2px;
  bottom: 2px;
  width: 1px;
  content: '';
  background: currentColor;
}

.panel-toggle-icon--start::after {
  left: 4px;
}

.panel-toggle-icon--end::after {
  right: 4px;
}
</style>
