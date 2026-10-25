export function fmtDate(s: string | undefined): string {
  if (!s) return '—'
  return s.slice(0, 10)
}

export function fmtNum(n: number | undefined, decimals = 2): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function fmtPct(n: number | null | undefined): string {
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

/** 统一展示到秒的北京时间，末尾带「北京」；非法/空值兜底，不跟浏览器时区走 */
export function fmtBeijing(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const d = new Date(String(value))
  if (Number.isNaN(d.getTime())) return String(value)
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(d)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')} 北京`
}

const WEEKDAY_NAMES = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

function weekdayLabel(iso: number): string {
  return WEEKDAY_NAMES[iso] ?? String(iso)
}

function parseDays(part: string): number[] {
  const bits = part.split('-').map(Number)
  const a = bits[0]
  const b = bits.length > 1 ? bits[1] : a
  return Array.from({ length: b - a + 1 }, (_, i) => a + i)
}

/** 调度 weekday_mask 的中文说明：1-7 → 每天，单个区间 → 周X至周Y，其余逐个列出 */
export function weekdayText(mask: string): string {
  const parts = String(mask).split(',').map((s) => s.trim()).filter(Boolean)
  if (parts.length === 1 && parts[0].includes('-')) {
    const [a, b] = parts[0].split('-').map(Number)
    if (a === 1 && b === 7) return '每天'
    return `${weekdayLabel(a)}至${weekdayLabel(b)}`
  }
  return parts.flatMap((p) => parseDays(p).map(weekdayLabel)).join('、')
}
