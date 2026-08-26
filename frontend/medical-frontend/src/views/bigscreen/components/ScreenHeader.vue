<template>
  <div class="screen-header">
    <div class="header-left">
      <div class="back-btn" @click="$router.push('/dashboard')" title="返回主页">
        <span>◀</span>
      </div>
      <div>
        <div class="title">NY 州医疗数据 3D 可视化大屏</div>
        <div class="subtitle">STAR SCHEMA · 2020-2024 · 实时数据监控</div>
      </div>
    </div>
    <div class="header-stats">
      <div class="stat-item">
        <div class="stat-num">{{ formatNum(summary.total_records) }}</div>
        <div class="stat-lbl">总记录数</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">{{ summary.total_hospitals || 0 }}</div>
        <div class="stat-lbl">医院数</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">{{ summary.total_diagnoses || 0 }}</div>
        <div class="stat-lbl">诊断数</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">{{ summary.emergency_rate || 0 }}%</div>
        <div class="stat-lbl">急诊率</div>
      </div>
    </div>
    <!-- Decorative SVG -->
    <svg class="header-bg" viewBox="0 0 1920 80" preserveAspectRatio="none">
      <defs>
        <radialGradient id="rg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#fff" stop-opacity="1"/>
          <stop offset="100%" stop-color="#fff" stop-opacity="0"/>
        </radialGradient>
        <mask id="m1">
          <circle r="80" cx="0" cy="0" fill="url(#rg)">
            <animateMotion dur="4s" path="M0,72 L620,72 L670,80 L960,80" keyPoints="0;1" keyTimes="0;1" repeatCount="indefinite"/>
          </circle>
        </mask>
        <mask id="m2">
          <circle r="80" cx="0" cy="0" fill="url(#rg)">
            <animateMotion dur="4s" path="M1920,72 L1300,72 L1250,80 L960,80" keyPoints="0;1" keyTimes="0;1" repeatCount="indefinite"/>
          </circle>
        </mask>
      </defs>
      <path d="M0,0 L1920,0 L1920,68 L1300,68 L1250,80 L670,80 L620,68 L0,68 Z" fill="rgba(2,14,42,0.8)"/>
      <path d="M0,68 L620,68 L670,80 L1250,80 L1300,68 L1920,68" fill="none" stroke="#00e5ff" stroke-width="1" opacity="0.3"/>
      <path d="M0,68 L620,68 L670,80 L960,80" fill="none" stroke="#00e5ff" stroke-width="2" mask="url(#m1)" opacity="0.6"/>
      <path d="M1920,68 L1300,68 L1250,80 L960,80" fill="none" stroke="#00e5ff" stroke-width="2" mask="url(#m2)" opacity="0.6"/>
    </svg>
  </div>
</template>

<script setup>
defineProps({
  summary: { type: Object, default: () => ({}) }
})

function formatNum(n) {
  if (!n) return '0'
  return Number(n).toLocaleString('en-US')
}
</script>

<style scoped>
.screen-header {
  position: relative;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  flex-shrink: 0;
  z-index: 10;
}
.header-bg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: -1;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.back-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 229, 255, 0.1);
  border: 1px solid rgba(0, 229, 255, 0.4);
  border-radius: 4px;
  color: #00e5ff;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}
.back-btn:hover {
  background: rgba(0, 229, 255, 0.25);
  box-shadow: 0 0 16px rgba(0, 229, 255, 0.5);
}
.title {
  font-size: 28px;
  font-weight: bold;
  background: linear-gradient(180deg, #ffffff 0%, #4fc3f7 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: 4px;
  text-shadow: 0 0 20px rgba(0, 229, 255, 0.3);
  filter: drop-shadow(0 0 10px rgba(0, 229, 255, 0.2));
}
.subtitle {
  font-size: 12px;
  color: #7da3d4;
  letter-spacing: 2px;
  margin-top: 4px;
  text-shadow: 0 0 8px rgba(0, 229, 255, 0.3);
}
.header-stats {
  display: flex;
  gap: 32px;
}
.stat-item {
  text-align: center;
  position: relative;
  padding: 0 8px;
}
.stat-item::before {
  content: "";
  position: absolute;
  left: -16px;
  top: 50%;
  transform: translateY(-50%);
  width: 1px;
  height: 24px;
  background: linear-gradient(transparent, rgba(0, 229, 255, 0.3), transparent);
}
.stat-item:first-child::before {
  display: none;
}
.stat-num {
  font-size: 22px;
  font-weight: bold;
  color: #00e5ff;
  text-shadow: 0 0 15px rgba(0, 229, 255, 0.6), 0 0 30px rgba(0, 229, 255, 0.3);
  font-family: 'Courier New', monospace;
  letter-spacing: 1px;
}
.stat-lbl {
  font-size: 11px;
  color: #7da3d4;
  margin-top: 4px;
  letter-spacing: 1px;
}
</style>
