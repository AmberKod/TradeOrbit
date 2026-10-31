<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import Icon from '../components/Icon.vue'
const email = ref(''), password = ref(''), error = ref(''), busy = ref(false)
const store = useSessionStore(), router = useRouter()
async function submit(): Promise<void> {
  busy.value = true; error.value = ''
  try { await store.login(email.value, password.value); password.value = ''; await router.replace('/') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '登录失败' }
  finally { busy.value = false }
}
</script>
<template><div class="login-page"><section class="login-story"><div class="brand"><span class="brand-mark">◎</span><span>TradeOrbit<small>交易星轨</small></span></div><div class="login-heading"><span class="eyebrow">ONE WORKSPACE. YOUR ORBIT.</span><h1>多交易所资产，<br>回到一个视野。</h1><p>从清晰的账户管理开始，让资产、风险和每一次交易都有据可循。</p><div class="orbit-art" aria-hidden="true"><div class="orbit-ring outer"></div><div class="orbit-ring inner"></div><span class="orbit-core">◎</span><span class="orbit-exchange orbit-one">BINANCE</span><span class="orbit-exchange orbit-two">BITGET</span><span class="orbit-exchange orbit-three">OKX</span></div></div><div class="login-features"><span><Icon name="shield" :size="16" />工作空间隔离</span><span><Icon name="lock" :size="16" />密钥加密存储</span></div></section><section class="login-form-region"><form class="login-form" @submit.prevent="submit"><span class="pill">PUBLIC MARKETS · E02</span><h2>欢迎回来</h2><p class="muted">登录你的 TradeOrbit 工作空间</p><div v-if="error || store.error" class="alert error" role="alert">{{ error || store.error }}</div><label>邮箱地址<input v-model="email" type="email" autocomplete="username" placeholder="you@example.com" required maxlength="254"></label><label>登录密码<input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" required maxlength="128"></label><button class="button primary full-width" :disabled="busy">{{ busy ? '正在登录…' : '进入工作空间' }}<Icon name="arrow" :size="17" /></button><div class="login-setup"><strong>首次启动？</strong><p>先在后端目录运行管理员初始化命令，设置自己的邮箱和密码。</p><code>uv run python -m app.cli bootstrap-admin --email you@example.com</code></div><p class="fine-print">当前为基础建设阶段，交易执行保持关闭。没有默认管理员密码。</p></form></section></div></template>
