<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">T</span>
        <span class="name">TalentMatch</span>
      </div>
      <nav class="nav">
        <RouterLink to="/" active-class="active">工作台</RouterLink>
        <span class="disabled">职位</span>
        <span class="disabled">候选人</span>
        <span class="disabled">看板</span>
        <span class="disabled">成本</span>
      </nav>
      <div class="right">
        <span class="badge">阶段一 · 骨架</span>
      </div>
    </header>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style>
:root {
  --bg: #f5f6fa;
  --panel: #ffffff;
  --line: #e7e9f0;
  --text: #1e2430;
  --muted: #6b7280;
  --primary: #4f46e5;
  --primary-soft: #eef1ff;
}
* { box-sizing: border-box; }
html, body, #app { height: 100%; margin: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
.app-shell { height: 100%; display: flex; flex-direction: column; }
.topbar {
  height: 56px; display: flex; align-items: center; gap: 26px;
  padding: 0 22px; background: var(--panel); border-bottom: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 9px; font-weight: 700; }
.logo {
  width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center;
  color: #fff; font-size: 13px; background: linear-gradient(135deg, #6366f1, #8b5cf6);
}
.nav { display: flex; align-items: center; gap: 4px; }
.nav a, .nav .disabled {
  padding: 6px 12px; border-radius: 8px; font-size: 13.5px;
  color: var(--muted); text-decoration: none;
}
.nav a:hover { background: #f2f3f8; color: var(--text); }
.nav a.active { background: var(--primary-soft); color: var(--primary); font-weight: 600; }
.nav .disabled { opacity: .45; cursor: not-allowed; }
.right { margin-left: auto; }
.badge {
  font-size: 12px; color: var(--primary); background: var(--primary-soft);
  padding: 4px 10px; border-radius: 20px; font-weight: 600;
}
.content { flex: 1; overflow: auto; padding: 24px; }
</style>
