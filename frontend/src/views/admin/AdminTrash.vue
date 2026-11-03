<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AdminNoteHistory from '../../components/AdminNoteHistory.vue'
const { t } = useI18n(),
  q = ref(''),
  history = ref<InstanceType<typeof AdminNoteHistory> | null>(null)
</script>
<template>
  <section>
    <h2>{{ t('adminUi.trash') }}</h2>
    <form class="admin-filters" @submit.prevent="history?.reload()">
      <label>{{ t('bookingUi.bookingNumber') }}<input v-model="q" maxlength="100" /></label
      ><button class="button" type="submit">{{ t('adminUi.apply') }}</button>
    </form>
    <AdminNoteHistory ref="history" trash :q="q" />
  </section>
</template>
