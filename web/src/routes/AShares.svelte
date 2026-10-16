<script lang="ts">
  import { onMount } from 'svelte'
  import type { EChartsOption } from 'echarts'
  import * as api from '../lib/api'
  import EChart from '../lib/charts/EChart.svelte'
  import ResearchCard from '../lib/components/ResearchCard.svelte'
  import SecurityPicker from '../lib/components/SecurityPicker.svelte'
  import { confirmResearchNavigation, guardHashNavigation } from '../lib/navigation-guard'
  import { researchHash, readResearchSelection } from '../lib/research-navigation'
  let { mode = 'data', beforeChange }: { mode?: 'data' | 'card'; beforeChange?: () => boolean } = $props()
  let symbol = $state('')
  let loadedSymbol = $state('')
  let view = $state<any>(null)
  let loading = $state(false)
  let busy = $state(false)
  let error = $state('')
  let info = $state('')
  let start = $state('')
  let end = $state('')
  let basis = $state('qfq')
  let periodMode = $state<'ytd' | 'quarter' | 'ttm'>('ytd')
  let benchmark = $state('CN:index:000300.SH')
  let shown = $state(20)
  let asOf = $state('')
  let loadRequest = 0
  let updateRequest = 0
  let watchRequest = 0
  let initialized = $state(false)
  let empty = $state(false)
  function canChange() { return beforeChange?.() !== false && confirmResearchNavigation() }
  function refresh() { if (canChange()) load() }
  function selectedHash(selected: string) {
    return researchHash(mode === 'data' ? 'data' : 'strategy', mode === 'data' ? 'ashares' : 'observation', 'CN', selected)
  }
  function selectSymbol(next: string, updateHash = true) {
    if (!next || next === symbol) return
    loadRequest++; updateRequest++; watchRequest++; busy = false
    symbol = next; view = null; loadedSymbol = ''; info = ''
    if (updateHash) history.replaceState(null, '', selectedHash(next))
    load()
  }
  function initialSelection(rows: any[]) {
    if (initialized) return
    initialized = true
    const selection = readResearchSelection(location.hash)
    const next = selection?.market === 'CN' ? selection.symbol : rows[0]?.ticker
    empty = !next
    if (next) selectSymbol(next)
  }
  let displayedBasis = $derived(view?.adjustment?.basis ?? basis)
  const statusName: Record<string, string> = { ready:'已更新', failed:'来源失败', partial:'覆盖不全', empty:'本次窗口无记录', stale:'已过期', never_collected:'尚未采集', unavailable_at_cutoff:'截止时尚不可用' }
  const dataName: Record<string, string> = { profile:'证券资料',bars:'日线',factors:'复权因子',financials:'财务',valuation:'估值',announcements:'公告索引',disclosure:'财报预约',unlocks:'解禁' }
  const num = (n: any, digits = 2) => n == null ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: digits })
  const money = (n: any) => n == null ? '—' : num(n / 1e8, 4)
  const time = (t: any) => t ? new Date(t).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '—'
  async function load() {
    if (!symbol) return
    const request = ++loadRequest
    const requestedSymbol = symbol.trim().toUpperCase()
    loading = true; error = ''
    try {
      const q = new URLSearchParams({ basis })
      if (start) q.set('start', start)
      if (end) q.set('end', end)
      if (asOf) q.set('as_of', new Date(asOf).toISOString())
      const next = await api.get<any>(`/api/ashares/${encodeURIComponent(requestedSymbol)}/research?${q}`)
      if (request !== loadRequest) return
      view = next
      loadedSymbol = requestedSymbol
      start = view.window.start; end = view.window.end
    } catch (e) { if (request === loadRequest) error = `读取失败：${String(e)}。旧页面数据不可视为已更新。` }
    finally { if (request === loadRequest) loading = false }
  }
  async function update(retry = false) {
    if (!symbol || !canChange()) return
    const requestedSymbol = symbol
    const request = ++updateRequest
    busy = true; info = ''; error = ''
    try {
      const result = await api.post<{ run_id: string }>('/api/ashares/sync', {
        symbols: [requestedSymbol], start: start || undefined, end: end || undefined, retry_failed: retry,
      })
      const run = await api.pollRun(result.run_id, { timeoutMs: 600_000 })
      if (run.status === 'error') throw new Error(run.error)
      if (request !== updateRequest || symbol !== requestedSymbol) return
      const outcome = run.result as any
      info = outcome?.status === 'error' ? '更新有缺失或失败；已保存成功部分，可续跑失败项。' : '手动更新完成。'
      await load()
    } catch (e) { if (request === updateRequest) error = `更新未完成：${String(e)}。请查看运行记录，不代表没有公告或风险。` }
    finally { if (request === updateRequest) busy = false }
  }
  async function watch() {
    if (!symbol) return
    const request = ++watchRequest
    const requestedSymbol = symbol
    try {
      const current = await api.getWatchlist('CN') as any
      if (request !== watchRequest) return
      if (current.rows.some((r: any) => r.ticker === requestedSymbol)) { info = '已在关注列表中，可在设置中编辑现有记录。'; return }
      await api.addWatchlistItem({ ticker: requestedSymbol, status: 'active' })
      const saved = await api.getWatchlist('CN') as any
      if (request === watchRequest && saved.rows.some((r: any) => r.ticker === requestedSymbol)) info = '已加入现有关注列表。'
    } catch (e) { if (request === watchRequest) error = String(e) }
  }
  onMount(() => {
    const explicit = readResearchSelection(location.hash)
    if (explicit?.market === 'CN') { initialized = true; selectSymbol(explicit.symbol) }
    function changedHash(event: HashChangeEvent) {
      if (!initialized) return
      const next = readResearchSelection(location.hash)
      if (next?.market !== 'CN' || next.symbol === symbol) return
      if (!guardHashNavigation(event, selectedHash(symbol))) return
      if (beforeChange?.() === false) { history.replaceState(null, '', selectedHash(symbol)); return }
      selectSymbol(next.symbol, false)
    }
    window.addEventListener('hashchange', changedHash)
    return () => { loadRequest++; updateRequest++; watchRequest++; window.removeEventListener('hashchange', changedHash) }
  })
  let priceOption = $derived<EChartsOption>({ tooltip: { trigger: 'axis' }, grid: { left: 55, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: (view?.bars ?? []).map((r: any) => r.date) }, yAxis: { type: 'value', scale: true },
    series: [{ type: 'line', showSymbol: false, connectNulls: false, data: (view?.bars ?? []).map((r: any) => r.close), name: displayedBasis + '收盘价' }] })
  let comp = $derived(view?.comparisons?.find((c: any) => c.security_id === benchmark))
  let compareOption = $derived<EChartsOption>({ tooltip: { trigger: 'axis' }, legend: { data: ['个股', '指数'] },
    grid: { left: 55, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: (comp?.series ?? []).map((r: any) => r.date) }, yAxis: { type: 'value', scale: true },
    series: ['stock', 'benchmark'].map((key, i) => ({ type: 'line', name: i ? '指数' : '个股', showSymbol: false,
      data: (comp?.series ?? []).map((r: any) => r[key]) })) })
  let latest = $derived(view?.raw_bars?.at(-1))
  let observations = $derived([...(view?.financials ?? []), ...(view?.announcements ?? [])])
</script>

<div class="ashare">
  <header><div><div class="eyebrow">A 股 · 中期改善研究</div><h1>{view?.profile?.name ?? (symbol || 'A股研究')}<span>{loadedSymbol}</span></h1>
    <p>{view?.profile?.board ?? '板块待确认'} · Asia/Shanghai · CNY · 股票与指数分开标识</p></div>
    <a href={symbol ? researchHash(mode === 'data' ? 'strategy' : 'data', mode === 'data' ? 'observation' : 'ashares', 'CN', symbol) : '#settings/watchlist'}>{mode === 'data' ? '打开研究观察卡 →' : '查看数据与来源 →'}</a></header>
  <section class="controls">
    <SecurityPicker market="CN" value={symbol} onchange={selectSymbol} beforeChange={canChange} onloaded={initialSelection} />
    <label>窗口开始<input type="date" bind:value={start} /></label><label>窗口结束<input type="date" bind:value={end} /></label>
    <button onclick={refresh} disabled={loading || !symbol}>读取数据</button><button onclick={watch} disabled={!symbol}>加入关注</button>
    <button class="primary" onclick={() => update(false)} disabled={busy || !!asOf || !symbol}>{busy ? '采集中…' : '手动更新'}</button>
    <button onclick={() => update(true)} disabled={busy || !!asOf || !symbol}>续跑失败项</button>
  </section>
  {#if empty}<p>暂无A股关注证券，请先在关注列表添加。</p><a href="#settings/watchlist">管理关注列表 →</a>{/if}
  {#if error}<div class="notice" role="alert">{error}</div>{/if}
  {#if info}<p role="status">{info}</p>{/if}
  {#if loading}<p>正在读取本地数据…</p>{/if}
  {#if view}
    <div class="metrics">
      <section><p>原始收盘价 · {latest?.date ?? '尚未采集'}</p><strong>¥ {num(latest?.close)}</strong><small>成交量 {num(latest?.volume,0)} 股 · 成交额 {money(latest?.amount)} 亿元</small></section>
      <section><p>区间收益 · {displayedBasis}</p><strong>{num(view.performance.return_pct)}%</strong><small>{view.performance.start ?? '—'} → {view.performance.end ?? '—'}</small></section>
      <section><p>最大回撤 · {displayedBasis}</p><strong>{num(view.performance.max_drawdown_pct)}%</strong><small>{view.performance.count ?? 0} 个有效交易日</small></section>
      <section><p>PE TTM · {view.valuation?.date ?? '尚未采集'}</p><strong>{num(view.valuation?.pe_ttm)} 倍</strong><small>PB MRQ {num(view.valuation?.pb_mrq)} · PS TTM {num(view.valuation?.ps_ttm)}</small></section>
    </div>
    <p>{view.valuation?.basis ?? '估值口径尚未取得'}{view.valuation?.pe_status !== 'available' ? ' · ' + (view.valuation?.pe_status ?? '无估值数据') : ''}</p>
    {#if mode === 'card'}
      <ResearchCard symbol={loadedSymbol} card={view.card} {observations} onSaved={load} />
    {:else}
      <section>
        <div class="section-heading"><h2>数据溯源与更新状态</h2><span>CNEquity {view.upstream.version} · {view.upstream.commit.slice(0,7)} 局部复用</span></div>
        <p>失败、过期、无记录、未采集分别显示；旧值保留日期。无记录仅指来源在本次窗口返回空，不代表没有风险。</p>
        <div class="table-scroll"><table><thead><tr><th>数据</th><th>状态</th><th>实际数据范围</th><th>首次采集</th><th>最近尝试</th><th>缺失 / 失败</th></tr></thead><tbody>
          {#each view.statuses as s}<tr><td>{dataName[s.dataset]}<small>{s.dataset === 'factors' ? '新浪财经' : '东方财富'}</small></td><td class:warn={s.status !== 'ready'}>{statusName[s.status]}{s.retained_old_values ? ' · 显示旧值' : ''}</td>
            <td>{s.coverage_start ?? '—'} → {s.coverage_end ?? '—'}<small>{s.stored_rows ?? 0} 条 · 请求 {s.requested_start ?? '—'}—{s.requested_end ?? '—'}{s.dataset === 'unlocks' ? '（另含未来180日）' : ''}</small></td><td>{time(s.first_collected_at)}</td><td>{time(s.attempted_at)}</td>
            <td>{s.error ?? s.details?.limitation ?? s.missing_reason ?? (s.details?.missing_sessions?.length ? `${s.details.missing_sessions.length}个交易日缺失` : '—')}</td></tr>{/each}
        </tbody></table></div>
        <details><summary>证券资料、日历与历史信息可用性</summary>
          <p>上市日期 {view.profile?.listing_date ?? '未知'} · 上市状态 {view.profile?.listing_status ?? '未知'}。{view.profile?.listing_status_note}</p>
          <p>日历：{view.calendar.coverage_start}—{view.calendar.coverage_end}。{view.calendar.next_year} · <a href={view.calendar.source_url} target="_blank" rel="noreferrer">交易所休市安排 ↗</a></p>
          <p>{view.pit.note} 严格 PIT：不支持。当前快照不能当作历史时点数据。</p>
          <div class="controls"><label>本机观察截止时间<input type="datetime-local" bind:value={asOf} /></label><button onclick={load}>按截止时间读取</button><button onclick={() => { asOf = ''; load() }}>回到当前数据</button></div>
        </details>
      </section>
      <section>
        <div class="section-heading"><h2>日线与复权</h2><select aria-label="价格口径" bind:value={basis} onchange={load}><option value="raw">原始价</option><option value="qfq">前复权</option><option value="hfq">后复权</option></select></div>
        <p>{view.adjustment.formula}</p><p>{view.adjustment.limit}</p>
        {#if view.bars.length}<EChart option={priceOption} />{:else}<div class="notice">当前条件下没有可展示的价格；请核对采集状态与历史截止时间。</div>{/if}
        <p>{view.performance.formula} · 窗口预期 {view.coverage.requested_sessions} 个交易日，缺失 {view.coverage.missing_sessions.length} 日，复权价格缺失 {view.adjustment.missing_sessions} 日。</p>
        <details><summary>每日价格、成交量、成交额及计算用因子</summary><p>{view.coverage.note}</p>
          <div class="table-scroll"><table><thead><tr><th>日期</th><th>原始收盘</th><th>{displayedBasis}收盘</th><th>成交量（股）</th><th>成交额（元）</th><th>后复权乘数</th><th>来源</th></tr></thead><tbody>
            {#each [...view.bars].reverse() as r}<tr><td>{r.date}</td><td>{num(view.raw_bars.find((x:any) => x.date===r.date)?.close)}</td><td>{num(r.close,4)}</td><td>{num(r.volume,0)}</td><td>{num(r.amount)}</td><td>{num(r.factor,8)}</td><td><a href={r.source_url} target="_blank" rel="noreferrer">数据 ↗</a></td></tr>{/each}
          </tbody></table></div>
        </details>
      </section>
      <section>
        <div class="section-heading"><h2>同行业与宽基比较</h2><select aria-label="比较基准" bind:value={benchmark}>{#each view.comparisons as c}<option value={c.security_id}>{c.name}</option>{/each}</select></div>
        <p>{comp?.methodology} <a href={comp?.source_url} target="_blank" rel="noreferrer">基准说明 ↗</a></p>
        <p>{comp?.basis} · 基准数据：{statusName[comp?.collection.status]} · {comp?.collection.coverage_start ?? '—'}—{comp?.collection.coverage_end ?? '—'}</p>
        {#if comp?.series?.length}<EChart option={compareOption} /><p>{comp.formula} · {comp.start}—{comp.end}，共同 {comp.common_sessions} 日，剔除个股 {comp.excluded_stock_sessions} 日 / 基准 {comp.excluded_benchmark_sessions} 日；相对收益 {num(comp.relative_return_pp)} 个百分点。</p>
        {:else}<p>共同日期不足，无法计算同期收益。</p>{/if}
      </section>
      <section>
        <div class="section-heading"><h2>财务期间与口径</h2><select aria-label="财务期间口径" bind:value={periodMode}><option value="ytd">年初累计</option><option value="quarter">单季度</option><option value="ttm">TTM</option></select></div>
        <p>金额：人民币亿元；应收、存货始终为期末余额。扣非利润不等于纯主营利润。累计数据差分缺前期不补零；TTM 必须四个连续季度。</p>
        <div class="table-scroll"><table><thead><tr><th>报告期末</th><th>收入</th><th>归母净利</th><th>扣非利润</th><th>毛利率</th><th>经营现金流</th><th>应收</th><th>存货</th></tr></thead><tbody>
          {#each view.financials as f}{@const values = periodMode === 'ytd' ? f : f[periodMode]}<tr><td>{f.period_end}<small>{periodMode === 'ytd' ? '年初至期末' : periodMode === 'quarter' ? '单季度差分' : '连续四季度'}</small></td>
            <td>{money(values?.revenue)}</td><td>{money(values?.parent_profit)}</td><td>{money(values?.deducted_profit)}</td>
            <td>{num(periodMode === 'ttm' ? (values?.revenue > 0 && values?.gross_profit != null ? values.gross_profit / values.revenue * 100 : null) : values?.gross_margin_pct)}%</td>
            <td>{money(values?.operating_cashflow)}</td><td>{money(f.receivables)}</td><td>{money(f.inventory)}</td></tr>{/each}
        </tbody></table></div>
        {#each view.financials as f}<details><summary>{f.period_end} · 计算、首次公告、修订及采集来源</summary>
          <p>{f.accounting_basis} · {f.unit} · EPS：{num(f.eps)}（{f.eps_basis}）</p><p>{f.shares_basis} · {num(f.shares,0)} 股</p>
          <p>{f.quarter_formula} · 输入记录 {f.quarter_inputs.join(', ')} · {f.quarter_missing_reason ?? '前期条件齐备'}。{f.ttm_formula}：{f.ttm_periods.join(' / ')}。</p>
          <p>首次公告日期（来源标注）：{f.first_disclosed_date ?? '未知'}；来源更新：{f.provider_updated_date ?? '未知'}；首次采集：{time(f.first_seen_at)}；保守可用时间：{time(f.available_after)}。</p>
          <p>后续重新披露日期：{Object.entries(f.provider_republished_dates ?? {}).map(([k,v]) => `${k}: ${v ?? '未知'}`).join('；')}</p>
          <p>{f.limitations.join('；')}</p>
          {#each Object.entries(f.origins ?? {}) as [name, origins]}<a href={(origins as any[])[0]?.source_url} target="_blank" rel="noreferrer">{name} ↗ </a>{/each}
        </details>{/each}
      </section>
      <section>
        <h2>公告与事件</h2><p>仅公告索引与原文入口；未做全文下载、业务分部提取或自动结构化解析。减持、监管标签来自标题匹配，不能作为全面风险结论。</p>
        <div class="table-scroll"><table><thead><tr><th>公告日期</th><th>标题 / 线索</th><th>来源展示时间</th><th>首次采集</th><th>原文</th></tr></thead><tbody>
          {#each view.announcements.slice(0,shown) as a}<tr><td>{a.notice_date}</td><td>{a.title}<small>{a.event_tags.join(' · ')}</small></td><td>{a.display_time ?? '未知'}</td><td>{time(a.first_seen_at)}</td><td><a href={a.original_url} target="_blank" rel="noreferrer">打开原文 ↗</a><small><a href={a.index_url} target="_blank" rel="noreferrer">公告索引</a></small></td></tr>
          {:else}<tr><td colspan="5">当前没有已展示记录，请先核对公告采集状态；不能据此判断没有公告或风险。</td></tr>{/each}
        </tbody></table></div>
        {#if shown < view.announcements.length}<button onclick={() => shown += 30}>继续显示（共 {view.announcements.length} 条）</button>{/if}
        <h3>财报预约 · 当前快照</h3><p>版本仅从启用后积累；预约可变更。</p>
        <div class="table-scroll"><table><thead><tr><th>报告期</th><th>首次预约</th><th>当前预约</th><th>实际披露</th><th>采集</th></tr></thead><tbody>{#each view.disclosure as d}<tr><td>{d.period_end}</td><td>{d.first_scheduled_date ?? '—'}</td><td>{d.scheduled_date ?? '—'}</td><td>{d.actual_date ?? '—'}</td><td>{time(d.first_seen_at)}</td></tr>{/each}</tbody></table></div>
        <h3>解禁日程 · 当前快照</h3><div class="table-scroll"><table><thead><tr><th>事件日期</th><th>股数</th><th>股份类型</th><th>来源</th></tr></thead><tbody>{#each view.unlocks as u}<tr><td>{u.event_date}</td><td>{num(u.shares,0)}<small>{u.unit}</small></td><td>{u.share_type}</td><td><a href={u.source_url} target="_blank" rel="noreferrer">数据 ↗</a></td></tr>{:else}<tr><td colspan="4">暂无已采集解禁记录，具体以来源状态和覆盖窗口为准。</td></tr>{/each}</tbody></table></div>
      </section>
    {/if}
  {/if}
</div>

<style>
  .ashare{display:grid;gap:1rem;max-width:1500px;margin:0 auto}header{display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}
  .eyebrow{font-size:.8rem;color:var(--accent);letter-spacing:.08em}h1{font-size:1.8rem;font-weight:650}h1 span{font-size:1rem;color:var(--text-muted);margin-left:1rem}h2{font-size:1.1rem;font-weight:650}h3{font-weight:600;margin-top:1.3rem}
  p{font-size:.82rem;color:var(--text-muted);line-height:1.65;margin:.4rem 0 .8rem}small{display:block;color:var(--text-muted);font-size:.72rem;margin-top:.3rem}
  section{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.1rem;min-width:0}
  .controls{display:flex;gap:.6rem;align-items:end;flex-wrap:wrap}.controls label{display:grid;gap:.25rem;font-size:.75rem;color:var(--text-muted)}
  input,select{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:.5rem;font-size:.85rem}
  button{padding:.5rem .75rem;border:1px solid var(--border);border-radius:5px;background:var(--surface-2);font-size:.85rem}button:disabled{opacity:.45}.primary{background:var(--accent);color:white}
  .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.8rem}.metrics strong{font-size:1.6rem;font-weight:600;font-variant-numeric:tabular-nums}
  .section-heading{display:flex;align-items:center;justify-content:space-between;gap:.8rem;flex-wrap:wrap}.section-heading span{font-size:.75rem;color:var(--text-muted)}
  .table-scroll{overflow:auto;max-height:500px}table{width:100%;border-collapse:collapse;font-size:.8rem;white-space:normal}th{text-align:left;color:var(--text-muted);font-weight:500;background:var(--surface-2);position:sticky;top:0}td,th{padding:.65rem;border-bottom:1px solid var(--border);min-width:90px}td{font-variant-numeric:tabular-nums}
  .warn{color:#c48218}.notice{border:1px solid #d99b27;padding:1rem;border-radius:8px;font-size:.9rem}a{color:var(--accent)}details{border-top:1px solid var(--border);padding:.7rem 0;font-size:.8rem}summary{cursor:pointer}
</style>
