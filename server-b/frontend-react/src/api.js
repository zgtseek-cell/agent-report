/**
 * API 基址：与页面同源、同协议，避免 HTTPS 页面请求 HTTP 导致 Mixed Content 被拦截。
 * 使用相对路径 /api/... 时浏览器会自动用当前页的 origin，此处显式同源便于排查。
 */
export function getApiBase() {
  if (typeof window === 'undefined') return ''
  return window.location.origin
}

export function apiUrl(path) {
  const base = getApiBase()
  const p = path.startsWith('/') ? path : `/${path}`
  return `${base}${p}`
}
