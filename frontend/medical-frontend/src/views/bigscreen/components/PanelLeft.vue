<template>
  <div class="panel-left">
    <!-- 疾病 TOP5 -->
    <div class="panel-card">
      <div class="card-title">疾病诊断 TOP10 <span class="tag">BAR</span></div>
      <div class="chart-box" ref="chartDiseaseRef"></div>
    </div>
    <!-- 年龄分布 -->
    <div class="panel-card">
      <div class="card-title">年龄分布 <span class="tag">BAR</span></div>
      <div class="chart-box" ref="chartAgeRef"></div>
    </div>
    <!-- 服务区域急诊率 -->
    <div class="panel-card">
      <div class="card-title">服务区域急诊率 <span class="tag">BAR</span></div>
      <div class="chart-box" ref="chartEmergencyRef"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { AGE_GROUP, t } from '@/utils/labels'

const props = defineProps({
  topDiseases: { type: Array, default: () => [] },
  ageDistribution: { type: Array, default: () => [] },
  serviceAreas: { type: Array, default: () => [] }
})

const chartDiseaseRef = ref(null)
const chartAgeRef = ref(null)
const chartEmergencyRef = ref(null)
let charts = []

const axisStyle = {
  axisLine: { lineStyle: { color: 'rgba(64,196,255,0.4)' } },
  axisLabel: { color: '#a8c5f0', fontSize: 10 },
  splitLine: { lineStyle: { color: 'rgba(64,196,255,0.1)' } },
  axisTick: { lineStyle: { color: 'rgba(64,196,255,0.2)' } }
}

function initDiseaseChart() {
  if (!chartDiseaseRef.value || props.topDiseases.length === 0) return
  const chart = echarts.init(chartDiseaseRef.value, 'medical')
  const data = props.topDiseases.slice(0, 10).reverse()
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 4, right: 50, top: 6, bottom: 2, containLabel: true },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      data: data.map(d => d.diagnosis?.substring(0, 14) || ''),
      ...axisStyle,
      axisLabel: { color: '#a8c5f0', fontSize: 11 }
    },
    series: [{
      type: 'bar',
      data: data.map(d => d.cases),
      barWidth: 16,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#0d47a1' },
          { offset: 1, color: '#40c4ff' }
        ]),
        borderRadius: [0, 2, 2, 0]
      },
      label: {
        show: true, position: 'right',
        color: '#a8c5f0', fontSize: 11,
        formatter: p => p.value.toLocaleString()
      }
    }]
  })
  charts.push(chart)
}

function initAgeChart() {
  if (!chartAgeRef.value || props.ageDistribution.length === 0) return
  const chart = echarts.init(chartAgeRef.value, 'medical')

  // 按年龄顺序排序，去重（优先使用 'to' 格式）
  const ageOrder = ['0 to 17', '18 to 29', '30 to 49', '50 to 69', '70 or Older']
  const sorted = [...props.ageDistribution]
    .filter(d => ageOrder.includes(d.age_group))
    .sort((a, b) => ageOrder.indexOf(a.age_group) - ageOrder.indexOf(b.age_group))

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 10, right: 10, top: 20, bottom: 2, containLabel: true },
    xAxis: {
      type: 'category',
      data: sorted.map(d => t(AGE_GROUP, d.age_group)),
      ...axisStyle,
      axisLabel: { color: '#a8c5f0', fontSize: 11, rotate: 0 },
      boundaryGap: true
    },
    yAxis: { type: 'value', show: false },
    series: [{
      type: 'bar',
      data: sorted.map(d => d.cases),
      barCategoryGap: '20%',
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#7c4dff' },
          { offset: 1, color: '#40c4ff' }
        ]),
        borderRadius: [3, 3, 0, 0]
      },
      label: {
        show: true, position: 'top',
        color: '#a8c5f0', fontSize: 11,
        formatter: p => (p.value / 1000).toFixed(0) + 'k'
      }
    }]
  })
  charts.push(chart)
}

function initEmergencyChart() {
  if (!chartEmergencyRef.value || props.serviceAreas.length === 0) return
  const chart = echarts.init(chartEmergencyRef.value, 'medical')
  const sorted = [...props.serviceAreas].sort((a, b) => b.emergency_rate - a.emergency_rate)
  const maxVal = Math.max(...sorted.map(d => d.emergency_rate || 0))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 4, right: 50, top: 6, bottom: 2, containLabel: true },
    xAxis: { type: 'value', show: false, min: 0, max: maxVal * 1.2 },
    yAxis: {
      type: 'category',
      data: sorted.map(d => d.area?.substring(0, 10) || ''),
      ...axisStyle,
      axisLabel: { color: '#a8c5f0', fontSize: 11 }
    },
    series: [{
      type: 'bar',
      data: sorted.map(d => ({ value: d.emergency_rate || 0, itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#0d47a1' }, { offset: 1, color: '#00e5ff' }]) } })),
      barWidth: 16,
      itemStyle: {
        borderRadius: [0, 2, 2, 0]
      },
      label: {
        show: true, position: 'right',
        color: '#a8c5f0', fontSize: 11,
        formatter: p => (p.value || 0) + '%'
      }
    }]
  })
  charts.push(chart)
}

function initAll() {
  charts.forEach(c => c.dispose())
  charts = []
  nextTick(() => {
    initDiseaseChart()
    initAgeChart()
    initEmergencyChart()
  })
}

const resizeHandler = () => charts.forEach(c => c.resize())

watch(() => [props.topDiseases, props.ageDistribution, props.serviceAreas], initAll, { deep: true })

onMounted(() => {
  initAll()
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeHandler)
  charts.forEach(c => c.dispose())
})
</script>

<style scoped>
.panel-left {
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
</style>
