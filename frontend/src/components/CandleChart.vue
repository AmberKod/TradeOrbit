<script setup lang="ts">
import { computed } from 'vue'
import type { Candle } from '../types/market'
import { displayNumber, displayTime } from '../types/market'
const props = defineProps<{ candles: Candle[]; symbol: string }>()
const points = computed(() => {
  const rows = props.candles.filter(row => [row.open, row.high, row.low, row.close].every(value => Number.isFinite(Number(value))))
  if (!rows.length) return null
  const low = Math.min(...rows.map(row => Number(row.low))), high = Math.max(...rows.map(row => Number(row.high)))
  const padding = (high - low) * .08 || high * .001 || 1
  const bottom = low - padding, top = high + padding
  const y = (value: string) => 16 + (top - Number(value)) / (top - bottom) * 176
  return { rows: rows.map((row, index) => ({ ...row, x: 12 + (index + .5) * 610 / rows.length, yOpen: y(row.open), yClose: y(row.close), yHigh: y(row.high), yLow: y(row.low), up: Number(row.close) >= Number(row.open) })), width: Math.max(1, Math.min(9, 610 / rows.length * .65)), high: top, low: bottom }
})
</script>
<template>
  <svg v-if="points" class="candle-chart" viewBox="0 0 720 225" role="img" :aria-label="symbol + ' 最近 120 根一分钟 K 线，REST 快照'">
    <g v-for="step in [0, 1, 2, 3, 4]" :key="step"><line x1="10" x2="625" :y1="16 + step * 44" :y2="16 + step * 44" stroke="#263446" stroke-dasharray="3 4" /><text x="634" :y="20 + step * 44" class="axis">{{ displayNumber(String(points.high - step * (points.high - points.low) / 4), 6) }}</text></g>
    <g v-for="row in points.rows" :key="row.open_time" :class="row.up ? 'candle-up' : 'candle-down'"><title>{{ displayTime(row.open_time) }} 开 {{ row.open }} 高 {{ row.high }} 低 {{ row.low }} 收 {{ row.close }}</title><line :x1="row.x" :x2="row.x" :y1="row.yHigh" :y2="row.yLow" /><rect :x="row.x - points.width / 2" :y="Math.min(row.yOpen, row.yClose)" :width="points.width" :height="Math.max(1, Math.abs(row.yClose - row.yOpen))" /></g>
    <text x="12" y="216" class="axis">{{ displayTime(candles[0]?.open_time) }}</text><text x="550" y="216" class="axis">{{ displayTime(candles[candles.length - 1]?.open_time) }}</text>
  </svg><div v-else class="loading-state">暂无可用 K 线快照</div>
</template>
<style scoped>
.candle-chart{display:block;width:100%;min-height:170px}.axis{font:10px Consolas,monospace;fill:#8391a3}.candle-up{stroke:#64d5ad;fill:#64d5ad}.candle-down{stroke:#ef8998;fill:#ef8998}
</style>
