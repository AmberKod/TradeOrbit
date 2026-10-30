<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { roleNames } from '../types/domain'
import Icon from './Icon.vue'
const route = useRoute(), router = useRouter(), session = useSessionStore()
const error = ref(''), mobileOpen = ref(false)
const primary = [{ to: '/', icon: 'grid', label: '资产总览' }, { to: '/accounts', icon: 'link', label: '账户连接' }]
const upcoming = [{ icon: 'chart', label: '行情工作台', stage: 'E02' }, { icon: 'bell', label: '告警中心', stage: 'E03' }, { icon: 'wallet', label: '交易工作台', stage: 'E04' }, { icon: 'pulse', label: '策略中心', stage: 'E05' }]
watch(() => route.fullPath, () => { mobileOpen.value = false })
watch(() => session.session, (value) => { if (!value && session.initialized) void router.replace('/login') })
async function logout(): Promise<void> { try { await session.logout(); await router.replace('/login') } catch (cause) { error.value = cause instanceof Error ? cause.message : '退出失败，请重试' } }
</script>
<template>
  <div class="app-layout">
    <aside class="sidebar" :class="{ 'is-open': mobileOpen }">
      <RouterLink to="/" class="brand"><span class="brand-mark">◎</span><span>TradeOrbit<small>交易星轨</small></span></RouterLink>
      <div class="workspace-switch"><span class="workspace-avatar">T</span><div><strong>{{ session.session?.workspace.name }}</strong><small>个人交易工作空间</small></div><span class="tiny-tag">E01</span></div>
      <p class="nav-label">工作台</p>
      <nav aria-label="主导航"><RouterLink v-for="item in primary" :key="item.to" :to="item.to" class="nav-item" :class="{ selected: route.path === item.to }"><Icon :name="item.icon" /><span>{{ item.label }}</span></RouterLink>
        <button v-for="item in upcoming" :key="item.label" class="nav-item upcoming" disabled :title="item.stage + ' 阶段实现'"><Icon :name="item.icon" /><span>{{ item.label }}</span><small>{{ item.stage }}</small></button>
      </nav>
      <p class="nav-label">管理</p><nav aria-label="管理导航"><RouterLink to="/system" class="nav-item" active-class="selected"><Icon name="shield" /><span>系统状态</span></RouterLink><RouterLink v-if="session.isAdmin" to="/audit" class="nav-item" active-class="selected"><Icon name="log" /><span>操作审计</span></RouterLink></nav>
      <div class="sidebar-bottom"><span class="status-dot amber"></span><div><strong>安全只读模式</strong><small>交易执行尚未开放</small></div><Icon name="lock" :size="16" /></div>
    </aside>
    <div v-if="mobileOpen" class="sidebar-backdrop" @click="mobileOpen = false"></div>
    <div class="main-region"><header class="topbar"><div class="breadcrumb"><button class="icon-button mobile-toggle" aria-label="展开导航" @click="mobileOpen = !mobileOpen"><Icon name="grid" /></button><span>工作空间</span><span class="muted">/</span><strong>{{ route.meta.title ?? 'TradeOrbit' }}</strong></div><div class="topbar-right"><span class="pill muted-pill"><Icon name="lock" :size="13" /> 交易锁定</span><div class="profile"><span class="profile-avatar">{{ session.session?.user.email.charAt(0).toUpperCase() }}</span><div><strong>{{ session.session?.user.email }}</strong><small>{{ session.session ? roleNames[session.session.role] : '' }}</small></div></div><button class="icon-button" aria-label="退出登录" title="退出登录" @click="logout"><Icon name="logout" /></button></div></header>
      <main class="page-content"><div v-if="error" class="alert error" role="alert">{{ error }}</div><slot /></main><footer class="app-footer"><span>TradeOrbit / Foundation 0.1.0</span><span>DEMO 与 LIVE 独立管理 · 密钥不回传浏览器</span></footer>
    </div>
  </div>
</template>
