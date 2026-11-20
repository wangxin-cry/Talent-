<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-brand">
        <span class="logo">T</span>
        <span class="name">TalentMatch</span>
      </div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  position: relative;
  min-height: 100%;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  overflow: hidden;
  background:
    radial-gradient(760px 460px at 12% 0%, rgba(99, 102, 241, 0.14), transparent 60%),
    radial-gradient(680px 420px at 92% 100%, rgba(139, 92, 246, 0.12), transparent 62%),
    var(--bg);
}
.auth-page::before,
.auth-page::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  pointer-events: none;
}
.auth-page::before {
  width: 300px;
  height: 300px;
  left: -110px;
  top: -80px;
  background: rgba(99, 102, 241, 0.16);
}
.auth-page::after {
  width: 260px;
  height: 260px;
  right: -90px;
  bottom: -90px;
  background: rgba(167, 139, 250, 0.16);
}

.auth-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(233, 235, 243, 0.9);
  border-radius: 18px;
  padding: 34px 30px 28px;
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(10px);
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  font-size: 15.5px;
  letter-spacing: -0.01em;
  margin-bottom: 22px;
}
.logo {
  width: 30px;
  height: 30px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  background: linear-gradient(135deg, #5b54ee, #8b5cf6);
  box-shadow: 0 6px 14px -6px rgba(79, 70, 229, 0.65), inset 0 1px 0 rgba(255, 255, 255, 0.28);
}

h1 {
  margin: 0 0 6px;
  font-size: 23px;
  font-weight: 750;
  letter-spacing: -0.02em;
}
.subtitle {
  margin: 0 0 22px;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.65;
}
.auth-footer {
  margin-top: 18px;
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--muted);
}
.auth-footer a {
  color: var(--primary);
  text-decoration: none;
  font-weight: 550;
}
.auth-footer a:hover {
  text-decoration: underline;
}
</style>
