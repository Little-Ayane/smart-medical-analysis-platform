<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>📊 疾病谱分析</h2>
      <span></span>
    </div>

    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key; loadData(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div v-if="loading" class="loading-mask">⏳ 加载中...</div>
    <div v-else class="page-body">
      <div ref="chartRef" class="chart-container"></div>
      <div class="chart-foot" v-if="metaInfo">
        📊 共 {{ metaInfo.total_records || 0 }} 条记录 · 耗时 {{ metaInfo.query_ms || 0 }} ms
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import api from '@/api'
import { AGE_GROUP, GENDER, SEVERITY, t } from '@/utils/labels'

const tabs = [
  { key: 'top-diagnoses', label: '📊 Top诊断排行' },
  { key: 'top-procedures', label: '🔬 手术谱排行' },
  { key: 'severity-profile', label: '📈 病重程度构成' },
  { key: 'population-diff', label: '👥 人群差异' },
  { key: 'pyramid', label: '📐 人口金字塔' },
  { key: 'region-diff', label: '📍 地区差异' },
  { key: 'heatmap', label: '🔥 热力图' }
]

const activeTab = ref('top-diagnoses')
const chartRef = ref(null)
const loading = ref(false)
const metaInfo = ref(null)
let chartInstance = null

const loadData = async (tabKey) => {
  loading.value = true
  metaInfo.value = null
  try {
    let result
    switch (tabKey) {
      case 'top-diagnoses':
        result = await api.getTopDiagnoses({ metric: 'count', top: 10 })
        break
      case 'top-procedures':
        result = await api.getTopProcedures({ metric: 'count', top: 10 })
        break
      case 'severity-profile':
        result = await api.getSeverityProfile({ by: 'age_group', metric: 'count' })
        break
      case 'population-diff':
        result = await api.getPopulationDiff({ dimension: 'gender', metric: 'count' })
        break
      case 'pyramid':
        result = await api.getPyramid()
        break
      case 'region-diff':
        result = await api.getRegionDiff({ level: 'service_area', metric: 'count' })
        break
      case 'heatmap':
        result = await api.getHeatmap({ dim1: 'diagnosis', dim2: 'age_group', top: 10 })
        break
      default:
        return
    }
    const data = result.data || []
    metaInfo.value = result.meta || null
    loading.value = false

    await nextTick()
    if (!chartRef.value) return
    if (chartInstance) chartInstance.dispose()
    chartInstance = echarts.init(chartRef.value, 'medical')

    if (data.length === 0) {
      chartInstance.setOption({ title: { text: '暂无数据', left: 'center', top: 'center' } })
      return
    }

    let option = {}
    if (tabKey === 'top-diagnoses') {
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: data.map(d => d.name), axisLabel: { rotate: 20, fontSize: 10 } },
        yAxis: { type: 'value', name: '住院人次' },
        series: [{ type: 'bar', data: data.map(d => d.value), itemStyle: { color: '#4A90D9', borderRadius: [4,4,0,0] } }]
      }
    } else if (tabKey === 'top-procedures') {
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: data.map(d => d.name), axisLabel: { rotate: 20, fontSize: 10 } },
        yAxis: { type: 'value', name: '手术量' },
        series: [{ type: 'bar', data: data.map(d => d.value), itemStyle: { color: '#F5A623', borderRadius: [4,4,0,0] } }]
      }
    } else if (tabKey === 'severity-profile') {
      const groups = [...new Set(data.map(d => d.group))]
      const severities = ['Minor', 'Moderate', 'Major', 'Extreme', 'Unknown']
      const severityLabels = severities.map(s => t(SEVERITY, s))
      const colors = ['#2ECC71', '#F5A623', '#E67E22', '#E74C3C', '#95A5A6']
      const series = severities.map((s, i) => ({
        type: 'bar',
        name: severityLabels[i],
        stack: 'severity',
        data: groups.map(g => data.find(d => d.group === g && d.severity === s)?.value || 0),
        itemStyle: { color: colors[i] }
      }))
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: groups.map(g => t(AGE_GROUP, g)), axisLabel: { rotate: 15 } },
        yAxis: { type: 'value', name: '人数' },
        legend: { top: 0, data: severityLabels, textStyle: { color: '#8ab4d6' } },
        series
      }
    } else if (tabKey === 'population-diff') {
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '14%' },
        xAxis: { type: 'category', data: data.map(d => t(GENDER, d.key)), name: '分组' },
        yAxis: { type: 'value', name: '人数' },
        series: [{ type: 'bar', data: data.map(d => d.value), itemStyle: { color: '#3498DB', borderRadius: [4,4,0,0] } }]
      }
    } else if (tabKey === 'pyramid') {
      const ageGroups = data.map(d => t(AGE_GROUP, d.age_group))
      const maleData = data.map(d => -d.male)
      const femaleData = data.map(d => d.female)
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '8%', right: '4%', top: '8%', bottom: '14%' },
        xAxis: { type: 'value', name: '人数' },
        yAxis: { type: 'category', data: ageGroups, axisLabel: { fontSize: 11 } },
        series: [
          { type: 'bar', name: '男', data: maleData, itemStyle: { color: '#3498DB' }, label: { show: true, position: 'left', formatter: (p) => Math.abs(p.value) } },
          { type: 'bar', name: '女', data: femaleData, itemStyle: { color: '#E74C3C' }, label: { show: true, position: 'right' } }
        ]
      }
    } else if (tabKey === 'region-diff') {
      const names = data.map(d => d.key).slice(0, 10)
      const values = data.map(d => d.value).slice(0, 10)
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '8%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 20, fontSize: 10 } },
        yAxis: { type: 'value', name: '人数' },
        series: [{ type: 'bar', data: values, itemStyle: { color: '#9B59B6', borderRadius: [4,4,0,0] } }]
      }
    } else if (tabKey === 'heatmap') {
      const dim1s = [...new Set(data.map(d => d.dim1_name || d.dim1))]
      const dim2s = [...new Set(data.map(d => d.dim2_name || d.dim2))]
      const dim2Labels = dim2s.map(v => t(AGE_GROUP, v))
      const seriesData = data.map(d => {
        const x = dim1s.indexOf(d.dim1_name || d.dim1)
        const y = dim2s.indexOf(d.dim2_name || d.dim2)
        return [x, y, d.value || 0]
      })
      const maxVal = Math.max(...seriesData.map(d => d[2]), 1)
      option = {
        tooltip: { position: 'top' },
        grid: { left: '10%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: dim1s, axisLabel: { rotate: 30, fontSize: 9 } },
        yAxis: { type: 'category', data: dim2Labels },
        visualMap: { min: 0, max: maxVal, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#0a1628', '#00d4ff', '#7b61ff'] } },
        series: [{ type: 'heatmap', data: seriesData, label: { show: false } }]
      }
    }

    chartInstance.setOption(option)
    chartInstance.resize()
  } catch (err) {
    console.error('加载失败:', err)
    loading.value = false
    await nextTick()
    if (!chartRef.value) return
    if (chartInstance) chartInstance.dispose()
    chartInstance = echarts.init(chartRef.value, 'medical')
    chartInstance.setOption({ title: { text: '❌ 数据加载失败，请检查后端服务', left: 'center', top: 'center' } })
  } finally {
    loading.value = false
  }
}

const onResize = () => { if (chartInstance) chartInstance.resize() }

onMounted(() => {
  loadData(activeTab.value)
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (chartInstance) chartInstance.dispose()
})
</script>

<style scoped>
.page {
  padding: 24px 32px 20px;
  background: #0a1628;
  min-height: 100vh;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1000px;
  margin: 0 auto 16px;
}
.page-header h2 { font-size: 22px; color: #fff; }
.back-btn {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  padding: 6px 18px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #8ab4d6;
  transition: all 0.3s;
}
.back-btn:hover { background: rgba(0,212,255,0.1); border-color: rgba(0,212,255,0.2); color: #fff; }

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-width: 1000px;
  margin: 0 auto 16px;
}
.tab-btn {
  padding: 8px 20px;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px;
  background: rgba(255,255,255,0.04);
  color: #8ab4d6;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}
.tab-btn:hover { background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.15); color: #fff; }
.tab-btn.active { background: rgba(0,212,255,0.12); border-color: rgba(0,212,255,0.25); color: #00d4ff; }

.loading-mask {
  max-width: 1000px;
  margin: 0 auto;
  text-align: center;
  padding: 60px 0;
  font-size: 18px;
  color: #8ab4d6;
}
.page-body {
  max-width: 1000px;
  margin: 0 auto;
  background: rgba(10,22,40,0.6);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(0,212,255,0.12);
  border-radius: 12px;
  padding: 20px 24px;
  box-shadow: 0 0 40px rgba(0,212,255,0.04);
}
.chart-container { width: 100%; height: 400px; }
.chart-foot {
  margin-top: 10px;
  font-size: 12px;
  color: #5a7a8a;
  text-align: right;
  border-top: 1px solid rgba(255,255,255,0.06);
  padding-top: 8px;
}
</style>