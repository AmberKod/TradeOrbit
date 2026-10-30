<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './components/AppShell.vue'
const route = useRoute()
const publicPage = computed(() => route.meta.public === true)
</script>
<template><RouterView v-if="publicPage" /><AppShell v-else><RouterView /></AppShell></template>
