<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>🏥 医院横向对比</h2>
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
import { RISK_MORTALITY, t } from '@/utils/labels'

const tabs = [
  { key: 'cost-ranking', label: '💰 费用排名' },
  { key: 'stay-comparison', label: '📆 住院天数' },
  { key: 'mortality-risk', label: '💀 死亡风险' },
  { key: 'cmi-ranking', label: '📊 CMI排名' },
  { key: 'outlier', label: '🚨 离群识别' },
  { key: 'summary', label: '📋 DRG汇总' }
]

const activeTab = ref('cost-ranking')
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
      case 'cost-ranking':
        result = await api.getDrgCostRankingApi({ limit: 10, sort_by: 'avg_charges', sort_order: 'desc' })
        break
      case 'stay-comparison':
        result = await api.getDrgStayComparison({ group_by: 'drg', limit: 10 })
        break
      case 'mortality-risk':
        result = await api.getDrgMortalityRisk({ group_by: 'risk_mortality' })
        break
      case 'cmi-ranking':
        result = await api.getDrgCmiRanking({ group_by: 'drg', limit: 10, sort_order: 'desc' })
        break
      case 'outlier':
        result = await api.getDrgOutlierDetection({ metric: 'avg_charges', group_by: 'drg', method: 'iqr', threshold: 1.5, limit: 20 })
        break
      case 'summary':
        result = await api.getDrgSummary()
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

    const rows = data.rows || data || []
    if (rows.length === 0) {
      chartInstance.setOption({ title: { text: '暂无数据', left: 'center', top: 'center' } })
      return
    }

    let option = {}
    if (tabKey === 'cost-ranking') {
      const names = rows.map(d => d.drg_desc?.slice(0, 20) || d.drg_code)
      const values = rows.map(d => d.avg_charges || 0)
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 25, fontSize: 9 } },
        yAxis: { type: 'value', name: '平均费用 (元)' },
        series: [{ type: 'bar', data: values, itemStyle: { color: '#F5A623', borderRadius: [4,4,0,0] } }]
      }
    } else if (tabKey === 'stay-comparison') {
      const names = rows.map(d => d.drg_desc?.slice(0, 20) || d.drg_code)
      const values = rows.map(d => d.avg_stay || 0)
      const colors = values.map(v => v > 7 ? '#E74C3C' : v > 5 ? '#F5A623' : '#2ECC71')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 25, fontSize: 9 } },
        yAxis: { type: 'value', name: '平均住院日 (天)' },
        series: [{
          type: 'bar',
          data: rows.map((d, i) => ({ value: d.avg_stay, itemStyle: { color: colors[i] } })),
          borderRadius: [4,4,0,0],
          label: { show: true, position: 'top' }
        }]
      }
    } else if (tabKey === 'mortality-risk') {
      const names = rows.map(d => t(RISK_MORTALITY, d.risk_mortality))
      const cases = rows.map(d => d.cases || 0)
      const pcts = rows.map(d => d.percentage || 0)
      const colors2 = ['#2ECC71', '#F5A623', '#E67E22', '#E74C3C']
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '14%' },
        xAxis: { type: 'category', data: names },
        yAxis: [
          { type: 'value', name: '病例数' },
          { type: 'value', name: '占比 (%)' }
        ],
        series: [
          { type: 'bar', name: '病例数', data: cases, itemStyle: { color: (p) => colors2[p.dataIndex % colors2.length] }, yAxisIndex: 0 },
          { type: 'line', name: '占比 (%)', data: pcts, lineStyle: { color: '#00d4ff', width: 2 }, yAxisIndex: 1, label: { show: true, formatter: (p) => p.value + '%' } }
        ]
      }
    } else if (tabKey === 'cmi-ranking') {
      const names = rows.map(d => d.drg_desc?.slice(0, 20) || d.drg_code)
      const cmi = rows.map(d => d.cmi || 0)
      const colors3 = cmi.map(v => v > 5 ? '#E74C3C' : v > 3 ? '#F5A623' : '#2ECC71')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names, axisLabel: { rotate: 25, fontSize: 9 } },
        yAxis: { type: 'value', name: 'CMI' },
        series: [{
          type: 'bar',
          data: rows.map((d, i) => ({ value: d.cmi, itemStyle: { color: colors3[i] } })),
          borderRadius: [4,4,0,0],
          label: { show: true, position: 'top' }
        }]
      }
    } else if (tabKey === 'outlier') {
      const outliers = rows.outliers || rows
      const names2 = outliers.map(d => d.drg_desc?.slice(0, 20) || d.drg_code)
      const values2 = outliers.map(d => d.avg_charges || 0)
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: names2, axisLabel: { rotate: 25, fontSize: 9 } },
        yAxis: { type: 'value', name: '费用 (元)' },
        series: [{ type: 'bar', data: values2, itemStyle: { color: '#E74C3C', borderRadius: [4,4,0,0] } }]
      }
    } else if (tabKey === 'summary') {
      const d = rows
      const summaryItems = [
        { name: 'DRG总数', value: d.total_drg || 0 },
        { name: '总病例', value: (d.total_cases || 0).toLocaleString() },
        { name: '总费用', value: '¥' + (d.total_charges || 0).toLocaleString() },
        { name: '平均住院日', value: (d.avg_stay || 0) + '天' }
      ]
      option = {
        title: { text: 'DRG汇总信息', textStyle: { color: '#fff', fontSize: 18 }, left: 'center', top: 0 },
        tooltip: { trigger: 'item' },
        grid: { left: '6%', right: '4%', top: '14%', bottom: '10%' },
        series: [{
          type: 'pie',
          radius: ['30%', '55%'],
          center: ['50%', '55%'],
          data: summaryItems,
          label: { formatter: '{b}\n{c}', fontSize: 12 },
          itemStyle: { borderRadius: 6 }
        }]
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