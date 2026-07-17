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
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`
}
