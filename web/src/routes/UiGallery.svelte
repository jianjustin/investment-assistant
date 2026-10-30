<script lang="ts">
  import InfoIcon from '@lucide/svelte/icons/info'
  import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert'
  import OctagonXIcon from '@lucide/svelte/icons/octagon-x'
  import XIcon from '@lucide/svelte/icons/x'
  import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down'
  import { Button } from '$lib/ui/button/index'
  import { Badge } from '$lib/ui/badge/index'
  import { DataTable } from '$lib/ui/data-table/index'
  import type { Column, RowGroup } from '$lib/ui/data-table/index'
  import ConfirmDialog from '$lib/ui/confirm-dialog/ConfirmDialog.svelte'
  import * as Sheet from '$lib/ui/sheet/index'
  import * as Tabs from '$lib/ui/tabs/index'
  import TabNav from '$lib/ui/tab-nav/TabNav.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'
  import { Textarea } from '$lib/ui/textarea/index'
  import * as Select from '$lib/ui/select/index'
  import * as Tooltip from '$lib/ui/tooltip/index'
  import * as Popover from '$lib/ui/popover/index'
  import * as Collapsible from '$lib/ui/collapsible/index'
  import * as Alert from '$lib/ui/alert/index'
  import { Skeleton } from '$lib/ui/skeleton/index'
  import { Separator } from '$lib/ui/separator/index'
  import * as Card from '$lib/ui/card/index'
  import { notify } from '$lib/ui/toast'
  import { getTheme, toggleTheme } from '$lib/theme'

  // ---- tokens ----
  const surfaces = [
    { name: 'background', cls: 'bg-background' }, { name: 'card', cls: 'bg-card' }, { name: 'popover', cls: 'bg-popover' },
    { name: 'muted', cls: 'bg-muted' }, { name: 'border', cls: 'bg-border' }, { name: 'input', cls: 'bg-input' },
    { name: 'ring', cls: 'bg-ring' }, { name: 'foreground', cls: 'bg-foreground' }, { name: 'muted-foreground', cls: 'bg-muted-foreground' },
  ]
  const tones = [
    { name: 'primary', cls: 'bg-primary text-primary-foreground' }, { name: 'success', cls: 'bg-success text-success-foreground' },
    { name: 'warn', cls: 'bg-warn text-warn-foreground' }, { name: 'destructive', cls: 'bg-destructive text-destructive-foreground' },
    { name: 'info', cls: 'bg-info text-info-foreground' }, { name: 'running', cls: 'bg-running text-running-foreground' },
    { name: 'neutral', cls: 'bg-neutral text-neutral-foreground' },
  ]
  const textTones = [
    { name: 'primary', cls: 'text-primary' }, { name: 'success', cls: 'text-success' }, { name: 'warn', cls: 'text-warn' },
    { name: 'destructive', cls: 'text-destructive' }, { name: 'info', cls: 'text-info' }, { name: 'running', cls: 'text-running' },
    { name: 'neutral', cls: 'text-neutral' }, { name: 'up', cls: 'text-up' }, { name: 'down', cls: 'text-down' },
  ]
  const chartColors = [
    { name: 'chart-rule', cls: 'bg-chart-rule' }, { name: 'chart-own', cls: 'bg-chart-own' }, { name: 'chart-agent', cls: 'bg-chart-agent' },
    { name: 'chart-fill', cls: 'bg-chart-fill' }, { name: 'chart-grid', cls: 'bg-chart-grid' },
    { name: 'chart-1', cls: 'bg-chart-1' }, { name: 'chart-2', cls: 'bg-chart-2' }, { name: 'chart-3', cls: 'bg-chart-3' },
    { name: 'chart-4', cls: 'bg-chart-4' }, { name: 'chart-5', cls: 'bg-chart-5' },
  ]
  let theme = $state(getTheme())
  function flipTheme() {
    toggleTheme()
    theme = getTheme()
  }

  // ---- tables ----
  type Plan = { id: number; ticker: string; entry: number; stop: number; shares: number; status: string }
  const plans: Plan[] = [
    { id: 1, ticker: 'AAPL', entry: 187.25, stop: 181.4, shares: 40, status: '入场期' },
    { id: 2, ticker: 'MSFT', entry: 412.8, stop: 401.15, shares: 18, status: '持仓中' },
    { id: 3, ticker: 'NVDA', entry: 128.5, stop: 121.9, shares: 55, status: '入场期' },
  ]
  const ended: Plan[] = [
    { id: 4, ticker: 'AMD', entry: 141.2, stop: 135.0, shares: 30, status: '已结束' },
    { id: 5, ticker: 'META', entry: 498.1, stop: 480.0, shares: 12, status: '作废' },
  ]
  const many: Plan[] = Array.from({ length: 64 }, (_, i) => ({
    id: 100 + i, ticker: `T${String(i + 1).padStart(3, '0')}`, entry: 20 + i, stop: 18 + i, shares: 10 + i, status: '入场期',
  }))
  const columns: Column<Plan>[] = [
    { key: 'ticker', header: '标的' },
    { key: 'entry', header: '入场价', align: 'num', title: '计划入场价' },
    { key: 'stop', header: '止损', align: 'num', value: (r) => r.stop.toFixed(2) },
    { key: 'shares', header: '股数', align: 'num', cardLabel: '建议股数' },
    { key: 'status', header: '状态', align: 'center', hideInCards: false },
  ]
  const groups: RowGroup<Plan>[] = [
    { key: 'live', label: '进行中', rows: plans },
    { key: 'ended', label: '已结束', rows: ended, muted: true, collapsible: true, open: false },
  ]
  let expanded = $state(new Set<string | number>([2]))
  const rowKey = (r: Plan) => r.id

  // ---- dialogs ----
  let confirmOpen = $state(false)
  let destructiveOpen = $state(false)
  let confirmBusy = $state(false)
  function confirmSoon(close: () => void) {
    confirmBusy = true
    setTimeout(() => {
      confirmBusy = false
      close()
      notify.success('已确认')
    }, 800)
  }

  // ---- tabs, form ----
  let tabValue = $state('one')
  let nameValue = $state('')
  let selectValue = $state('rule')
  const selectItems = [
    { value: 'rule', label: '规则基线' },
    { value: 'own', label: '自定计划' },
    { value: 'agent', label: 'Agent 计划' },
  ]
  const selectedLabel = $derived(selectItems.find((i) => i.value === selectValue)?.label ?? '请选择')
  let collapsibleOpen = $state(false)
</script>

<div class="grid gap-8 pb-16">
  <header class="grid gap-1">
    <h1 class="text-xl font-medium">组件画廊</h1>
    <p class="text-sm text-muted-foreground">开发模式组件画廊（不进生产包）</p>
    <div class="pt-1">
      <Button size="sm" onclick={flipTheme}>切换主题（当前 {theme === 'dark' ? '深色' : '浅色'}）</Button>
    </div>
  </header>

  <section class="grid gap-3" aria-labelledby="g-tokens">
    <h2 id="g-tokens" class="text-lg font-medium">令牌</h2>
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {#each surfaces as s (s.name)}
        <div class="grid gap-1 text-xs"><div class={`h-8 rounded-md border border-border ${s.cls}`}></div>{s.name}</div>
      {/each}
    </div>
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {#each tones as s (s.name)}
        <div class={`flex h-8 items-center justify-center rounded-md text-xs ${s.cls}`}>{s.name}</div>
      {/each}
    </div>
    <div class="flex flex-wrap gap-x-4 gap-y-1 rounded-md border border-border bg-card p-3 text-sm">
      {#each textTones as s (s.name)}<span class={s.cls}>{s.name}</span>{/each}
    </div>
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {#each chartColors as s (s.name)}
        <div class="grid gap-1 text-xs"><div class={`h-6 rounded-md border border-border ${s.cls}`}></div>{s.name}</div>
      {/each}
    </div>
    <div class="flex flex-wrap items-baseline gap-4 text-muted-foreground">
      <span class="text-xs">text-xs 12</span><span class="text-sm">text-sm 13</span><span class="text-base">text-base 14</span>
      <span class="text-lg">text-lg 16</span><span class="text-xl">text-xl 20</span>
      <span class="shadow-1 rounded-md bg-card px-2 py-1 text-xs">shadow-1</span>
      <span class="shadow-2 rounded-md bg-card px-2 py-1 text-xs">shadow-2</span>
      <span class="rounded-md border border-running px-2 py-1 text-xs animate-running">animate-running</span>
    </div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-button">
    <h2 id="g-button" class="text-lg font-medium">按钮</h2>
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="primary">primary</Button>
      <Button variant="outline">outline</Button>
      <Button variant="ghost">ghost</Button>
      <Button variant="link">link</Button>
      <Button variant="destructive">destructive</Button>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="primary" size="sm">primary sm</Button>
      <Button variant="outline" size="sm">outline sm</Button>
      <Button variant="primary" size="md">primary md</Button>
      <Button variant="outline" size="md">outline md</Button>
      <Button variant="outline" size="icon" aria-label="关闭"><XIcon /></Button>
      <Button variant="ghost" size="icon" aria-label="更多"><ChevronsUpDownIcon /></Button>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="primary" busy busyText="提交中…">primary busy</Button>
      <Button variant="outline" busy>outline busy</Button>
      <Button variant="destructive" busy busyText="作废中…">destructive busy</Button>
      <Button variant="primary" disabled>primary disabled</Button>
      <Button variant="outline" disabled>outline disabled</Button>
      <Button variant="link" disabled>link disabled</Button>
      <Button variant="link" href="#_ui">link href</Button>
      <Button variant="outline" href="#_ui">outline href</Button>
    </div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-badge">
    <h2 id="g-badge" class="text-lg font-medium">徽标</h2>
    <p class="text-sm text-muted-foreground">Badge 只有中性底；语气由领域层的 StatusPill 通过类名给出。</p>
    <div class="flex flex-wrap items-center gap-2">
      <Badge>中性</Badge>
      <Badge class="bg-success/15 text-success">success</Badge>
      <Badge class="bg-warn/15 text-warn">warn</Badge>
      <Badge class="bg-destructive/15 text-destructive">danger</Badge>
      <Badge class="bg-info/15 text-info">info</Badge>
      <Badge class="bg-running/15 text-running animate-running border-running">running</Badge>
      <Badge class="bg-neutral/15 text-neutral">neutral</Badge>
    </div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-table">
    <h2 id="g-table" class="text-lg font-medium">表格</h2>
    <p class="text-sm text-muted-foreground">窗口窄于 768px 时，下面设了 cards 的表变成卡片，字段名在左。</p>
    <h3 class="text-sm font-medium">数字列、表头分组、置灰行</h3>
    <DataTable
      {columns}
      rows={plans}
      {rowKey}
      caption="计划（头部分组、数字列右对齐）"
      headerGroups={[{ label: '标的', span: 1 }, { label: '价位', span: 2 }, { label: '仓位与状态', span: 2 }]}
      muted={(r) => r.status === '已结束'}
      cards="narrow"
    />
    <h3 class="text-sm font-medium">分组（已结束组可折叠、置灰）与行展开</h3>
    <DataTable {columns} {groups} {rowKey} bind:expanded cards="narrow">
      {#snippet expandable(row)}
        <p class="text-sm">展开内容：{row.ticker} 的推理视图占位。</p>
      {/snippet}
    </DataTable>
    <h3 class="text-sm font-medium">超过 50 行显示「显示更多」</h3>
    <DataTable {columns} rows={many} {rowKey} sticky={false} />
  </section>

  <section class="grid gap-3" aria-labelledby="g-confirm">
    <h2 id="g-confirm" class="text-lg font-medium">确认对话框</h2>
    <div class="flex flex-wrap gap-2">
      <Button variant="primary" onclick={() => (confirmOpen = true)}>打开确认框</Button>
      <Button variant="outline" onclick={() => (destructiveOpen = true)}>打开危险确认框</Button>
    </div>
    <ConfirmDialog
      bind:open={confirmOpen}
      title="从此节点继续？"
      consequence="将重新运行该节点及之后的全部节点。"
      actionLabel="从此节点继续"
      busy={confirmBusy}
      onConfirm={() => confirmSoon(() => (confirmOpen = false))}
    />
    <ConfirmDialog
      bind:open={destructiveOpen}
      title="作废这笔成交？"
      consequence="作废后不再计入复盘统计，且不能恢复。"
      actionLabel="确认作废"
      destructive
      busy={confirmBusy}
      onConfirm={() => confirmSoon(() => (destructiveOpen = false))}
    />
  </section>

  <section class="grid gap-3" aria-labelledby="g-sheet">
    <h2 id="g-sheet" class="text-lg font-medium">抽屉</h2>
    <div class="flex flex-wrap gap-2">
      <Sheet.Root>
        <Sheet.Trigger>
          {#snippet child({ props })}<Button {...props}>打开抽屉（sm 24rem）</Button>{/snippet}
        </Sheet.Trigger>
        <Sheet.Content width="sm">
          <Sheet.Header>
            <Sheet.Title>计划详情</Sheet.Title>
            <Sheet.Description>右侧抽屉，窄屏全宽。</Sheet.Description>
          </Sheet.Header>
          <div class="px-4 text-sm">内容区。</div>
          <Sheet.Footer><Sheet.Close>{#snippet child({ props })}<Button {...props}>关闭</Button>{/snippet}</Sheet.Close></Sheet.Footer>
        </Sheet.Content>
      </Sheet.Root>
      <Sheet.Root>
        <Sheet.Trigger>
          {#snippet child({ props })}<Button {...props}>打开抽屉（lg 40rem）</Button>{/snippet}
        </Sheet.Trigger>
        <Sheet.Content width="lg">
          <Sheet.Header>
            <Sheet.Title>推理过程</Sheet.Title>
            <Sheet.Description>宽抽屉。</Sheet.Description>
          </Sheet.Header>
          <div class="px-4 text-sm">内容区。</div>
        </Sheet.Content>
      </Sheet.Root>
    </div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-tabs">
    <h2 id="g-tabs" class="text-lg font-medium">页内页签</h2>
    <Tabs.Root bind:value={tabValue}>
      <Tabs.List aria-label="页内页签示例">
        <Tabs.Trigger value="one">概览</Tabs.Trigger>
        <Tabs.Trigger value="two">明细</Tabs.Trigger>
        <Tabs.Trigger value="three" disabled>停用</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="one">概览内容</Tabs.Content>
      <Tabs.Content value="two">明细内容</Tabs.Content>
    </Tabs.Root>
    <Tabs.Root value="a">
      <Tabs.List variant="line" aria-label="线形页签示例">
        <Tabs.Trigger value="a">线形一</Tabs.Trigger>
        <Tabs.Trigger value="b">线形二</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="a">线形内容一</Tabs.Content>
      <Tabs.Content value="b">线形内容二</Tabs.Content>
    </Tabs.Root>
  </section>

  <section class="grid gap-3" aria-labelledby="g-tabnav">
    <h2 id="g-tabnav" class="text-lg font-medium">路由页签</h2>
    <TabNav
      label="路由页签示例"
      items={[
        { href: '#_ui', label: '复盘卡', current: true, badge: 3 },
        { href: '#_ui', label: '成交', current: false },
        { href: '#_ui', label: '统计', current: false, badge: '新' },
      ]}
    />
  </section>

  <section class="grid gap-3" aria-labelledby="g-form">
    <h2 id="g-form" class="text-lg font-medium">表单</h2>
    <div class="grid max-w-md gap-4">
      <Field label="名称" id="g-name" hint="最多 20 个字" required>
        {#snippet children({ id, describedby, invalid })}
          <Input {id} bind:value={nameValue} aria-describedby={describedby} aria-invalid={invalid} placeholder="例如：回撤买入" />
        {/snippet}
      </Field>
      <Field label="成交价" id="g-price" error="必须大于 0">
        {#snippet children({ id, describedby, invalid })}
          <Input {id} inputmode="decimal" class="text-right tabular-nums" value="-1" aria-describedby={describedby} aria-invalid={invalid} />
        {/snippet}
      </Field>
      <Field label="停用字段" id="g-disabled">
        {#snippet children({ id })}<Input {id} disabled value="不可编辑" />{/snippet}
      </Field>
      <Field label="备注" id="g-note">
        {#snippet children({ id, describedby })}<Textarea {id} aria-describedby={describedby} placeholder="可选" />{/snippet}
      </Field>
      <Field label="计划来源" id="g-source">
        {#snippet children({ id })}
          <Select.Root type="single" bind:value={selectValue}>
            <Select.Trigger {id} class="w-48">{selectedLabel}</Select.Trigger>
            <Select.Content>
              {#each selectItems as item (item.value)}
                <Select.Item value={item.value} label={item.label} />
              {/each}
            </Select.Content>
          </Select.Root>
        {/snippet}
      </Field>
    </div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-overlay">
    <h2 id="g-overlay" class="text-lg font-medium">提示与浮层</h2>
    <div class="flex flex-wrap items-center gap-2">
      <Tooltip.Provider>
        <Tooltip.Root>
          <Tooltip.Trigger>
            {#snippet child({ props })}<Button {...props}>悬停看提示</Button>{/snippet}
          </Tooltip.Trigger>
          <Tooltip.Content>表头缩写说明</Tooltip.Content>
        </Tooltip.Root>
      </Tooltip.Provider>
      <Popover.Root>
        <Popover.Trigger>
          {#snippet child({ props })}<Button variant="link" {...props}>点开概念卡</Button>{/snippet}
        </Popover.Trigger>
        <Popover.Content>
          <Popover.Header>
            <Popover.Title>ATR</Popover.Title>
            <Popover.Description>平均真实波幅，用于设定止损距离。</Popover.Description>
          </Popover.Header>
        </Popover.Content>
      </Popover.Root>
    </div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-collapsible">
    <h2 id="g-collapsible" class="text-lg font-medium">折叠</h2>
    <Collapsible.Root bind:open={collapsibleOpen} class="grid justify-items-start gap-2">
      <Collapsible.Trigger>
        {#snippet child({ props })}
          <Button variant="link" {...props} aria-expanded={collapsibleOpen}>{collapsibleOpen ? '收起规则基线' : '展开规则基线'}</Button>
        {/snippet}
      </Collapsible.Trigger>
      <Collapsible.Content class="rounded-md border border-border bg-card p-3 text-sm">规则基线的内容。</Collapsible.Content>
    </Collapsible.Root>
  </section>

  <section class="grid gap-3" aria-labelledby="g-alert">
    <h2 id="g-alert" class="text-lg font-medium">提示条</h2>
    <Alert.Root variant="info">
      <InfoIcon />
      <Alert.Title>提示</Alert.Title>
      <Alert.Description>入场期计划按规则基线重新计算。</Alert.Description>
    </Alert.Root>
    <Alert.Root variant="warn">
      <TriangleAlertIcon />
      <Alert.Title>降级</Alert.Title>
      <Alert.Description>Yahoo 空结果，日线用上一交易日。</Alert.Description>
    </Alert.Root>
    <Alert.Root variant="danger">
      <OctagonXIcon />
      <Alert.Title>失败</Alert.Title>
      <Alert.Description>Agent 连接需要重新登录。</Alert.Description>
      <Alert.Action><Button size="sm">重试</Button></Alert.Action>
    </Alert.Root>
  </section>

  <section class="grid gap-3" aria-labelledby="g-skeleton">
    <h2 id="g-skeleton" class="text-lg font-medium">骨架</h2>
    <div class="grid max-w-md gap-2" aria-busy="true">
      <Skeleton class="h-4 w-1/3" />
      <Skeleton class="h-4 w-full" />
      <Skeleton class="h-24 w-full" />
    </div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-card">
    <h2 id="g-card" class="text-lg font-medium">分隔与卡片</h2>
    <Card.Root class="max-w-md">
      <Card.Header>
        <Card.Title>AAPL</Card.Title>
        <Card.Description>入场期 · 第 2 版</Card.Description>
        <Card.Action><Button size="sm">查看</Button></Card.Action>
      </Card.Header>
      <Separator />
      <Card.Content class="text-sm">卡片只给一个对象。</Card.Content>
      <Card.Footer class="text-xs text-muted-foreground">截止 2026-10-29 16:00 北京</Card.Footer>
    </Card.Root>
    <div class="flex h-6 items-center gap-3 text-sm">左<Separator orientation="vertical" />中<Separator orientation="vertical" />右</div>
  </section>

  <section class="grid gap-3" aria-labelledby="g-toast">
    <h2 id="g-toast" class="text-lg font-medium">轻提示</h2>
    <div class="flex flex-wrap gap-2">
      <Button onclick={() => notify.success('已保存')}>成功（3 秒）</Button>
      <Button onclick={() => notify.info('已提交批处理')}>信息（3 秒）</Button>
      <Button variant="destructive" onclick={() => notify.error('保存失败：网络中断')}>失败（不自动消失）</Button>
    </div>
  </section>
</div>
