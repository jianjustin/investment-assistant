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
