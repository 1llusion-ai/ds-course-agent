const AUTH_REDIRECT_BASE = 'https://course.invalid'
const AUTHENTICATED_ROUTE = /^\/(chat|profile|settings|knowledge-map|assessments|admin)(?:\/|$)/

// Accept only known application routes. Authorization still belongs to the router/backend.
export function authenticatedRedirect(value) {
  if (
    typeof value !== 'string' ||
    !value.startsWith('/') ||
    value.startsWith('//') ||
    /[\\\u0000-\u0020]/.test(value)
  ) {
    return '/chat'
  }
  try {
    const parsed = new URL(value, AUTH_REDIRECT_BASE)
    if (parsed.origin !== AUTH_REDIRECT_BASE || !AUTHENTICATED_ROUTE.test(parsed.pathname)) return '/chat'
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return '/chat'
  }
}
