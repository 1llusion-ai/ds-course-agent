// Own browser URLs for deployments at / or a configured application subpath.
export function appPath(path = '') {
  return `${import.meta.env.BASE_URL}${String(path).replace(/^\/+/, '')}`
}

export function redirectToLogin() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('auth:unauthorized'))
  const { pathname, search, hash } = window.location
  if (pathname === appPath('login')) return
  const base = import.meta.env.BASE_URL
  const route = pathname.startsWith(base) ? `/${pathname.slice(base.length)}` : '/chat'
  window.location.assign(`${appPath('login')}?redirect=${encodeURIComponent(`${route}${search}${hash}`)}`)
}
