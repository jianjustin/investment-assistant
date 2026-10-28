import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import KnowledgeForm from './KnowledgeForm.svelte'
import * as api from '../api'
import { resetConceptIndex } from '../knowledge'
import { version } from '../growth-fixtures'

const fill = async (label: string, value: string) =>
  fireEvent.input(screen.getByLabelText(label), { target: { value } })
const addConcept = async (id: string) => {
  await fill('概念', id)
  await fireEvent.click(screen.getByRole('button', { name: '添加概念' }))
}
const addTicker = async (t: string) => {
  await fill('标的', t)
  await fireEvent.click(screen.getByRole('button', { name: '添加标的' }))
}
const submit = () => screen.getByRole('button', { name: '提交' })

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockResolvedValue({ knowledge_version: 'knowledge-1', groups: [], concepts: [
    { id: 'plan.stop', ref: 'concept:plan.stop@1', title: '止损', group: 'plan', version: 1, applies_to: [], summary: 's', related: [] },
    { id: 'review.discipline_chase', ref: 'concept:review.discipline_chase@1', title: '追高', group: 'review', version: 1,
      applies_to: [], summary: 's', related: [] },
  ] })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('KnowledgeForm', () => {
  it('form limits and required scope', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(KnowledgeForm, { onSubmit })
    await fireEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('标题不能为空')
    await fill('标题', 'x'.repeat(61))
    await fill('正文', '正文')
    await fireEvent.click(submit())
    expect(await screen.findByText(/标题最多 60 字（现在 61 字）/)).toBeInTheDocument()
    await fill('标题', '标题')
    await fireEvent.click(submit())
    expect(await screen.findByText(/适用范围必填/)).toBeInTheDocument()
    await fill('适用范围', '趋势回踩后')
    await fireEvent.click(submit())
    expect(await screen.findByText(/挂靠.*1–10/)).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
    await fill('正文', 'x'.repeat(4001))
    await addTicker('nvda')
    await fireEvent.click(submit())
    expect(await screen.findByText(/正文最多 4000 字/)).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits trimmed values with an upper-cased ticker, a concept id and one request id', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(KnowledgeForm, { onSubmit })
    await fill('标题', ' 回踩别追 ')
    await fill('正文', '价格高于入场上沿就等')
    await fill('适用范围', '趋势回踩后')
    await addConcept('review.discipline_chase')
    await addTicker(' nvda ')
    await fireEvent.click(submit())
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    const [values, requestId] = onSubmit.mock.calls[0]
    expect(values).toEqual({ title: '回踩别追', body: '价格高于入场上沿就等', scope: '趋势回踩后', counter_examples: '',
                             concepts: ['review.discipline_chase'], tickers: ['NVDA'] })
    expect(requestId).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('rejects a concept the index does not know and a malformed ticker', async () => {
    render(KnowledgeForm, { onSubmit: vi.fn() })
    await addConcept('nope.nothing')
    expect(await screen.findByText('没有这张概念卡：nope.nothing')).toBeInTheDocument()
    await addTicker('not a ticker')
    expect(await screen.findByText(/标的代码不合法/)).toBeInTheDocument()
  })

  it('requireCounter makes the counter examples mandatory', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(KnowledgeForm, { onSubmit, requireCounter: true,
      initial: { title: 't', body: 'b', scope: 's', counter_examples: '', concepts: ['concept:plan.stop@1'], tickers: [] } })
    await fireEvent.click(submit())
    expect(await screen.findByText(/反例必填/)).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
    await fill('反例', '财报前后除外')
    await fireEvent.click(submit())
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
  })

  it('prefills from a version and writes plain concept ids back', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(KnowledgeForm, { onSubmit, initial: version(2) })
    expect((screen.getByLabelText('标题') as HTMLInputElement).value).toBe('回踩别追 v2')
    expect((screen.getByLabelText('正文') as HTMLTextAreaElement).value).toBe('第 2 版正文\n第二行')
    await fireEvent.click(submit())
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ concepts: ['review.discipline_chase'], tickers: ['NVDA'] })
  })

  it('removes an attachment again', async () => {
    render(KnowledgeForm, { onSubmit: vi.fn(), initial: version(1) })
    await fireEvent.click(screen.getByRole('button', { name: '移除标的 NVDA' }))
    expect(screen.queryByRole('button', { name: '移除标的 NVDA' })).toBeNull()
  })

  it('failure keeps the values; the same content retries with the same request id, changed content with a new one', async () => {
    const onSubmit = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(undefined)
    render(KnowledgeForm, { onSubmit, initial: version(1) })
    await fireEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')
    expect((screen.getByLabelText('标题') as HTMLInputElement).value).toBe('回踩别追 v1')
    await fireEvent.click(submit())
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2))
    expect(onSubmit.mock.calls[1][1]).toBe(onSubmit.mock.calls[0][1])
    // after a success the next write is a new write
    await fireEvent.click(submit())
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(3))
    expect(onSubmit.mock.calls[2][1]).not.toBe(onSubmit.mock.calls[1][1])
  })

  it('reports values and validity to a parent that owns the submit', async () => {
    const onChange = vi.fn()
    render(KnowledgeForm, { hideSubmit: true, onChange,
      initial: { title: 't', body: 'b', scope: '', counter_examples: 'c', concepts: ['concept:plan.stop@1'], tickers: [] } })
    expect(screen.queryByRole('button', { name: '提交' })).toBeNull()
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(onChange.mock.lastCall![1]).toMatch(/适用范围必填/)
    await fill('适用范围', '范围')
    expect(onChange.mock.lastCall![0]).toMatchObject({ scope: '范围', concepts: ['plan.stop'] })
    expect(onChange.mock.lastCall![1]).toBeNull()
  })
})
