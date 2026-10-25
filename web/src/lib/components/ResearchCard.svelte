<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import * as api from '../api'
  import { registerNavigationGuard } from '../navigation-guard'
  let { symbol, card, observations = [], onSaved, onDirtyChange }: {
    symbol: string; card: any; observations?: any[]; onSaved?: () => Promise<void>; onDirtyChange?: (dirty: boolean) => void
  } = $props()
  const empty = () => ({
    improvement: { hypothesis: '', products: '', expected_window: '', next_event: '', next_event_date: null },
    evidence: [], scenarios: [], invalidations: [], links: [],
  })
  let body = $state<any>(empty())
  let version = $state(0)
  let saving = $state(false)
  let message = $state('')
  let refs = $state<any[]>([])
  let refError = $state('')
  let baseline = $state('')
  let loadedSymbol = ''
  let generation = 0
  let discardDraft: string | null = null
  let dirty = $derived(baseline !== '' && JSON.stringify(body) !== baseline)
  const defaultCurrency = 'USD'
  function normalized(input: any) {
    return structuredClone(input ?? empty())
  }
  function adopt(incoming: any) {
    discardDraft = null
    body = normalized($state.snapshot(incoming?.body ?? empty()))
    baseline = JSON.stringify(body)
    version = incoming?.version ?? 0
  }
  $effect(() => {
    const nextSymbol = symbol
    const incoming = card
    untrack(() => {
      if (loadedSymbol !== nextSymbol) {
        generation++; loadedSymbol = nextSymbol; saving = false; message = ''; adopt(incoming)
      } else if (!dirty || discardDraft === JSON.stringify(body)) adopt(incoming)
      else if ((incoming?.version ?? 0) !== version) message = '已有更新版本；当前未保存编辑已保留，请合并后再保存。'
    })
  })
  $effect(() => { onDirtyChange?.(dirty) })
  onMount(() => {
    const dispose = registerNavigationGuard({
      snapshot: () => JSON.stringify(body), dirty: () => dirty,
      discard: snapshot => { discardDraft = snapshot },
    })
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', beforeUnload)
    return () => { generation++; dispose(); window.removeEventListener('beforeunload', beforeUnload); onDirtyChange?.(false) }
  })
  onMount(async () => {
    try { refs = (await api.get<{ rows: any[] }>('/api/research/us-references')).rows }
    catch { refError = '既有SEC索引读取失败；请在数据 → 财报页核对' }
  })
  function addEvidence() {
    body.evidence = [...body.evidence, { claim: '', stance: 'pending', source_url: '', observation_id: null,
      occurred_at: null, disclosed_at: null, collected_at: null, method: 'disclosed', metric: null, value: null, unit: null, period: null, source_locator: null, basis: null }]
  }
  function chooseEvidence(e: any) {
    const obs = observations.find(o => o.id === Number(e.observation_id))
    if (!obs) { e.observation_id = null; return }
    e.observation_id = obs.id
    e.source_url = obs.original_url ?? obs.source_url
    e.occurred_at = obs.period_end ?? obs.event_date ?? null
    e.disclosed_at = obs.first_disclosed_date ?? obs.notice_date ?? null
    e.collected_at = obs.first_seen_at
  }
  async function save() {
    const request = generation
    const savedSymbol = symbol
    const submitted = JSON.stringify(body)
    saving = true; message = ''
    try {
      const data = structuredClone($state.snapshot(body))
      data.improvement.next_event_date ||= null
      for (const i of data.invalidations) { i.review_date ||= null; i.checked_at ||= null }
      for (const s of data.scenarios) {
        for (const key of ['profit', 'pe', 'shares']) if (s[key] === '' || s[key] === undefined) s[key] = null
      }
      const result = await api.put<any>(`/api/research/observation-cards/${encodeURIComponent(savedSymbol)}`, { body: data, expected_version: version })
      if (request !== generation || savedSymbol !== symbol) return
      if (!result?.card?.body || !Number.isInteger(result.card.version)) throw new Error('保存回读缺少观察卡；编辑已保留，请核对服务器版本')
      if (JSON.stringify(body) === submitted) adopt(result.card)
      else { version = result.card.version; baseline = JSON.stringify(normalized(result.card.body)) }
      // The PUT response is the authoritative readback. Optional parent refresh must not erase later edits.
      await onSaved?.()
      if (request !== generation || savedSymbol !== symbol) return
      message = dirty ? '观察卡已保存；保存期间的新编辑尚未保存。' : '观察卡已保存，证据变化已复核。'
    } catch (e) { if (request === generation && savedSymbol === symbol) message = String(e) }
    finally { if (request === generation && savedSymbol === symbol) saving = false }
  }
  function scenarioValue(s: any) {
    return s.profit > 0 && s.pe > 0 && s.shares > 0 ? (s.profit * s.pe / s.shares).toFixed(2) : '不适用/待补充'
  }
  function addLink() {
    body.links = [...body.links, { ticker: '', filing_id: null, products: '', transmission_condition: '',
      fiscal_period: '', currency: '', accounting_basis: '', status: 'pending' }]
  }

</script>

<div class="card-editor">
  <div class="heading"><div><h2>研究观察卡</h2><p>改善—证据—价格—失效条件 · {symbol} · 版本 {version} · {dirty ? '有未保存编辑' : '已读取'} · 判断由你复核</p></div>
    <button class="primary" onclick={save} disabled={saving}>{saving ? '保存中…' : '保存并复核证据'}</button></div>
  {#if message}<p role="status">{message}</p>{/if}
  {#if card?.new_evidence_count > 0}<div class="notice">有 {card.new_evidence_count} 条新增或修订数据，请核对证据与失效条件；系统没有改变投资判断。</div>{/if}
  <section>
    <h3>01 改善</h3>
    <label>投资假设<textarea rows="3" bind:value={body.improvement.hypothesis} placeholder="何种变化可能带来未来2–4季度的改善？"></textarea></label>
    <div class="fields"><label>作用产品<input bind:value={body.improvement.products} placeholder="明确产品与需求传导" /></label>
      <label>预期兑现窗口<input bind:value={body.improvement.expected_window} /></label>
      <label>下一次验证事件<input bind:value={body.improvement.next_event} /></label>
      <label>验证日期<input type="date" bind:value={body.improvement.next_event_date} /></label></div>
  </section>
  <section>
    <div class="heading"><h3>02 证据</h3><button onclick={addEvidence}>添加证据</button></div>
    <p>支持、反对和尚待验证分别记录。产品收入、订单和客户采用进度没有披露时保留空白。</p>
    {#each body.evidence as e, i}
      <div class="entry">
        <div class="fields"><label>证据方向<select bind:value={e.stance}><option value="supports">支持</option><option value="opposes">反对</option><option value="pending">尚待验证</option></select></label>
          <label>判断性质<select bind:value={e.method}><option value="disclosed">来源披露</option><option value="calculated">工作台计算</option><option value="analyst_assumption">分析假设</option></select></label>
          <label>关联已采集数据<select bind:value={e.observation_id} onchange={() => chooseEvidence(e)}><option value={null}>手动来源链接</option>
            {#each observations as o}<option value={o.id}>#{o.id} {o.title ?? o.period_end ?? o.data_date}</option>{/each}</select></label></div>
        <label>判断与依据<textarea rows="2" bind:value={e.claim}></textarea></label>
        <div class="fields"><label>指标<input bind:value={e.metric} /></label><label>数值 / 范围原文<input bind:value={e.value} /></label>
          <label>单位<input bind:value={e.unit} /></label><label>实际期间<input bind:value={e.period} /></label><label>会计口径<input bind:value={e.basis} /></label></div>
        <label>原文定位<input bind:value={e.source_locator} placeholder="页码、表格或原文段落" /></label>
        <label>原文或数据链接<input type="url" bind:value={e.source_url} /></label>
        <div class="fields"><label>发生时间 / 报告期<input bind:value={e.occurred_at} placeholder="未知可留空" /></label>
          <label>披露时间<input bind:value={e.disclosed_at} placeholder="日期不等于盘中可用时间" /></label>
          <label>首次采集<input readonly value={e.collected_at ?? '保存时记录'} /></label></div>
        <button onclick={() => body.evidence = body.evidence.filter((_: any, j: number) => j !== i)}>移除此条</button>
      </div>
    {:else}<p>尚未记录证据。</p>{/each}
  </section>
  <section>
    <div class="heading"><h3>03 价格情景</h3><button onclick={() => body.scenarios = [...body.scenarios, {
      label: '', method: 'analyst_assumption', profit: null, currency: defaultCurrency, pe: null, shares: null, period: '', share_basis: '', source_url: '', note: '',
    }]}>添加情景</button></div>
    <p>情景每股价值 = 同币种年度利润 × PE ÷ 股数。请明确归属与股本口径。亏损时不计算常规 PE。所有情景可调整，不构成目标价。</p>
    {#each body.scenarios as s, i}
      <div class="entry"><div class="fields"><label>情景名称<input bind:value={s.label} /></label>
        <label>计算性质<select bind:value={s.method}><option value="analyst_assumption">分析假设</option><option value="mechanical_annualization">机械年化</option><option value="company_guidance">公司指引（需原文）</option></select></label>
        <label>盈利期间<input bind:value={s.period} /></label>
        <label>年度利润<input type="number" bind:value={s.profit} /></label><label>币种<select bind:value={s.currency}><option>USD</option><option>EUR</option><option>HKD</option></select></label>
        <label>假设 PE<input type="number" min="0.01" step="0.1" bind:value={s.pe} /></label>
        <label>股数（股）<input type="number" min="1" bind:value={s.shares} /></label></div>
        <label>股本口径<input bind:value={s.share_basis} placeholder="期末/加权平均/A+H总股本；日期" /></label>
        <label>来源链接<input type="url" bind:value={s.source_url} /></label>
        <label>假设与限制<textarea rows="2" bind:value={s.note}></textarea></label>
        <div class="heading"><strong>情景值：{scenarioValue(s)} {s.currency ?? '币种待填'} / 股</strong><button onclick={() => body.scenarios = body.scenarios.filter((_: any, j: number) => j !== i)}>移除情景</button></div>
      </div>
    {:else}<p>尚未记录盈利/估值情景。</p>{/each}
  </section>
  <section>
    <div class="heading"><h3>04 失效条件</h3><button onclick={() => body.invalidations = [...body.invalidations, {
      condition: '', indicator: '', review_date: null, result: 'pending', checked_at: null, note: '',
    }]}>添加条件</button></div>
    {#each body.invalidations as item, i}
      <div class="entry"><label>触发条件<textarea rows="2" bind:value={item.condition}></textarea></label>
        <div class="fields"><label>观察指标<input bind:value={item.indicator} /></label><label>复核日期<input type="date" bind:value={item.review_date} /></label>
          <label>核对结果<select bind:value={item.result}><option value="pending">待复核</option><option value="triggered">已触发</option><option value="not_triggered">未触发</option><option value="unknown">数据不足</option></select></label>
          <label>核对日期<input type="date" bind:value={item.checked_at} /></label></div>
        <label>核对依据<textarea rows="2" bind:value={item.note}></textarea></label>
        <button onclick={() => body.invalidations = body.invalidations.filter((_: any, j: number) => j !== i)}>移除条件</button></div>
    {:else}<p>尚未记录失效条件。</p>{/each}
  </section>
  <section>
    <div class="heading"><h3>跨市场研究关联</h3><button onclick={addLink}>关联美股研究</button></div>
    <p>同属 AI 不意味着业绩同步。写明具体产品、客户采用和兑现条件，保留各自财年、币种及会计口径。</p>
    {#if refError}<div class="notice">{refError}</div>{/if}
    <datalist id="us-link-tickers">{#each [...new Set(refs.map(r => r.ticker))] as ticker}<option value={ticker}></option>{/each}</datalist>
    {#each body.links as link, i}
      <div class="entry"><div class="fields"><label>美股公司<input bind:value={link.ticker} oninput={() => link.filing_id = null} list="us-link-tickers" placeholder="输入有效美股Ticker" /></label>
        <label>既有 SEC 原文<select bind:value={link.filing_id}><option value={null}>尚待关联</option>{#each refs.filter(r => r.ticker === link.ticker.trim().toUpperCase()) as r}<option value={r.id}>{r.form} · {r.filing_date}</option>{/each}</select></label>
        <label>关联状态<select bind:value={link.status}><option value="pending">待验证</option><option value="supported">有支持证据</option><option value="opposed">有反对证据</option></select></label></div>
        <label>具体产品关系<input bind:value={link.products} /></label>
        <label>传导条件<textarea rows="2" bind:value={link.transmission_condition}></textarea></label>
        <div class="fields"><label>实际财年 / 报告期<input bind:value={link.fiscal_period} /></label><label>币种<input bind:value={link.currency} /></label><label>会计口径<input bind:value={link.accounting_basis} /></label></div>
        {#if link.filing_id}
          {@const ref = refs.find(r => r.id === Number(link.filing_id))}
          <a href={ref?.url} target="_blank" rel="noreferrer">打开既有 SEC 原文 ↗</a>
          <details><summary>既有解析器提取的期间与单位</summary>
            {#if ref?.limitation}<p>{ref.limitation}</p>{/if}
            {#each Object.entries(ref?.facts ?? {}) as [key, value]}
              <p>{key} · {(value as any).display ?? (value as any).value} · {(value as any).period} · {(value as any).unit} · {(value as any).basis}</p>
            {:else}<p>尚无已提取事实，请核对原文；不自动补全产品与客户数据。</p>{/each}
          </details>
        {/if}
        <button onclick={() => body.links = body.links.filter((_: any, j: number) => j !== i)}>移除关联</button>
      </div>
    {/each}
  </section>
  <button class="primary" onclick={save} disabled={saving}>{saving ? '保存中…' : '保存观察卡'}</button>
</div>

<style>
  .card-editor { display:grid; gap:1rem; min-width:0; overflow-wrap:anywhere } h2 {font-size:1.3rem;font-weight:650} h3{font-weight:650;margin-bottom:.6rem}
  section {min-width:0;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem}
  .heading{display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}
  p {color:var(--text-muted);font-size:.85rem;margin:.4rem 0 .8rem;line-height:1.6}
  label {display:flex;flex-direction:column;gap:.35rem;font-size:.8rem;color:var(--text-muted);margin-bottom:.7rem}
  input,select,textarea {width:100%;min-width:0;max-width:100%;padding:.6rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);color:var(--text);font-size:.9rem}
  .fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:.5rem 1rem}
  button {border:1px solid var(--border);border-radius:6px;padding:.5rem .85rem;font-size:.85rem;background:var(--surface-2)}
  .primary {background:var(--accent);color:white} button:disabled{opacity:.5} .entry{border-top:1px solid var(--border);padding:1rem 0}
  .notice {padding:.8rem;border:1px solid #d99b27;border-radius:8px;background:#d99b2710;font-size:.9rem}
  a{color:var(--accent)} details{font-size:.8rem;margin:.6rem 0}
</style>
