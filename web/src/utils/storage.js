/**
 * Derive browser-storage namespaces from the authenticated account so a shared
 * browser never surfaces one learner's local UI state to another learner.
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

/** Read local UI preferences without making private-browsing storage a fatal dependency. */
export function readLocalStorage(key) {
  try {
    return getLocalStorage()?.getItem(key) ?? null
  } catch {
    return null
  }
}

/** Persist optional local UI preferences when the browser permits storage. */
export function writeLocalStorage(key, value) {
  try {
    getLocalStorage()?.setItem(key, value)
    return true
  } catch {
    return false
  }
}

/** Remove optional local UI preferences when the browser permits storage. */
export function removeLocalStorage(key) {
  try {
    getLocalStorage()?.removeItem(key)
    return true
  } catch {
    return false
  }
}
