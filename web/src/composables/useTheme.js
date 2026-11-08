import { computed, ref, watch } from 'vue'

const STORAGE_KEY = 'ds-course-agent.theme'
const theme = ref(
  typeof window !== 'undefined' && window.localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light'
)

function applyTheme(value) {
  if (typeof document === 'undefined') return
  const dark = value === 'dark'
  document.documentElement.classList.toggle('theme-dark', dark)
  document.body?.classList.toggle('theme-dark', dark)
  document.getElementById('app')?.classList.toggle('theme-dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

export function useTheme() {
  watch(theme, applyTheme, { immediate: true })
  const isDarkTheme = computed(() => theme.value === 'dark')
  function toggleTheme() {
    theme.value = isDarkTheme.value ? 'light' : 'dark'
    window.localStorage.setItem(STORAGE_KEY, theme.value)
  }
  return { isDarkTheme, toggleTheme }
}
