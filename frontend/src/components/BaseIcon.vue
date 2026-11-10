<script setup lang="ts">
const props = defineProps<{ name: string }>()
const paths: Record<string, string[]> = {
  folder: ['M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10H3V6Z'],
  clock: ['M12 8v4l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0'],
  search: ['m21 21-4.5-4.5 M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0'],
  home: ['m3 10 9-7 9 7', 'M5 9v12h14V9', 'M9 21v-8h6v8'],
  grid: ['M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z'],
  user: ['M20 21v-2a7 7 0 0 0-14 0v2', 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0'],
  shield: ['m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7l8-4Z', 'm9 12 2 2 4-4'],
  chart: ['M3 3v18h18', 'M7 16v-4m5 4V8m5 8V5'],
  bell: ['M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9', 'M10 21h4'],
  sun: [
    'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
    'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1',
  ],
  moon: ['M20 14a8 8 0 0 1-10-10 8 8 0 1 0 10 10Z'],
  logout: ['M9 3H4v18h5', 'M10 12h11m-4-4 4 4-4 4'],
  help: [
    'M12 17h.01',
    'M9 8a3 3 0 1 1 5 2c-2 1-2 2-2 3',
    'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  ],
  menu: ['M4 6h16M4 12h16M4 18h16'],
  close: ['m6 6 12 12M6 18 18 6'],
  copy: ['M9 9h12v12H9z', 'M15 5V3H3v12h2'],
  check: ['m5 12 4 4L19 6'],
  arrow: ['M5 12h14m-5-5 5 5-5 5'],
  chevron: ['m9 5 7 7-7 7'],
  plus: ['M12 5v14M5 12h14'],
  filter: ['M4 7h16M4 17h16', 'M8 4v6M16 14v6'],
  inbox: ['M4 4h16l2 16H2L4 4Z', 'M3 14h5l2 3h4l2-3h5'],
  keyboard: ['M2 5h20v14H2z', 'M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M10 13h8'],
  globe: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0', 'M2 12h20M12 2c-5 5-5 15 0 20 5-5 5-15 0-20'],
}
</script>
<template>
  <svg
    class="icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, index) in paths[props.name] || paths.grid" :key="index" :d="d" />
  </svg>
</template>
