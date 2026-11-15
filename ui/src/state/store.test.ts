/// <reference types="node" />
import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'
import type { MarketSummary, Move, Tick } from '../lib/types'
import { useStore } from './store.ts'

const initial = useStore.getState()
const { apply } = initial

const market = (id: string): MarketSummary => ({
  id, venue: 'kalshi', title: id, url: null, price: 40, change_24h: 2, ticks_today: 3, made_up: false, poll_seconds: 60,
})
const tick = (id: number): Tick => ({ id, market_id: 'a', headline: `tick ${id}` }) as Tick

beforeEach(() => {
  useStore.setState(initial, true)
  useStore.getState().setMarkets([market('a'), market('b')])
})

test('a tick_update for a tick not on the tape adds nothing', () => {
  apply({ type: 'tick_update', data: tick(9) }) // no tape loaded yet
  assert.equal(useStore.getState().ticks.a, undefined)
  useStore.getState().setTicks('a', [tick(1)])
  apply({ type: 'tick_update', data: tick(9) })
  assert.deepEqual(useStore.getState().ticks.a, [tick(1)])
})

test('a price for a market not in the list is kept aside, not added to the list', () => {
  apply({ type: 'price', data: { market_id: 'x', ts: 1, price: 70 } })
  const s = useStore.getState()
  assert.equal(s.otherPrices.x, 70)
  assert.equal(s.markets.x, undefined)
  assert.equal(s.prices.x, undefined)
  assert.deepEqual(s.order, ['a', 'b'])
})

test('deleting the selected market selects the next one, and none once the list is empty', () => {
  assert.equal(useStore.getState().selectedId, 'a')
  apply({ type: 'market', data: { market_id: 'a', status: 'deleted' } })
  const s = useStore.getState()
  assert.equal(s.markets.a, undefined)
  assert.deepEqual(s.order, ['b'])
  assert.equal(s.selectedId, 'b')
  apply({ type: 'market', data: { market_id: 'b', status: 'deleted' } })
  assert.equal(useStore.getState().selectedId, null)
})

test('a reset empties the tape, moves, prices and pending rows of that market only', () => {
  const st = useStore.getState()
  st.setTicks('a', [tick(1)])
  st.setPrices('a', [{ ts: 1, price: 40 }])
  st.setMoves('a', [{ id: 1, market_id: 'a' } as Move])
  st.addPending('a', 'hello', 'typed')
  apply({ type: 'market', data: { market_id: 'a', status: 'reset' } })
  const s = useStore.getState()
  assert.deepEqual([s.ticks.a, s.moves.a, s.prices.a, s.pending.a], [[], [], [], []])
  assert.deepEqual(s.markets.a, { ...market('a'), ticks_today: 0, change_24h: null })
  assert.deepEqual(s.markets.b, market('b'))
})
