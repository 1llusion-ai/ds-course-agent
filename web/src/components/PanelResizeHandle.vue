<template>
  <div
    class="panel-resize-handle"
    :class="`panel-resize-handle--${side}`"
    role="separator"
    aria-orientation="vertical"
    :aria-label="label"
    :aria-valuemin="min"
    :aria-valuemax="max"
    :aria-valuenow="Math.round(value)"
    tabindex="0"
    @pointerdown="$emit('resize-start', $event)"
    @keydown="$emit('resize-keydown', $event)"
    @dblclick="$emit('reset')"
  />
</template>

<script setup>
defineProps({
  side: { type: String, required: true, validator: value => ['start', 'end'].includes(value) },
  label: { type: String, required: true },
  value: { type: Number, required: true },
  min: { type: Number, required: true },
  max: { type: Number, required: true }
})

defineEmits(['resize-start', 'resize-keydown', 'reset'])
</script>

<style scoped>
.panel-resize-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 20;
  width: 9px;
  padding: 0;
  touch-action: none;
  cursor: col-resize;
  outline: 0;
}

.panel-resize-handle--start {
  right: -5px;
}

.panel-resize-handle--end {
  left: -5px;
}

.panel-resize-handle::after {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 4px;
  width: 1px;
  content: '';
  background: transparent;
  transition: background 0.14s ease, box-shadow 0.14s ease;
}

.panel-resize-handle:hover::after,
.panel-resize-handle:focus-visible::after {
  background: #a8a29e;
  box-shadow: 0 0 0 1px rgba(168, 162, 158, 0.16);
}

html.theme-dark .panel-resize-handle:hover::after,
html.theme-dark .panel-resize-handle:focus-visible::after {
  background: #737373;
  box-shadow: none;
}

@media (max-width: 900px) {
  .panel-resize-handle {
    display: none;
  }
}
</style>
