import type { CommandStatus, Language, MarketSignal, Operation } from '../app/types'
import type { Translator } from '../i18n/messages'

export function formatBool(value: unknown, t: Translator): string {
  if (value === true) return t('yes')
  if (value === false) return t('no')
  return t('unknown')
}

export function formatNumber(value: unknown, digits = 0): string {
  const numberValue = typeof value === 'string' ? Number(value) : value
  return typeof numberValue === 'number' && Number.isFinite(numberValue) ? numberValue.toFixed(digits) : 'N/A'
}

export function formatBytes(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

export function formatTimestamp(value: unknown, language: Language): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A'
  return new Date(value * 1000).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US')
}

export function serviceLabel(service: CommandStatus | undefined, t: Translator): string {
  if (!service) return t('unknown')
  if (service.ok) return 'active'
  return service.output?.trim() || 'inactive'
}

export function serviceDot(service?: CommandStatus): string {
  if (!service) return 'bg-slate-300'
  return service.ok ? 'bg-emerald-500' : 'bg-rose-500'
}

export function marketDot(signal?: MarketSignal | null): string {
  const status = signal?.market_status?.toLowerCase()
  if (status === 'green') return 'bg-emerald-500'
  if (status === 'red') return 'bg-rose-500'
  if (status === 'yellow') return 'bg-amber-500'
  return 'bg-slate-300'
}

export function marketLabel(signal: MarketSignal | null | undefined, t: Translator): string {
  const status = signal?.market_status?.toLowerCase()
  if (status === 'green') return t('green')
  if (status === 'yellow') return t('yellow')
  if (status === 'red') return t('red')
  return signal?.market_status ?? 'N/A'
}

export function riskLabel(operation: Operation, t: Translator): string {
  if (operation.risk === 'low') return t('low')
  if (operation.risk === 'medium') return t('medium')
  if (operation.risk === 'high') return t('high')
  return operation.risk
}
