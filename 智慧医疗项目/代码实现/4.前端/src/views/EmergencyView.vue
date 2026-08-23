<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>🚑 急诊与效率分析</h2>
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
  { key: 'emergency-rate', label: '📈 急诊率趋势' },
  { key: 'emergency-compare', label: '⚖️ 急诊对比' },
  { key: 'avg-los', label: '📊 平均住院日' },
  { key: 'outliers', label: '🚨 超标识别' },
  { key: 'disposition-cross', label: '🔄 转归×急诊交叉' }
]

const activeTab = ref('emergency-rate')
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
      case 'emergency-rate':
        result = await api.getEmergencyRate()
        break
      case 'emergency-compare':
        result = await api.getEmergencyCompare()
        break
      case 'avg-los':
        result = await api.getAvgLos({ group_by: 'age_group' })
        break
      case 'outliers':
        result = await api.getOutliers({ los_threshold: 30, charge_threshold: 500000 })
        break
      case 'disposition-cross':
        result = await api.getDispositionEmergencyCross()
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

    if (data.length === 0) {
      chartInstance.setOption({ title: { text: '暂无数据', left: 'center', top: 'center' } })
      return
    }

    let option = {}
    if (tabKey === 'emergency-rate') {
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '14%' },
        xAxis: { type: 'category', data: data.map(d => d.year), name: '年份' },
        yAxis: { type: 'value', name: '急诊占比 (%)', min: 0, max: 30 },
        series: [{
          type: 'line',
          data: data.map(d => d.emergency_rate),
          smooth: true,
          lineStyle: { color: '#E74C3C', width: 3 },
          areaStyle: { opacity: 0.2 },
          symbol: 'circle',
          symbolSize: 8,
          label: { show: true, formatter: (p) => p.value + '%' }
        }]
      }
    } else if (tabKey === 'emergency-compare') {
      const categories = data.map(d => d.is_emergency === 'Y' ? '急诊' : '非急诊')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '14%' },
        xAxis: { type: 'category', data: categories, name: '入院方式' },
        yAxis: [
          { type: 'value', name: '平均住院日 (天)' },
          { type: 'value', name: '平均费用 (千元)' }
        ],
        series: [
          { type: 'bar', name: '平均住院日', data: data.map(d => d.avg_los), itemStyle: { color: '#3498DB' }, yAxisIndex: 0 },
          { type: 'bar', name: '平均费用 (千元)', data: data.map(d => d.avg_charges / 1000), itemStyle: { color: '#F39C12' }, yAxisIndex: 1 }
        ]
      }
    } else if (tabKey === 'avg-los') {
      const colors = data.map(d => d.avg_los > 6 ? '#E74C3C' : d.avg_los > 4 ? '#F39C12' : '#2ECC71')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: data.map(d => d.key), axisLabel: { rotate: 20 } },
        yAxis: { type: 'value', name: '平均住院日 (天)' },
        series: [{
          type: 'bar',
          data: data.map((d, i) => ({ value: d.avg_los, itemStyle: { color: colors[i] } })),
          borderRadius: [4,4,0,0],
          label: { show: true, position: 'top' }
        }]
      }
    } else if (tabKey === 'outliers') {
      const names = data.map(d => d.facility_name || '未知医院')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '8%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 30, interval: 0, fontSize: 10 } },
        yAxis: [
          { type: 'value', name: '住院日 (天)' },
          { type: 'value', name: '费用 (万元)' }
        ],
        series: [
          { type: 'bar', name: '住院日', data: data.map(d => d.length_of_stay), itemStyle: { color: '#E74C3C' }, yAxisIndex: 0 },
          { type: 'bar', name: '费用 (万元)', data: data.map(d => d.total_charges / 10000), itemStyle: { color: '#F39C12' }, yAxisIndex: 1 }
        ]
      }
    } else if (tabKey === 'disposition-cross') {
      const dispositions = [...new Set(data.map(d => d.patient_disposition))]
      const emergencyData = data.filter(d => d.is_emergency === 'Y')
      const nonEmergencyData = data.filter(d => d.is_emergency === 'N')
      const emergencyCounts = dispositions.map(d => emergencyData.find(x => x.patient_disposition === d)?.cnt || 0)
      const nonEmergencyCounts = dispositions.map(d => nonEmergencyData.find(x => x.patient_disposition === d)?.cnt || 0)
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: dispositions, axisLabel: { rotate: 20, interval: 0 } },
        yAxis: { type: 'value', name: '病例数' },
        series: [
          { type: 'bar', name: '急诊', data: emergencyCounts, stack: 'total', itemStyle: { color: '#E74C3C' } },
          { type: 'bar', name: '非急诊', data: nonEmergencyCounts, stack: 'total', itemStyle: { color: '#3498DB' } }
        ]
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
    chartInstance.setOption({
      title: { text: '❌ 数据加载失败，请检查后端服务', left: 'center', top: 'center' }
    })
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
.page-header h2 {
  font-size: 22px;
  color: #fff;
}
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
.back-btn:hover {
  background: rgba(0,212,255,0.1);
  border-color: rgba(0,212,255,0.2);
  color: #fff;
}

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
.tab-btn:hover {
  background: rgba(255,255,255,0.08);
  border-color: rgba(255,255,255,0.15);
  color: #fff;
}
.tab-btn.active {
  background: rgba(0,212,255,0.12);
  border-color: rgba(0,212,255,0.25);
  color: #00d4ff;
}

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
.chart-container {
  width: 100%;
  height: 400px;
}
.chart-foot {
  margin-top: 10px;
  font-size: 12px;
  color: #5a7a8a;
  text-align: right;
  border-top: 1px solid rgba(255,255,255,0.06);
  padding-top: 8px;
}
</style>