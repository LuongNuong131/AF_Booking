<script setup lang="ts">
import { ElDialog } from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import { useI18n } from 'vue-i18n'
import { useUiStore } from '../stores/ui'
import BaseIcon from './BaseIcon.vue'
const { t } = useI18n()
const ui = useUiStore()
const rows = [
  'focus',
  'lookup',
  'save',
  'task',
  'status',
  'back',
  'palette',
  'move',
  'openRow',
  'watch',
  'rowTask',
  'page',
  'help',
]
</script>
<template>
  <ElDialog
    v-model="ui.shortcutHelp"
    :title="t('shortcuts.title')"
    :show-close="false"
    width="480px"
    align-center
    class="shortcut-dialog"
  >
    <template #header
      ><div class="dialog-heading">
        <h2>{{ t('shortcuts.title') }}</h2>
        <button
          type="button"
          class="icon-button"
          :aria-label="t('common.close')"
          @click="ui.shortcutHelp = false"
        >
          <BaseIcon name="close" />
        </button></div
    ></template>
    <p class="muted">{{ t('shortcuts.hint') }}</p>
    <dl class="shortcut-list">
      <div v-for="row in rows" :key="row">
        <dt>{{ t(`shortcuts.${row}`) }}</dt>
        <dd>
          <kbd>{{ t(`shortcuts.keys.${row}`) }}</kbd>
        </dd>
      </div>
    </dl>
    <p class="help-footnote">{{ t('shortcuts.context') }}</p>
  </ElDialog>
</template>
