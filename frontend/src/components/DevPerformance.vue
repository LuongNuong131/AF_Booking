<script setup lang="ts">
import { apiMeasurements, realtimeEvents } from '../runtime/performance'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>
<template>
  <details class="dev-performance">
    <summary>{{ t('outboxUi.devMetrics') }}</summary>
    <p>{{ t('outboxUi.realtimeEvents') }}: {{ realtimeEvents }}</p>
    <table>
      <tbody>
        <tr v-for="(row, i) in apiMeasurements" :key="i">
          <td>{{ row.path }}</td>
          <td>{{ row.timing }}</td>
        </tr>
      </tbody>
    </table>
  </details>
</template>
