import { onBeforeUnmount, ref } from 'vue'

import { readLocalStorage, writeLocalStorage } from '../utils/storage'

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

export function useResizablePanel({ storageKey, defaultWidth, minWidth, maxWidth, side = 'start' }) {
  const width = ref(readStoredWidth())
  const isResizing = ref(false)
  let resizeState = null
  let previousCursor = ''
  let previousUserSelect = ''

  function readStoredWidth() {
    if (typeof window === 'undefined') return defaultWidth
    const stored = Number.parseFloat(readLocalStorage(storageKey))
    return Number.isFinite(stored) ? clamp(stored, minWidth, maxWidth) : defaultWidth
  }

  function persistWidth() {
    if (typeof window !== 'undefined') {
      writeLocalStorage(storageKey, String(Math.round(width.value)))
    }
  }

  function startResize(event) {
    if (event.button !== 0) return
    event.preventDefault()
    isResizing.value = true
    resizeState = { pointerX: event.clientX, width: width.value }
    previousCursor = document.documentElement.style.cursor
    previousUserSelect = document.documentElement.style.userSelect
    document.documentElement.style.cursor = 'col-resize'
    document.documentElement.style.userSelect = 'none'
    window.addEventListener('pointermove', resizeFromPointer)
    window.addEventListener('pointerup', stopResize, { once: true })
    window.addEventListener('pointercancel', stopResize, { once: true })
    window.addEventListener('blur', stopResize, { once: true })
  }

  function resizeFromPointer(event) {
    if (!resizeState) return
    const direction = side === 'start' ? 1 : -1
    width.value = clamp(
      resizeState.width + ((event.clientX - resizeState.pointerX) * direction),
      minWidth,
      maxWidth
    )
  }

  function stopResize() {
    if (!resizeState) return
    resizeState = null
    isResizing.value = false
    document.documentElement.style.cursor = previousCursor
    document.documentElement.style.userSelect = previousUserSelect
    window.removeEventListener('pointermove', resizeFromPointer)
    window.removeEventListener('pointerup', stopResize)
    window.removeEventListener('pointercancel', stopResize)
    window.removeEventListener('blur', stopResize)
    persistWidth()
  }

  function resizeFromKeyboard(event) {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
    event.preventDefault()
    const keyboardDirection = event.key === 'ArrowRight' ? 1 : -1
    const panelDirection = side === 'start' ? 1 : -1
    width.value = clamp(width.value + (keyboardDirection * panelDirection * 12), minWidth, maxWidth)
    persistWidth()
  }

  function resetWidth() {
    width.value = defaultWidth
    persistWidth()
  }

  onBeforeUnmount(stopResize)

  return { width, isResizing, startResize, resizeFromKeyboard, resetWidth }
}
