export function retryAfterDelayMs(headers) {
  const value = headers?.get?.('retry-after') ?? headers?.['retry-after'] ?? headers?.['Retry-After']
  if (typeof value !== 'string' || !value.trim()) return null
  const delay = /^\d+$/.test(value.trim()) ? Number(value) * 1000 : Date.parse(value) - Date.now()
  return Number.isFinite(delay) ? Math.max(0, delay) : null
}
