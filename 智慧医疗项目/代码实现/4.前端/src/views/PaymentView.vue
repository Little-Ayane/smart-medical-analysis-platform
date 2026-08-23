<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>🧾 支付结构分析</h2>
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
  { key: 'composition', label: '🧩 支付构成' },
  { key: 'cross', label: '📊 支付交叉' },
  { key: 'sankey', label: '🌊 桑葚图' },
  { key: 'cost-relation', label: '💹 费用关系' },
  { key: 'oop-burden', label: '💳 自付负担' },
  { key: 'summary', label: '📋 KPI总览' }
]

const activeTab = ref('composition')
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
      case 'composition':
        result = await api.getPaymentComposition({ group: 'payment1', metric: 'count' })
        break
      case 'cross':
        result = await api.getPaymentCross({ dim2: 'age_group', metric: 'count', top: 10 })
        break
      case 'sankey':
        result = await api.getPaymentSankey({ levels: 'payment,payment2' })
        break
      case 'cost-relation':
        result = await api.getPaymentCostRelation({ by: 'payment', top: 20 })
        break
      case 'oop-burden':
        result = await api.getPaymentOopBurden({ dimension: 'age_group', mode: 'selfpay1', top: 10 })
        break
      case 'summary':
        result = await api.getPaymentSummary()
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
    if (tabKey === 'composition') {
      const pieData = data.map(d => ({ name: d.key, value: d.value || d.count || 0 }))
      option = {
        tooltip: { trigger: 'item' },
        series: [{ type: 'pie', radius: ['40%', '70%'], center: ['50%', '55%'], data: pieData, label: { formatter: '{b}\n{d}%' }, itemStyle: { borderRadius: 6 } }]
      }
    } else if (tabKey === 'cross') {
      const keys = [...new Set(data.map(d => d.key))]
      const dim2s = [...new Set(data.map(d => d.dim2_name || d.dim2))]
      const colors = ['#00d4ff', '#7b61ff', '#2ECC71', '#F5A623', '#E74C3C']
      const series = dim2s.map((s, i) => ({
        type: 'bar',
        name: s,
        stack: 'cross',
        data: keys.map(k => data.find(d => d.key === k && (d.dim2_name || d.dim2) === s)?.value || 0),
        itemStyle: { color: colors[i % colors.length] }
      }))
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '6%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: keys, axisLabel: { rotate: 15, fontSize: 10 } },
        yAxis: { type: 'value', name: '人数' },
        legend: { top: 0, data: dim2s, textStyle: { color: '#8ab4d6' } },
        series
      }
    } else if (tabKey === 'sankey') {
      const sankeyData = data
      const nodes = sankeyData.nodes || []
      const links = sankeyData.links || []
      option = {
        tooltip: { trigger: 'item' },
        series: [{ type: 'sankey', data: nodes, links: links, lineStyle: { color: 'gradient', curveness: 0.5 }, label: { fontSize: 10 } }]
      }
    } else if (tabKey === 'cost-relation') {
      option = {
        tooltip: { trigger: 'item', formatter: (p) => `${p.name}<br/>费用: ${p.data[1]}<br/>成本: ${p.data[0]}<br/>比值: ${p.data[2]}` },
        grid: { left: '8%', right: '4%', top: '8%', bottom: '14%' },
        xAxis: { type: 'value', name: '平均成本' },
        yAxis: { type: 'value', name: '平均费用' },
        series: [{
          type: 'scatter',
          data: data.map(d => ({
            value: [d.avg_costs, d.avg_charges, d.charge_cost_ratio || 0],
            name: d.key
          })),
          symbolSize: 20,
          label: { show: true, formatter: '{b}', fontSize: 9, position: 'top' }
        }]
      }
    } else if (tabKey === 'oop-burden') {
      const keys = data.map(d => d.key)
      const pcts = data.map(d => d.self_pay_pct || 0)
      const colors2 = pcts.map(v => v > 2 ? '#E74C3C' : v > 1.5 ? '#F5A623' : '#2ECC71')
      option = {
        tooltip: { trigger: 'axis' },
        grid: { left: '8%', right: '4%', top: '8%', bottom: '18%' },
        xAxis: { type: 'category', data: keys, axisLabel: { rotate: 15, fontSize: 10 } },
        yAxis: { type: 'value', name: '自付占比 (%)' },
        series: [{
          type: 'bar',
          data: data.map((d, i) => ({ value: d.self_pay_pct || 0, itemStyle: { color: colors2[i] } })),
          borderRadius: [4,4,0,0],
          label: { show: true, position: 'top', formatter: (p) => p.value + '%' }
        }]
      }
    } else if (tabKey === 'summary') {
      const d = data
      const sevData = Object.entries(d.severity_distribution || {}).map(([k, v]) => ({ name: k, value: v }))
      option = {
        title: { text: 'KPI总览', textStyle: { color: '#fff', fontSize: 18 }, left: 'center', top: 0 },
        tooltip: { trigger: 'item' },
        grid: { left: '6%', right: '4%', top: '16%', bottom: '10%' },
        series: [{ type: 'pie', radius: ['30%', '55%'], center: ['50%', '55%'], data: sevData, label: { formatter: '{b}\n{d}%' }, itemStyle: { borderRadius: 6 } }]
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