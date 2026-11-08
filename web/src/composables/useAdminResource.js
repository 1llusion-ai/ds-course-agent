import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { errorMessage } from '../utils/admin'

export function useAdminResource(fetcher, initialValue = null) {
  const data = shallowRef(initialValue)
  const loading = ref(false)
  const error = ref('')
  let version = 0

  async function load() {
    const current = ++version
    loading.value = true
    error.value = ''
    try {
      const result = await fetcher()
      if (current === version) data.value = result
      return result
    } catch (cause) {
      if (current === version) {
        data.value = initialValue
        error.value = errorMessage(cause)
      }
    } finally {
      if (current === version) loading.value = false
    }
  }

  onBeforeUnmount(() => {
    version++
  })
  return { data, loading, error, load }
}
