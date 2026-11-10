<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import ReportsView from './ReportsView.vue'
import MyDailyReportView from './MyDailyReportView.vue'
const auth = useAuthStore()
</script>
<template><MyDailyReportView v-if="auth.user?.role === 'agent'" /><ReportsView v-else /></template>
