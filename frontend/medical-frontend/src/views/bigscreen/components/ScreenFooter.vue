<template>
  <div class="screen-footer">
    <div class="footer-stats">
      <div class="footer-item" v-for="(item, idx) in stats" :key="idx">
        <div class="footer-num">{{ item.value }}</div>
        <div class="footer-label">{{ item.label }}</div>
      </div>
    </div>
    <div class="footer-decor">
      <svg width="100%" height="6" preserveAspectRatio="none">
        <defs>
          <linearGradient id="footerGrad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="transparent"/>
            <stop offset="15%" stop-color="#00e5ff" stop-opacity="0.3"/>
            <stop offset="50%" stop-color="#00e5ff" stop-opacity="0.8"/>
            <stop offset="85%" stop-color="#00e5ff" stop-opacity="0.3"/>
            <stop offset="100%" stop-color="transparent"/>
          </linearGradient>
        </defs>
        <rect width="100%" height="1" fill="url(#footerGrad)" y="2"/>
      </svg>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  summary: { type: Object, default: () => ({}) }
})

const stats = computed(() => [
  { label: '总记录数', value: formatNum(props.summary.total_records) },
  { label: '医院数', value: props.summary.total_hospitals || 0 },
  { label: '诊断类型', value: props.summary.total_diagnoses || 0 },
  { label: '年份跨度', value: props.summary.total_years || 5 },
  { label: '急诊率', value: (props.summary.emergency_rate || 0) + '%' }
])

function formatNum(n) {
  if (!n) return '0'
  return Number(n).toLocaleString('en-US')
}
</script>

<style scoped>
.screen-footer {
  flex-shrink: 0;
  padding: 12px 30px 8px;
  z-index: 10;
  position: relative;
}
.footer-stats {
  display: flex;
  justify-content: center;
  gap: 60px;
}
.footer-item {
  text-align: center;
  position: relative;
}
.footer-item::after {
  content: "";
  position: absolute;
  right: -30px;
  top: 50%;
  transform: translateY(-50%);
  width: 1px;
  height: 20px;
  background: linear-gradient(transparent, rgba(0, 229, 255, 0.3), transparent);
}
.footer-item:last-child::after {
  display: none;
}
.footer-num {
  font-size: 22px;
  font-weight: bold;
  color: #00e5ff;
  text-shadow: 0 0 15px rgba(0, 229, 255, 0.6), 0 0 30px rgba(0, 229, 255, 0.3);
  font-family: 'Courier New', monospace;
  letter-spacing: 1px;
}
.footer-label {
  font-size: 11px;
  color: #7da3d4;
  margin-top: 4px;
  letter-spacing: 1px;
}
.footer-decor {
  margin-top: 8px;
}
</style>
