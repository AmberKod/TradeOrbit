<script setup lang="ts">
defineProps<{ name?: string; size?: number }>()
const paths: Record<string, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  wallet: 'M3 6h16v14H3z M3 6V3h14v3 M15 11h6v5h-6z',
  chart: 'M3 3v18h18 M6 15l4-5 4 3 6-8',
  link: 'M10 13a5 5 0 007 0l3-3a5 5 0 00-7-7l-2 2 M14 11a5 5 0 00-7 0l-3 3a5 5 0 007 7l2-2',
  shield: 'M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6',
  pulse: 'M2 12h5l3-8 4 16 3-8h5',
  bell: 'M5 17h14l-2-3V9a5 5 0 00-10 0v5z M10 21h4',
  arrow: 'M4 12h16 M14 6l6 6-6 6',
  plus: 'M12 4v16 M4 12h16',
  log: 'M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5',
  lock: 'M5 10h14v11H5z M8 10V7a4 4 0 018 0v3 M12 14v3',
  logout: 'M9 4H4v16h5 M10 12h11 M17 8l4 4-4 4',
  refresh: 'M20 7v5h-5 M4 17v-5h5 M19 12a7 7 0 00-12-5L4 10 M5 12a7 7 0 0012 5l3-3',
}
</script>
<template><svg :width="size ?? 19" :height="size ?? 19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name ?? 'grid'] ?? paths.grid" /></svg></template>
