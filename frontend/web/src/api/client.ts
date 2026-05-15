const BASE = import.meta.env.VITE_API_BASE ?? ''

export function apiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  if (!BASE) return normalized
  return `${BASE.replace(/\/$/, '')}${normalized}`
}
