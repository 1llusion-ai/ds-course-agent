<template>
  <aside
    class="resizable-side-panel"
    :class="[
      `resizable-side-panel--${side}`,
      `resizable-side-panel--mobile-${mobileMode}`,
      {
        'resizable-side-panel--closed': !open,
        'resizable-side-panel--resizing': isResizing
      }
    ]"
    :style="panelStyle"
    :aria-label="label"
    :aria-hidden="!open"
    :inert="!open"
  >
    <PanelResizeHandle
      v-if="open"
      :side="side"
      :label="resizeLabel"
      :value="width"
      :min="minWidth"
      :max="maxWidth"
      @resize-start="startResize"
      @resize-keydown="resizeFromKeyboard"
      @reset="resetWidth"
    />
    <div class="resizable-side-panel__content">
      <slot :close="close" />
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

import { useResizablePanel } from '../composables/useResizablePanel'
import PanelResizeHandle from './PanelResizeHandle.vue'

const props = defineProps({
  open: { type: Boolean, required: true },
  side: { type: String, required: true, validator: value => ['start', 'end'].includes(value) },
  label: { type: String, required: true },
  resizeLabel: { type: String, required: true },
  storageKey: { type: String, required: true },
  defaultWidth: { type: Number, required: true },
  minWidth: { type: Number, required: true },
  maxWidth: { type: Number, required: true },
  collapseThreshold: { type: Number, default: null },
  mobileMode: {
    type: String,
    default: 'flow',
    validator: value => ['flow', 'overlay'].includes(value)
  },
  mobileMaxWidth: { type: String, default: '92vw' }
})

const emit = defineEmits(['update:open'])

const {
  width,
  isResizing,
  startResize,
  resizeFromKeyboard,
  resetWidth
} = useResizablePanel({
  storageKey: props.storageKey,
  defaultWidth: props.defaultWidth,
  minWidth: props.minWidth,
  maxWidth: props.maxWidth,
  side: props.side,
  collapseThreshold: props.collapseThreshold ?? props.minWidth - 20,
  onCollapse: close
})

const panelStyle = computed(() => ({
  '--resizable-panel-width': `${width.value}px`,
  '--resizable-panel-min-width': `${props.minWidth}px`,
  '--resizable-panel-mobile-max-width': props.mobileMaxWidth
}))

function close() {
  emit('update:open', false)
}
</script>

<style scoped>
.resizable-side-panel {
  position: relative;
  box-sizing: border-box;
  flex: 0 0 auto;
  width: var(--resizable-panel-width);
  min-width: 0;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  transition: width 200ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: width;
}

.resizable-side-panel--closed {
  width: 0;
  pointer-events: none;
}

.resizable-side-panel--resizing {
  transition: none;
}

.resizable-side-panel--start > .panel-resize-handle {
  right: 0;
}

.resizable-side-panel--end > .panel-resize-handle {
  left: 0;
}

.resizable-side-panel__content {
  position: absolute;
  top: 0;
  bottom: 0;
  box-sizing: border-box;
  width: max(var(--resizable-panel-width), var(--resizable-panel-min-width));
}

.resizable-side-panel--start > .resizable-side-panel__content {
  left: 0;
}

.resizable-side-panel--end > .resizable-side-panel__content {
  right: 0;
}

@media (max-width: 900px) {
  .resizable-side-panel--mobile-flow {
    width: 100%;
    height: auto;
    overflow: visible;
    transition: none;
  }

  .resizable-side-panel--mobile-flow.resizable-side-panel--closed {
    display: none;
  }

  .resizable-side-panel--mobile-flow > .resizable-side-panel__content {
    position: static;
    width: 100%;
  }

  .resizable-side-panel--mobile-overlay {
    position: absolute;
    top: 0;
    bottom: 0;
    z-index: 30;
  }

  .resizable-side-panel--mobile-overlay.resizable-side-panel--start {
    left: 0;
  }

  .resizable-side-panel--mobile-overlay.resizable-side-panel--end {
    right: 0;
  }

  .resizable-side-panel--mobile-overlay:not(.resizable-side-panel--closed),
  .resizable-side-panel--mobile-overlay > .resizable-side-panel__content {
    width: min(var(--resizable-panel-mobile-max-width), var(--resizable-panel-width));
  }
}

@media (prefers-reduced-motion: reduce) {
  .resizable-side-panel {
    transition: none;
  }
}
</style>
