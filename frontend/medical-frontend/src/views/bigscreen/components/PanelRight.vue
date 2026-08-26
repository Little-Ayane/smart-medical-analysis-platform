<template>
  <div class="panel-right">
    <!-- 支付结构 -->
    <div class="panel-card">
      <div class="card-title">支付方式占比 <span class="tag">PIE</span></div>
      <div class="chart-box" ref="chartPaymentRef"></div>
    </div>
    <!-- 严重程度分布 -->
    <div class="panel-card">
      <div class="card-title">严重程度分布 <span class="tag">GAUGE</span></div>
      <div class="chart-box" ref="chartSeverityRef"></div>
    </div>
    <!-- DRG 排名 -->
    <div class="panel-card">
      <div class="card-title">DRG 排名 TOP10 <span class="tag">TABLE</span></div>
      <div class="table-box">
        <div class="table-header">
          <span class="col-rank">#</span>
          <span class="col-name">DRG名称</span>
          <span class="col-cases">病例数</span>
          <span class="col-cost">费用</span>
        </div>
        <div class="table-body" ref="scrollBody">
          <div class="table-row" v-for="(item, idx) in topDrg" :key="idx"
               :class="{ 'row-highlight': idx < 3 }">
            <span class="col-rank">
              <span class="rank-badge" :class="'rank-' + (idx + 1)">{{ idx + 1 }}</span>
            </span>
            <span class="col-name" :title="item.drg_name">{{ item.drg_name?.substring(0, 18) || '' }}</span>
            <span class="col-cases">{{ (item.cases || 0).toLocaleString() }}</span>
            <span class="col-cost">${{ (item.avg_charges || 0).toLocaleString() }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { PAYMENT, SEVERITY, t } from '@/utils/labels'

const props = defineProps({
  paymentTypes: { type: Array, default: () => [] },
  severityDist: { type: Array, default: () => [] },
  topDrg: { type: Array, default: () => [] }
})

const chartPaymentRef = ref(null)
const chartSeverityRef = ref(null)
const scrollBody = ref(null)
let charts = []
let scrollTimer = null

const PIE_COLORS = ['#00e5ff', '#40c4ff', '#7c4dff', '#ffd740', '#ff5252', '#69f0ae', '#ff80ab', '#b388ff']

function initPaymentChart() {
  if (!chartPaymentRef.value || props.paymentTypes.length === 0) return
  const chart = echarts.init(chartPaymentRef.value, 'medical')
  const data = props.paymentTypes.slice(0, 8).map((d, i) => ({
    value: d.cases,
    name: t(PAYMENT, d.payment_type),
    itemStyle: { color: PIE_COLORS[i % PIE_COLORS.length] }
  }))
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {d}%' },
    series: [{
      type: 'pie',
      radius: ['30%', '70%'],
      center: ['50%', '50%'],
      roseType: 'radius',
      label: { show: false },
      labelLine: { show: false },
      itemStyle: {
        borderColor: '#0a2a5e', borderWidth: 2,
        shadowBlur: 15, shadowColor: 'rgba(0,229,255,0.3)'
      },
      emphasis: {
        scale: true, scaleSize: 8,
        itemStyle: { shadowBlur: 25, shadowColor: 'rgba(0,229,255,0.8)' }
      },
      data,
      animationType: 'expansion',
      animationEasing: 'elasticOut'
    }]
  })
  charts.push(chart)
}

function initSeverityChart() {
  if (!chartSeverityRef.value || props.severityDist.length === 0) return
  const chart = echarts.init(chartSeverityRef.value, 'medical')
  const sevColors = { 'Minor': '#69f0ae', 'Moderate': '#ffd740', 'Major': '#ff80ab', 'Extreme': '#ff5252', 'Unknown': '#7da3d4' }
  const data = props.severityDist.map(d => ({
    value: d.cases,
    name: t(SEVERITY, d.severity),
    itemStyle: { color: sevColors[d.severity] || '#7da3d4' }
  }))
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['30%', '70%'],
      center: ['50%', '50%'],
      label: { show: false },
      labelLine: { show: false },
      itemStyle: {
        borderColor: '#0a2a5e', borderWidth: 2,
        shadowBlur: 10, shadowColor: 'rgba(0,229,255,0.2)'
      },
      emphasis: {
        scale: true, scaleSize: 6,
        itemStyle: { shadowBlur: 20, shadowColor: 'rgba(0,229,255,0.6)' }
      },
      data
    }]
  })
  charts.push(chart)
}

function startTableScroll() {
  if (scrollTimer) clearInterval(scrollTimer)
  scrollTimer = setInterval(() => {
    if (!scrollBody.value) return
    const el = scrollBody.value
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 5) {
      el.scrollTop = 0
    } else {
      el.scrollTop += 1
    }
  }, 100)
}

function initAll() {
  charts.forEach(c => c.dispose())
  charts = []
  nextTick(() => {
    initPaymentChart()
    initSeverityChart()
    startTableScroll()
  })
}

const resizeHandler = () => charts.forEach(c => c.resize())

watch(() => [props.paymentTypes, props.severityDist, props.topDrg], initAll, { deep: true })

onMounted(() => {
  initAll()
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeHandler)
  charts.forEach(c => c.dispose())
  if (scrollTimer) clearInterval(scrollTimer)
})
</script>

<style scoped>
.panel-right {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  width: 100%;
}
.panel-card {
  flex: 1;
  min-height: 0;
  background: linear-gradient(135deg, rgba(8, 24, 56, 0.8) 0%, rgba(13, 33, 55, 0.6) 100%);
  border: 1px solid transparent;
  border-image: linear-gradient(135deg, rgba(0, 229, 255, 0.4), rgba(0, 229, 255, 0.1)) 1;
  border-radius: 0;
  padding: 16px;
  display: flex;
  flex-direction: column;
  position: relative;
  backdrop-filter: blur(12px);
  box-shadow:
    0 0 20px rgba(0, 229, 255, 0.05),
    inset 0 0 30px rgba(0, 229, 255, 0.02);
  transition: all 0.3s ease;
}
.panel-card:hover {
  box-shadow:
    0 0 30px rgba(0, 229, 255, 0.1),
    inset 0 0 40px rgba(0, 229, 255, 0.03);
  border-image: linear-gradient(135deg, rgba(0, 229, 255, 0.6), rgba(0, 229, 255, 0.2)) 1;
}
.panel-card::before, .panel-card::after {
  content: "";
  position: absolute;
  width: 16px;
  height: 16px;
  border-color: #00e5ff;
  border-style: solid;
  border-width: 0;
  filter: drop-shadow(0 0 4px rgba(0, 229, 255, 0.5));
}
.panel-card::before { top: -1px; left: -1px; border-top-width: 2px; border-left-width: 2px; }
.panel-card::after { bottom: -1px; right: -1px; border-bottom-width: 2px; border-right-width: 2px; }
.card-title {
  font-size: 14px;
  font-weight: bold;
  color: #4fc3f7;
  padding-left: 12px;
  border-left: 3px solid #00e5ff;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  text-shadow: 0 0 10px rgba(0, 229, 255, 0.3);
}
.tag {
  font-size: 9px;
  color: #7da3d4;
  background: rgba(0, 229, 255, 0.15);
  padding: 2px 6px;
  border-radius: 2px;
  border: 1px solid rgba(0, 229, 255, 0.3);
  font-weight: normal;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.chart-box {
  flex: 1;
  width: 100%;
  min-height: 0;
}
.table-box {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.table-header {
  display: flex;
  padding: 6px 8px;
  font-size: 11px;
  color: #7da3d4;
  border-bottom: 1px solid rgba(0, 229, 255, 0.15);
  flex-shrink: 0;
  background: rgba(0, 229, 255, 0.03);
  letter-spacing: 1px;
}
.table-body {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: none;
}
.table-body::-webkit-scrollbar { display: none; }
.table-row {
  display: flex;
  padding: 5px 8px;
  font-size: 11px;
  color: #a8c5f0;
  border-bottom: 1px solid rgba(0, 229, 255, 0.05);
  transition: all 0.2s;
}
.table-row:hover {
  background: rgba(0, 229, 255, 0.08);
  box-shadow: inset 0 0 20px rgba(0, 229, 255, 0.05);
}
.row-highlight { color: #e3f2fd; }
.col-rank { width: 28px; text-align: center; flex-shrink: 0; }
.col-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.col-cases { width: 55px; text-align: right; font-family: 'Courier New', monospace; flex-shrink: 0; }
.col-cost { width: 70px; text-align: right; font-family: 'Courier New', monospace; flex-shrink: 0; }
.rank-badge {
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  font-size: 10px;
  font-weight: bold;
}
.rank-1 { background: linear-gradient(135deg, #ffd740, #ff9100); color: #1a1a2e; }
.rank-2 { background: linear-gradient(135deg, #b0bec5, #78909c); color: #1a1a2e; }
.rank-3 { background: linear-gradient(135deg, #ff8a65, #d84315); color: #fff; }
</style>
