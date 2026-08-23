<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>📉 医疗质量监测</h2>
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

const tabs = [
  { key: 'overview', label: '📋 KPI总览' },
  { key: 'mortality', label: '💀 死亡率排行' },
  { key: 'los', label: '📊 住院日排行' },
  { key: 'facility', label: '🏥 医院质量对比' },
  { key: 'disposition', label: '🚪 离院去向' }
]

const activeTab = ref('overview')
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
      case 'overview':
        result = await api.getQualityOverview()
        break
      case 'mortality':
        result = await api.getQualityMortality({ dimension: 'diagnosis', top: 10, min_cases: 30 })
        break
      case 'los':
        result = await api.getQualityLos({ dimension: 'diagnosis', top: 10, min_cases: 30 })
        break
      case 'facility':
        result = await api.getQualityFacilityRanking({ top: 10, min_cases: 100 })
        break
      case 'disposition':
        result = await api.getQualityDisposition()
        break
      default:
        return
    }
    const data = result.data || []
    metaInfo.value = result.meta || null

    await nextTick()
    if (!chartRef.value) return
    if (chartInstance) chartInstance.dispose()
    chartInstance = echarts.init(chartRef.value)

    if (!data || (Array.isArray(data) && data.length === 0) || (typeof data === 'object' && !Array.isArray(data) && Object.keys(data).length === 0)) {
      chartInstance.setOption({ title: { text: '暂无数据', left: 'center', top: 'center' } })
      return
    }

    let option = {}
    if (tabKey === 'overview') {
      const d = data
      const kpiItems = [
        { label: '总出院', value: d.total_records?.toLocaleString() },
        { label: '死亡率', value: d.mortality_rate + '%' },
        { label: '平均住院日', value: d.avg_los + '天' },
        { label: '急诊率', value: d.ed_rate + '%' },
        { label: '非医嘱离院率', value: d.ama_rate + '%' },
        { label: '转院率', value: d.transfer_rate + '%' },
        { label: '低出生体重率', value: d.lbw_rate + '%' },
        { label: '次均费用', value: '¥' + (d.avg_charges || 0).toLocaleString() }
      ]
      const cardData = kpiItems.map(item => ({ name: item.label, value: item.value }))
      option = {
        title: { text: '质量KPI总览', textStyle: { color: '#fff', fontSize: 18 }, left: 'center', top: 0 },
        tooltip: { trigger: 'item' },
        grid: { left: '6%', right: '4%', top: '14%', bottom: '10%' },
        series: [{
          type: 'pie',
          radius: ['30%', '55%'],
          center: ['50%', '55%'],
          data: cardData,
          label: { formatter: '{b}\n{c}', fontSize: 11 },
          itemStyle: { borderRadius: 6 }
        }]
      }
    } else if (tabKey === 'mortality') {
      const names = data.map(d => d.name || d.key)
      const rates = data.map(d => d.mortality_rate)
      const colors = rates.map(v => v > 5 ? '#E74C3C' : v > 3 ? '#F5A623' : '#2ECC71')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 20, fontSize: 9 } },
        yAxis: { type: 'value', name: '死亡率 (%)' },
        series: [{
          type: 'bar',
          data: data.map((d, i) => ({ value: d.mortality_rate, itemStyle: { color: colors[i] } })),
          borderRadius: [4,4,0,0],
          label: { show: true, position: 'top', formatter: (p) => p.value + '%' }
        }]
      }
    } else if (tabKey === 'los') {
      const names = data.map(d => d.name || d.key)
      const los = data.map(d => d.avg_los)
      const colors2 = los.map(v => v > 7 ? '#E74C3C' : v > 5 ? '#F5A623' : '#2ECC71')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 20, fontSize: 9 } },
        yAxis: { type: 'value', name: '平均住院日 (天)' },
        series: [{
          type: 'bar',
          data: data.map((d, i) => ({ value: d.avg_los, itemStyle: { color: colors2[i] } })),
          borderRadius: [4,4,0,0],
          label: { show: true, position: 'top' }
        }]
      }
    } else if (tabKey === 'facility') {
      const names = data.map(d => d.name || d.key)
      const mortality = data.map(d => d.mortality_rate)
      const los2 = data.map(d => d.avg_los)
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '8%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 25, fontSize: 9 } },
        yAxis: [
          { type: 'value', name: '死亡率 (%)', min: 0, max: 5 },
          { type: 'value', name: '平均住院日 (天)', min: 0, max: 8 }
        ],
        series: [
          { type: 'bar', name: '死亡率', data: mortality, itemStyle: { color: '#E74C3C' }, yAxisIndex: 0 },
          { type: 'bar', name: '平均住院日', data: los2, itemStyle: { color: '#3498DB' }, yAxisIndex: 1 }
        ]
      }
    } else if (tabKey === 'disposition') {
      const pieData = data.map(d => ({ name: d.key, value: d.count || 0 }))
      option = {
        tooltip: { trigger: 'item' },
        series: [{
          type: 'pie',
          radius: ['40%', '70%'],
          center: ['50%', '55%'],
          data: pieData,
          label: { formatter: '{b}\n{d}%' },
          itemStyle: { borderRadius: 6 }
        }]
      }
    }

    chartInstance.setOption(option)
    chartInstance.resize()
  } catch (err) {
    console.error('加载失败:', err)
    await nextTick()
    if (!chartRef.value) return
    if (chartInstance) chartInstance.dispose()
    chartInstance = echarts.init(chartRef.value)
    chartInstance.setOption({ title: { text: '❌ 数据加载失败', left: 'center', top: 'center' } })
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