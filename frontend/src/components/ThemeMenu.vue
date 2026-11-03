<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore, type Theme } from '../stores/ui'
import BaseIcon from './BaseIcon.vue'
const { t } = useI18n()
const ui = useUiStore()
const menu = ref<HTMLDetailsElement | null>(null)
function set(value: Theme) {
  ui.setTheme(value)
  if (menu.value) {
    menu.value.open = false
    menu.value.querySelector('summary')?.focus()
  }
}
function close(event: KeyboardEvent) {
  if (event.key === 'Escape' && menu.value?.open) {
    event.stopPropagation()
    menu.value.open = false
    menu.value.querySelector('summary')?.focus()
  }
}
</script>
<template>
  <details ref="menu" class="header-menu" @keydown="close">
    <summary
      class="icon-button"
      :aria-label="t('theme.title')"
      :title="t('theme.title')"
      aria-haspopup="menu"
    >
      <BaseIcon :name="ui.resolvedTheme === 'dark' ? 'moon' : 'sun'" />
    </summary>
    <div class="menu-popover theme-options" role="menu" :aria-label="t('theme.title')">
      <button
        v-for="value in ['system', 'light', 'dark'] as const"
        :key="value"
        type="button"
        role="menuitemradio"
        :aria-checked="ui.theme === value"
        @click="set(value)"
      >
        <BaseIcon
          :name="value === 'system' ? 'globe' : value === 'light' ? 'sun' : 'moon'"
        /><span>{{ t(`theme.${value}`) }}</span
        ><BaseIcon v-if="ui.theme === value" name="check" />
      </button>
    </div>
  </details>
</template>
