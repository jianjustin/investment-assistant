const zh: Record<string, string> = {
  dashboard: '总览',
  market: '市场',
  watchlist: '关注',
  strategy: '策略',
  hermes: 'Hermes',
  system: '系统',
  loading: '加载中…',
  error: '出错了',
}

export function t(key: string): string {
  return zh[key] ?? key
}
