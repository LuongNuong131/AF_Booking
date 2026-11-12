<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCollaborationStore } from '../stores/collaboration'
import { useViewRefresh } from '../composables/useViewRefresh'
const props = withDefaults(defineProps<{ folderKey: string; following?: boolean }>(), { following: undefined })
const { t } = useI18n(), store = useCollaborationStore()
watch(() => [props.folderKey, props.following] as const, ([key, following]) => {
  if (following !== undefined) store.seedFolder(key, following)
  void store.folderFollow(key, undefined, following === undefined)
}, { immediate: true })
useViewRefresh(() => store.folderFollow(props.folderKey, undefined, true))
const selected = computed(() => store.followingFolders[props.folderKey] ?? props.following ?? false)
</script>
<template>
  <button type="button" class="button folder-follow-button" :aria-pressed="selected"
    :disabled="store.folderPending.includes(folderKey)" @click.stop="store.folderFollow(folderKey, !selected)">
    {{ t(selected ? 'followUi.unfollow' : 'followUi.follow') }}
  </button>
</template>
