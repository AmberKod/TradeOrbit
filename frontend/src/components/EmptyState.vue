<script setup lang="ts">
import Icon from './Icon.vue'
defineProps<{ title: string; description: string; icon?: string }>()
</script>
<template><div class="empty-state"><span class="empty-icon"><Icon :name="icon ?? 'chart'" :size="25" /></span><h3>{{ title }}</h3><p>{{ description }}</p><slot /></div></template>
