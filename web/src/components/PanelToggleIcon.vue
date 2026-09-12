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
  width: 15px;
  height: 13px;
  border: 1.5px solid currentColor;
  border-radius: 3px;
}

.panel-toggle-icon::after {
  position: absolute;
  top: 1px;
  bottom: 1px;
  width: 1.5px;
  content: '';
  background: currentColor;
  border-radius: 1px;
}

.panel-toggle-icon--start::after {
  left: 3px;
}

.panel-toggle-icon--end::after {
  right: 3px;
}
</style>
