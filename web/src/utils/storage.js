/**
 * Keep browser-local UI state separate when the same browser is used by
 * multiple learners.
 */
export function accountStorageKey(namespace, user) {
  const identity = [user?.id, user?.student_id, user?.username, user?.email]
    .find(value => String(value || '').trim())
  const scope = identity ? encodeURIComponent(String(identity)) : 'anonymous'
  return `${namespace}.${scope}`
}

function getLocalStorage() {
  if (typeof window === 'undefined') return null

  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function readLocalStorage(key) {
  try {
    return getLocalStorage()?.getItem(key) ?? null
  } catch {
    return null
  }
}

export function writeLocalStorage(key, value) {
  try {
    getLocalStorage()?.setItem(key, value)
    return true
  } catch {
    return false
  }
}

export function removeLocalStorage(key) {
  try {
    getLocalStorage()?.removeItem(key)
    return true
  } catch {
    return false
  }
}
