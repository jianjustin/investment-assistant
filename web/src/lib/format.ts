export function fmtDate(s: string | undefined): string {
  if (!s) return '—'
  return s.slice(0, 10)
}

export function fmtNum(n: number | undefined, decimals = 2): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function fmtPct(n: number | undefined): string {
  if (n == null) return '—'
  return (n * 100).toFixed(1) + '%'
}

/** 时间戳统一展示到秒（本地时区），非法/空值兜底 */
export function fmtTime(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const d = new Date(String(value))
  if (Number.isNaN(d.getTime())) return String(value)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 本地时区的今天，YYYY-MM-DD（喂给 <input type="date">） */
export function todayLocalISO(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
