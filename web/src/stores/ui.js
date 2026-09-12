import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { readLocalStorage, writeLocalStorage } from '../utils/storage'

const THEME_STORAGE_KEY = 'ds-course-agent.theme'
const THEME_VALUES = new Set(['system', 'light', 'dark'])

function readThemePreference() {
  if (typeof window === 'undefined') return 'system'
  const stored = readLocalStorage(THEME_STORAGE_KEY)
  return THEME_VALUES.has(stored) ? stored : 'system'
}

export const useUiStore = defineStore('ui', () => {
  const theme = ref(readThemePreference())
  const systemPrefersDark = ref(false)
  let mediaQuery = null
  let initialized = false

  const resolvedTheme = computed(() => (
    theme.value === 'system'
      ? (systemPrefersDark.value ? 'dark' : 'light')
      : theme.value
  ))

  function applyTheme() {
    if (typeof document === 'undefined') return
    const isDark = resolvedTheme.value === 'dark'
    document.documentElement.classList.toggle('theme-dark', isDark)
    document.documentElement.dataset.theme = resolvedTheme.value
    document.documentElement.style.colorScheme = resolvedTheme.value
  }

  function setTheme(nextTheme) {
    if (!THEME_VALUES.has(nextTheme)) return
    theme.value = nextTheme
    if (typeof window !== 'undefined') {
      writeLocalStorage(THEME_STORAGE_KEY, nextTheme)
    }
    applyTheme()
  }

  function initialize() {
    if (initialized || typeof window === 'undefined') {
      applyTheme()
      return
    }

    initialized = true
    if (typeof window.matchMedia === 'function') {
      mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
      systemPrefersDark.value = mediaQuery.matches
      mediaQuery.addEventListener('change', event => {
        systemPrefersDark.value = event.matches
        if (theme.value === 'system') applyTheme()
      })
    }
    applyTheme()
  }

  return {
    theme,
    resolvedTheme,
    initialize,
    setTheme
  }
})
