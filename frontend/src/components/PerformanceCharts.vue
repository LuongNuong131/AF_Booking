<script setup lang="ts">
import { onMounted, onScopeDispose, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { PerformanceReport } from '../types/api.generated'
const props = defineProps<{ report: PerformanceReport }>(),
  { t } = useI18n(),
  bars = ref<HTMLCanvasElement | null>(null),
  line = ref<HTMLCanvasElement | null>(null)
let charts: Array<{ destroy: () => void }> = [],
  disposed = false
async function draw() {
  const { default: Chart } = await import('chart.js/auto')
  if (disposed || !bars.value || !line.value) return
  charts.forEach((c) => c.destroy())
  charts = [
    new Chart(bars.value, {
      type: 'bar',
      data: {
        labels: props.report.users.map((u) => u.agent?.full_name ?? t('adminUi.unassigned')),
        datasets: [
          {
            label: t('adminUi.notes'),
            data: props.report.users.map((u) => u.note_count ?? 0),
            backgroundColor: '#536dfe',
          },
          {
            label: t('status_labels.done'),
            data: props.report.users.map((u) => u.done_count ?? 0),
            backgroundColor: '#24a780',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    }),
    new Chart(line.value, {
      type: 'line',
      data: {
        labels: props.report.trend.map((d) => d.date),
        datasets: [
          {
            label: t('adminUi.notes'),
            data: props.report.trend.map((d) => d.count),
            borderColor: '#536dfe',
            tension: 0.2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    }),
  ]
}
onMounted(() => {
  void draw()
})
watch(
  () => props.report,
  () => {
    void draw()
  },
)
onScopeDispose(() => {
  disposed = true
  charts.forEach((c) => c.destroy())
})
</script>
<template>
  <section class="report-charts">
    <div>
      <canvas ref="bars" role="img" :aria-label="t('adminUi.userChart')" />
    </div>
    <div>
      <canvas ref="line" role="img" :aria-label="t('adminUi.trendChart')" />
    </div>
  </section>
</template>
