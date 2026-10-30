<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { AuditEntry } from '../types/domain'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
const entries = ref<AuditEntry[]>([]), error = ref(''), loading = ref(false)
const labels: Record<string, string> = { 'auth.login': '登录工作空间', 'auth.logout': '退出登录', 'account.created': '创建账户连接', 'account.updated': '修改账户配置', 'account.archived': '归档账户连接', 'account.credentials_saved': '更新加密密钥', 'identity.user_created': '创建工作空间用户' }
function time(value: string): string { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
async function refresh(): Promise<void> { loading.value = true; error.value = ''; try { entries.value = await api<AuditEntry[]>('/audit-logs?limit=50') } catch (cause) { error.value = cause instanceof Error ? cause.message : '审计日志读取失败' } finally { loading.value = false } }
onMounted(refresh)
</script>
<template><div class="page-heading"><div><span class="eyebrow">ACTIVITY & AUDIT</span><h1>操作审计</h1><p>最近 50 条工作空间操作，保留操作者与请求关联编号。</p></div><button class="button secondary" :disabled="loading" @click="refresh"><Icon name="refresh" :size="16" />刷新记录</button></div><div v-if="error" class="alert error" role="alert">{{ error }}</div><section class="panel"><div class="panel-heading"><h2>操作记录</h2><span class="pill muted-pill">仅管理员可见</span></div><div v-if="loading" class="loading-state">读取审计记录…</div><EmptyState v-else-if="!entries.length" title="暂无操作记录" description="账户配置与登录操作会在这里留下审计记录。" icon="log" /><div v-else class="table-scroll"><table><thead><tr><th>时间</th><th>操作</th><th>目标 / 操作者</th><th>请求编号</th></tr></thead><tbody><tr v-for="entry in entries" :key="entry.id"><td>{{ time(entry.created_at) }}</td><td><strong>{{ labels[entry.action] ?? entry.action }}</strong><small class="mono">{{ entry.action }}</small></td><td class="mono">{{ entry.target_id?.slice(0, 8) ?? '—' }}<small>用户 {{ entry.actor_id?.slice(0, 8) ?? '系统' }}</small></td><td class="mono audit-id">{{ entry.request_id }}</td></tr></tbody></table></div></section></template>
