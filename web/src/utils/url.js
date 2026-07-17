export function domainFromUrl(url) {
  if (!url) return ''
  try {
    const host = new URL(url).hostname || ''
    return host.startsWith('www.') ? host.slice(4) : host
  } catch (error) {
    return ''
  }
}

export function faviconUrl(url, domain = '') {
  const host = domain || domainFromUrl(url)
  if (!host) return ''
  // Use the site's own favicon instead of a third-party favicon service.
  // The previous Google S2 endpoint is unreachable in some regions, which
  // silently broke every web-source icon. Per-site favicon.ico has no such
  // dependency; callers render an emoji fallback when this is empty or 404s.
  return `https://${host}/favicon.ico`
}

export function isExternalUrl(value) {
  if (!value) return false
  try {
    const parsed = new URL(String(value))
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch (error) {
    return false
  }
}
