<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { setLanguage } from '../i18n'
import BaseIcon from './BaseIcon.vue'
const { t, locale } = useI18n()
</script>
<template>
  <label class="language-select">
    <BaseIcon name="globe" />
    <span class="sr-only">{{ t('language.title') }}</span>
    <select :value="locale" @change="setLanguage(($event.target as HTMLSelectElement).value)">
      <option value="en">English</option>
      <option value="vi">Tiếng Việt</option>
    </select>
  </label>
</template>
