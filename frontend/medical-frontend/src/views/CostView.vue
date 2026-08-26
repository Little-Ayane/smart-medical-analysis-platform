<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>💰 费用成本分析</h2>
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
  { key: 'profit-difference', label: '💸 费用成本差' },
  { key: 'profit-margin', label: '📈 利润率' },
  { key: 'efficiency', label: '🏆 成本效益' },
  { key: 'composition', label: '🧩 费用构成' },
  { key: 'trend', label: '📊 年度趋势' }
]

const activeTab = ref('profit-difference')
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
      case 'profit-difference':
        result = await api.getCostProfitDifference({ dimension: 'diagnosis', top: 10 })
        break
      case 'profit-margin':
        result = await api.getCostProfitMargin({ dimension: 'diagnosis', top: 10, order: 'desc' })
        break
      case 'efficiency':
        result = await api.getCostEfficiencyRanking({ dimension: 'diagnosis', top: 15 })
        break
      case 'composition':
        result = await api.getCostComposition({ dimension: 'mdc', top: 10 })
        break
      case 'trend':
        result = await api.getCostTrendApi({ start_year: 2020, end_year: 2024 })
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

    if (!data || data.length === 0) {
      chartInstance.setOption({ title: { text: '暂无数据', left: 'center', top: 'center' } })
      return
    }

    let option = {}
    if (tabKey === 'profit-difference') {
      const names = data.map(d => d.key?.slice(0, 20) || '未知')
      const values = data.map(d => d.value || 0)
      const colors = values.map(v => v > 0 ? '#2ECC71' : '#E74C3C')
      option = {
        tooltip: { trigger: 'axis', formatter: (p) => `${p[0].name}<br/>费用成本差: ¥${p[0].value?.toLocaleString()}` },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 20, fontSize: 9 } },
        yAxis: { type: 'value', name: '费用成本差 (元)' },
        series: [{ type: 'bar', data: data.map((d, i) => ({ value: d.value, itemStyle: { color: colors[i] } })), borderRadius: [4,4,0,0] }]
      }
    } else if (tabKey === 'profit-margin') {
      const names = data.map(d => d.key?.slice(0, 20) || '未知')
      const values = data.map(d => d.value || 0)
      const colors2 = values.map(v => v > 15 ? '#2ECC71' : v > 10 ? '#F5A623' : '#E74C3C')
      option = {
        tooltip: { trigger: 'axis', formatter: (p) => `${p[0].name}<br/>利润率: ${p[0].value}%` },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 20, fontSize: 9 } },
        yAxis: { type: 'value', name: '利润率 (%)' },
        series: [{ type: 'bar', data: data.map((d, i) => ({ value: d.value, itemStyle: { color: colors2[i] } })), borderRadius: [4,4,0,0], label: { show: true, position: 'top', formatter: (p) => p.value + '%' } }]
      }
    } else if (tabKey === 'efficiency') {
      const names = data.map(d => d.key?.slice(0, 20) || '未知')
      const values = data.map(d => d.value || 0)
      const grades = data.map(d => d.efficiency_grade || '')
      const colors3 = grades.map(g => g.includes('A') ? '#2ECC71' : g.includes('B') ? '#F5A623' : g.includes('C') ? '#E67E22' : '#E74C3C')
      option = {
        tooltip: { trigger: 'axis', formatter: (p) => `${p[0].name}<br/>利润率: ${p[0].value}%<br/>等级: ${grades[p[0].dataIndex]}` },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 20, fontSize: 9 } },
        yAxis: { type: 'value', name: '利润率 (%)' },
        series: [{ type: 'bar', data: data.map((d, i) => ({ value: d.value, itemStyle: { color: colors3[i] } })), borderRadius: [4,4,0,0], label: { show: true, position: 'top', formatter: (p) => p.value + '%' } }]
      }
    } else if (tabKey === 'composition') {
      const pieData = data.map(d => ({ name: d.key?.slice(0, 30) || '未知', value: d.value || 0 }))
      option = {
        tooltip: { trigger: 'item', formatter: (p) => `${p.name}<br/>占比: ${p.percent}%<br/>费用: ¥${p.value?.toLocaleString()}` },
        series: [{ type: 'pie', radius: ['40%', '70%'], center: ['50%', '55%'], data: pieData, label: { formatter: '{b}\n{d}%' }, itemStyle: { borderRadius: 6 } }]
      }
    } else if (tabKey === 'trend') {
      const years = data.map(d => d.year)
      const charges = data.map(d => d.total_charges || 0)
      const costs = data.map(d => d.total_costs || 0)
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '14%' },
        xAxis: { type: 'category', data: years, name: '年份' },
        yAxis: { type: 'value', name: '费用 (元)' },
        series: [
          { type: 'line', name: '总费用', data: charges, smooth: true, lineStyle: { color: '#00d4ff', width: 3 }, areaStyle: { opacity: 0.2 }, symbol: 'circle', symbolSize: 8 },
          { type: 'line', name: '总成本', data: costs, smooth: true, lineStyle: { color: '#F5A623', width: 3 }, areaStyle: { opacity: 0.1 }, symbol: 'diamond', symbolSize: 8 }
        ]
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