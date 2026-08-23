<template>
  <div class="dashboard">
    <!-- 顶部标题栏 -->
    <div class="header">
      <div style="display: flex; align-items: center; gap: 16px;">
        <!-- 左上角下拉菜单 -->
        <div class="dropdown" @mouseenter="menuOpen = true" @mouseleave="menuOpen = false">
          <button class="menu-btn">
            <span class="menu-icon">≡</span>
            <span class="menu-label">功能入口</span>
            <span class="menu-arrow" :class="{ open: menuOpen }">▾</span>
          </button>
          <transition name="menu-fade">
            <div v-show="menuOpen" class="menu-panel">
              <div class="menu-item" @click="goDrill">
                <span class="item-icon">📐</span>
                <div class="item-text">
                  <div class="item-title">多维下钻</div>
                  <div class="item-desc">按维度逐层展开分析</div>
                </div>
              </div>
              <div class="menu-item" @click="goAI">
                <span class="item-icon">🤖</span>
                <div class="item-text">
                  <div class="item-title">AI 助手</div>
                  <div class="item-desc">智能问答与数据解读</div>
                </div>
              </div>
            </div>
          </transition>
        </div>
        <div>
          <div class="title">NY 州医疗 discharge 星型数据大屏</div>
          <div class="subtitle">STAR SCHEMA · 2020 - 2024 · 10.38M RECORDS · 218 HOSPITALS</div>
        </div>
      </div>
      <div class="header-right">
        <div class="stat-item"><div class="num">{{ numRecords }}</div><div class="lbl">总记录数</div></div>
        <div class="stat-item"><div class="num">{{ numHospital }}</div><div class="lbl">医院数</div></div>
        <div class="stat-item"><div class="num">{{ numDiag }}</div><div class="lbl">诊断数</div></div>
        <div class="stat-item"><div class="num">{{ numYear }}</div><div class="lbl">年份数</div></div>
        <!-- 右上角下拉菜单：6 个图表模块 -->
        <div class="dropdown dropdown-right" @mouseenter="chartMenuOpen = true" @mouseleave="chartMenuOpen = false">
          <button class="menu-btn">
            <span class="menu-icon">▦</span>
            <span class="menu-label">图表模块</span>
            <span class="menu-arrow" :class="{ open: chartMenuOpen }">▾</span>
          </button>
          <transition name="menu-fade">
            <div v-show="chartMenuOpen" class="menu-panel menu-panel-right">
              <div class="menu-item" @click="goDisease">
                <span class="item-icon">🦠</span>
                <div class="item-text">
                  <div class="item-title">疾病谱分析</div>
                  <div class="item-desc">疾病类别 × 年份分布</div>
                </div>
              </div>
              <div class="menu-item" @click="goPayment">
                <span class="item-icon">💳</span>
                <div class="item-text">
                  <div class="item-title">支付结构</div>
                  <div class="item-desc">6 种支付方式占比</div>
                </div>
              </div>
              <div class="menu-item" @click="goHospital">
                <span class="item-icon">🏥</span>
                <div class="item-text">
                  <div class="item-title">医院对比</div>
                  <div class="item-desc">病例数 × 费用 × 住院日</div>
                </div>
              </div>
              <div class="menu-item" @click="goQuality">
                <span class="item-icon">⭐</span>
                <div class="item-text">
                  <div class="item-title">质量监测</div>
                  <div class="item-desc">医院等级质量评分</div>
                </div>
              </div>
              <div class="menu-item" @click="goEmergency">
                <span class="item-icon">🚑</span>
                <div class="item-text">
                  <div class="item-title">急诊效率</div>
                  <div class="item-desc">地区急诊占比趋势</div>
                </div>
              </div>
              <div class="menu-item" @click="goCost">
                <span class="item-icon">💰</span>
                <div class="item-text">
                  <div class="item-title">费用成本</div>
                  <div class="item-desc">总费用 vs 总成本对比</div>
                </div>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </div>

    <!-- 6 个图表 -->
    <div class="grid">
      <div class="card clickable" @click="goDisease">
        <div class="card-title">疾病谱分析 <span class="tag">BAR3D</span></div>
        <div class="chart-box" ref="chartDiseaseRef"></div>
      </div>
      <div class="card clickable" @click="goPayment">
        <div class="card-title">支付结构 <span class="tag">PIE 3D</span></div>
        <div class="chart-box" ref="chartPaymentRef"></div>
      </div>
      <div class="card clickable" @click="goHospital">
        <div class="card-title">医院对比 <span class="tag">SCATTER3D</span></div>
        <div class="chart-box" ref="chartHospitalRef"></div>
      </div>
      <div class="card clickable" @click="goQuality">
        <div class="card-title">质量监测 <span class="tag">SURFACE</span></div>
        <div class="chart-box" ref="chartQualityRef"></div>
      </div>
      <div class="card clickable" @click="goEmergency">
        <div class="card-title">急诊效率 <span class="tag">LINE</span></div>
        <div class="chart-box" ref="chartEmergencyRef"></div>
      </div>
      <div class="card clickable" @click="goCost">
        <div class="card-title">费用成本 <span class="tag">BAR3D MIX</span></div>
        <div class="chart-box" ref="chartCostRef"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import 'echarts-gl'

const router = useRouter()
const menuOpen = ref(false)
const chartMenuOpen = ref(false)
const goDisease  = () => { chartMenuOpen.value = false; router.push('/disease') }
const goPayment  = () => { chartMenuOpen.value = false; router.push('/payment') }
const goHospital = () => { chartMenuOpen.value = false; router.push('/hospital') }
const goQuality  = () => { chartMenuOpen.value = false; router.push('/quality') }
const goEmergency = () => { chartMenuOpen.value = false; router.push('/emergency') }
const goCost     = () => { chartMenuOpen.value = false; router.push('/cost') }
const goDrill    = () => { menuOpen.value = false; router.push('/drill') }
const goAI       = () => { menuOpen.value = false; router.push('/ai') }

const chartDiseaseRef   = ref(null)
const chartPaymentRef    = ref(null)
const chartHospitalRef   = ref(null)
const chartQualityRef    = ref(null)
const chartEmergencyRef  = ref(null)
const chartCostRef       = ref(null)

const numRecords  = ref('0')
const numHospital = ref('0')
const numDiag     = ref('0')
const numYear     = ref('0')

let charts = []
let resizeHandler = null

const YEARS = ['2020', '2021', '2022', '2023', '2024']

/* 简化的 3D 轴样式（去掉过重的 postEffect，防止 WebGL 上下文崩溃） */
function makeAxis3D(name) {
  return {
    name,
    nameTextStyle: { color: '#7da3d4', fontSize: 11 },
    axisLine: { lineStyle: { color: 'rgba(64,196,255,0.5)' } },
    axisLabel: { color: '#a8c5f0', fontSize: 10 },
    splitLine: { lineStyle: { color: 'rgba(64,196,255,0.15)' } },
    axisTick: { lineStyle: { color: 'rgba(64,196,255,0.3)' } }
  }
}
function makeGrid3D(autoRotateSpeed = 8, opts = {}) {
  return Object.assign({
    boxWidth: 100, boxDepth: 75, boxHeight: 60,
    viewControl: {
      autoRotate: true,
      autoRotateSpeed,
      autoRotateAfterStill: 0,
      distance: 200,
      alpha: 18,
      beta: 40
    },
    light: {
      main:    { intensity: 1.2, shadow: false, alpha: 30, beta: 40 },
      ambient: { intensity: 0.5 }
    },
    environment: 'none'
  }, opts)
}

/* ========== 1. 疾病谱分析 —— bar3D ========== */
function initDisease() {
  const CAT = ['循环系统', '呼吸系统', '消化系统', '肿瘤', '损伤中毒', '内分泌', '神经系统', '泌尿生殖']
  const base = [2400, 1800, 1300, 1500, 1100, 900, 800, 1000]
  const data = []
  YEARS.forEach((y, yi) => {
    CAT.forEach((c, ci) => {
      const g = 1 + yi * 0.04
      const w = Math.sin(yi + ci) * 0.1 + 1
      data.push([yi, ci, Math.round(base[ci] * g * w)])
    })
  })
  const chart = echarts.init(chartDiseaseRef.value)
  chart.setOption({
    tooltip: { show: false },
    visualMap: { show: false, max: 3200, min: 0,
      inRange: { color: ['#0d47a1', '#1976d2', '#40c4ff', '#00e5ff', '#ffd740'] } },
    xAxis3D: makeAxis3D('年份'),
    yAxis3D: makeAxis3D('疾病类别'),
    zAxis3D: makeAxis3D('病例数(千)'),
    grid3D: makeGrid3D(7),
    series: [{
      type: 'bar3D', shading: 'lambert', data,
      label: { show: false },
      emphasis: { label: { show: false }, itemStyle: { color: '#00e5ff' } }
    }]
  })
  charts.push(chart)
}

/* ========== 2. 支付结构 —— 3D 风格饼图（多层环+阴影立体感） ========== */
function initPayment() {
  const data = [
    { value: 38, name: '联邦医保',     itemStyle: { color: '#00e5ff' } },
    { value: 25, name: '州医疗补助',   itemStyle: { color: '#40c4ff' } },
    { value: 18, name: '商业保险',     itemStyle: { color: '#7c4dff' } },
    { value: 10, name: '蓝十字保险',   itemStyle: { color: '#ffd740' } },
    { value: 5,  name: '自费',         itemStyle: { color: '#ff5252' } },
    { value: 4,  name: '其他',         itemStyle: { color: '#69f0ae' } }
  ]
  const chart = echarts.init(chartPaymentRef.value)
  chart.setOption({
    tooltip: { show: false },
    legend: {
      orient: 'vertical', right: 8, top: 'center',
      textStyle: { color: '#a8c5f0', fontSize: 10 },
      itemWidth: 8, itemHeight: 8
    },
    series: [
      // 外层光晕环
      {
        type: 'pie', radius: ['62%', '70%'], center: ['40%', '52%'],
        silent: true,
        label: { show: false },
        data: data.map(d => ({ value: d.value, itemStyle: { color: d.itemStyle.color, opacity: 0.15 } })),
        animationType: 'scale'
      },
      // 主饼（带阴影立体感）
      {
        type: 'pie', radius: ['30%', '60%'], center: ['40%', '52%'],
        roseType: 'radius',
        label: {
          color: '#e3f2fd', fontSize: 11,
          formatter: '{b}\n{d}%'
        },
        labelLine: { lineStyle: { color: 'rgba(64,196,255,0.5)' }, length: 8, length2: 10 },
        itemStyle: {
          borderColor: '#0a2a5e', borderWidth: 2,
          shadowBlur: 25,
          shadowColor: 'rgba(0,229,255,0.6)'
        },
        // hover 高亮：选中扇形放大、强发光，其他扇形变暗
        emphasis: {
          scale: true,
          scaleSize: 14,
          label: {
            show: true,
            fontSize: 13,
            fontWeight: 'bold',
            color: '#ffffff',
            textShadowColor: '#00e5ff',
            textShadowBlur: 10
          },
          itemStyle: {
            shadowBlur: 35,
            shadowColor: 'rgba(0,229,255,0.95)',
            borderColor: '#00e5ff',
            borderWidth: 2
          }
        },
        // 非选中扇形自动变暗（echarts 默认行为）
        blur: {
          itemStyle: {
            opacity: 0.25,
            shadowBlur: 0
          },
          label: { show: false }
        },
        data,
        animationType: 'expansion',
        animationEasing: 'elasticOut'
      }
    ]
  })
  charts.push(chart)
}

/* ========== 3. 医院对比 —— scatter3D ========== */
function initHospital() {
  const data = []
  for (let i = 0; i < 80; i++) {
    const area   = i % 7
    const cases  = 2000 + Math.floor(Math.random() * 45000)
    const charge = 8000 + Math.floor(Math.random() * 42000)
    const los    = 2 + Math.random() * 6
    data.push([cases, charge, +los.toFixed(1), area])
  }
  const chart = echarts.init(chartHospitalRef.value)
  chart.setOption({
    tooltip: { show: false },
    visualMap: { show: false, min: 0, max: 7,
      inRange: { color: ['#00e5ff','#40c4ff','#7c4dff','#ffd740','#ff5252','#69f0ae','#ff80ab'] } },
    xAxis3D: Object.assign(makeAxis3D('病例数'), { nameGap: 25 }),
    yAxis3D: Object.assign(makeAxis3D('平均费用($)'), { nameGap: 25 }),
    zAxis3D: makeAxis3D('住院天数'),
    grid3D: makeGrid3D(6, {
      viewControl: { autoRotate: true, autoRotateSpeed: 6, distance: 190, alpha: 15, beta: 35 }
    }),
    series: [{
      type: 'scatter3D', data,
      symbolSize: d => Math.sqrt(d[0]) / 20 + 3,
      shading: 'color',
      itemStyle: { borderColor: '#ffffff', borderWidth: 0.5, opacity: 0.85 },
      label: { show: false }
    }]
  })
  charts.push(chart)
}

/* ========== 4. 质量监测 —— surface ========== */
function initQuality() {
  const GRADES = ['A', 'B', 'C', 'D', 'E', 'F']
  const data = []
  for (let xi = 0; xi < 5; xi++) {
    for (let yi = 0; yi < 6; yi++) {
      const base = 95 - yi * 7
      const wave = Math.sin(xi * 0.8) * 3
      data.push([xi, yi, base + wave + Math.random() * 2])
    }
  }
  const chart = echarts.init(chartQualityRef.value)
  chart.setOption({
    tooltip: { show: false },
    visualMap: { show: false, min: 55, max: 100,
      inRange: { color: ['#1a237e', '#1565c0', '#26c6da', '#69f0ae', '#ffd740'] } },
    xAxis3D: Object.assign(makeAxis3D('年份'),   { type: 'category', data: YEARS }),
    yAxis3D: Object.assign(makeAxis3D('医院等级'), { type: 'category', data: GRADES }),
    zAxis3D: makeAxis3D('质量评分'),
    grid3D: makeGrid3D(5, {
      viewControl: { autoRotate: true, autoRotateSpeed: 5, distance: 170, alpha: 25, beta: 50 }
    }),
    series: [{
      type: 'surface', data,
      shading: 'lambert',
      wireframe: { show: true, lineStyle: { color: 'rgba(0,229,255,0.4)', width: 1 } },
      itemStyle: { opacity: 0.92 }
    }]
  })
  charts.push(chart)
}

/* ========== 5. 急诊效率 —— 2D 折线图（每年份各地区急诊占比） ========== */
function initEmergency() {
  const AREAS = ['纽约市', '长岛', '哈德逊', '首都区', '西部NY', '中部NY', '手指湖']
  const emergBase = [42, 28, 35, 24, 31, 30, 26]
  const areaColors = ['#00e5ff', '#40c4ff', '#7c4dff', '#ffd740', '#ff5252', '#69f0ae', '#ff80ab']

  // 每个地区一条折线，沿年份延伸
  const series = AREAS.map((area, ai) => ({
    name: area,
    type: 'line',
    smooth: true,
    showSymbol: true,
    symbol: 'circle',
    symbolSize: 7,
    data: YEARS.map((y, yi) => {
      const trend = -yi * 1.5
      return +(emergBase[ai] + trend + Math.random() * 3).toFixed(1)
    }),
    lineStyle: { width: 3, color: areaColors[ai], shadowBlur: 12, shadowColor: areaColors[ai] },
    itemStyle: { color: areaColors[ai], borderColor: '#ffffff', borderWidth: 1.5 },
    areaStyle: {
      color: {
        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: areaColors[ai] + '55' },
          { offset: 1, color: areaColors[ai] + '00' }
        ]
      }
    },
    emphasis: { focus: 'series' }
  }))

  const chart = echarts.init(chartEmergencyRef.value)
  chart.setOption({
    tooltip: { show: false },
    legend: {
      top: 4, right: 10,
      textStyle: { color: '#a8c5f0', fontSize: 9 },
      itemWidth: 10, itemHeight: 6
    },
    grid: { left: 45, right: 18, top: 32, bottom: 32 },
    xAxis: {
      type: 'category', data: YEARS,
      axisLine:  { lineStyle: { color: 'rgba(64,196,255,0.5)' } },
      axisLabel: { color: '#a8c5f0', fontSize: 10 },
      axisTick:  { lineStyle: { color: 'rgba(64,196,255,0.3)' } }
    },
    yAxis: {
      type: 'value', name: '急诊占比(%)',
      nameTextStyle: { color: '#7da3d4', fontSize: 10 },
      axisLine:  { lineStyle: { color: 'rgba(64,196,255,0.5)' } },
      axisLabel: { color: '#a8c5f0', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(64,196,255,0.15)' } },
      axisTick:  { lineStyle: { color: 'rgba(64,196,255,0.3)' } }
    },
    series
  })
  charts.push(chart)
}

/* ========== 6. 费用成本 —— bar3D 单系列，y=类别(费用/成本×MDC)，颜色按类型区分 ========== */
function initCost() {
  const MDC = ['内科', '外科', '妇产', '新生儿']
  const costBase    = [3200, 3600, 4100, 4500, 4900]
  const chargeBase  = [3800, 4300, 4900, 5400, 5900]
  // y 轴 8 个 category: 0-3 = 费用(4 个 MDC), 4-7 = 成本(4 个 MDC)
  const yCats = MDC.map(m => m + '·费用').concat(MDC.map(m => m + '·成本'))
  const data = []
  YEARS.forEach((y, yi) => {
    MDC.forEach((m, mi) => {
      const mult = 1 + mi * 0.3
      data.push([yi, mi, chargeBase[yi] * mult, 0])         // 费用
      data.push([yi, mi + 4, costBase[yi] * mult, 1])       // 成本
    })
  })
  const chart = echarts.init(chartCostRef.value)
  chart.setOption({
    tooltip: { show: false },
    visualMap: {
      show: false,
      dimension: 3,           // 按数据第 4 维（0/1）映射颜色
      min: 0, max: 1,
      inRange: { color: ['#40c4ff', '#ffd740'] }   // 0=费用蓝, 1=成本金
    },
    legend: {
      top: 4, right: 10,
      textStyle: { color: '#a8c5f0', fontSize: 10 },
      itemWidth: 10, itemHeight: 10,
      data: [
        { name: '总费用', itemStyle: { color: '#40c4ff' } },
        { name: '总成本', itemStyle: { color: '#ffd740' } }
      ],
      formatter: (name) => name
    },
    xAxis3D: Object.assign(makeAxis3D('年份'), { type: 'category', data: YEARS }),
    yAxis3D: Object.assign(makeAxis3D('MDC·类型'), {
      type: 'category', data: yCats,
      axisLabel: { color: '#a8c5f0', fontSize: 9, interval: 0 }
    }),
    zAxis3D: makeAxis3D('金额($)'),
    grid3D: makeGrid3D(8, {
      boxDepth: 130,
      viewControl: { autoRotate: true, autoRotateSpeed: 8, distance: 200, alpha: 15, beta: 45 }
    }),
    series: [{
      type: 'bar3D', shading: 'lambert', data, barSize: 8,
      label: { show: false },
      emphasis: { label: { show: false } }
    }]
  })
  charts.push(chart)
}

/* 数字翻牌 */
function animateNum(target, setter, duration = 2000) {
  const start = performance.now()
  function tick(now) {
    const t = Math.min(1, (now - start) / duration)
    const eased = 1 - Math.pow(1 - t, 3)
    setter(Math.floor(target * eased).toLocaleString('en-US'))
    if (t < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

onMounted(async () => {
  await nextTick()
  // 每个 init 包 try-catch，单个失败不影响其他图表
  const inits = [
    ['疾病谱',   initDisease],
    ['支付结构', initPayment],
    ['医院对比', initHospital],
    ['质量监测', initQuality],
    ['急诊效率', initEmergency],
    ['费用成本', initCost]
  ]
  inits.forEach(([name, fn]) => {
    try { fn() }
    catch (e) { console.error(`[图表初始化失败] ${name}:`, e) }
  })

  animateNum(10378775, v => numRecords.value  = v)
  animateNum(218,      v => numHospital.value = v)
  animateNum(485,      v => numDiag.value     = v)
  animateNum(5,        v => numYear.value     = v)

  resizeHandler = () => charts.forEach(c => c && c.resize())
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
  charts.forEach(c => c && c.dispose())
  charts = []
})
</script>

<style scoped>
* { margin: 0; padding: 0; box-sizing: border-box; }

.dashboard {
  width: 100%;
  height: 100vh;
  background: radial-gradient(ellipse at center, #0a2a5e 0%, #051633 50%, #020e2a 100%);
  font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
  color: #e3f2fd;
  display: flex;
  flex-direction: column;
  padding: 12px;
  overflow: hidden;
  position: relative;
}
.dashboard::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    radial-gradient(1px 1px at 10% 20%, #4fc3f7 50%, transparent),
    radial-gradient(1px 1px at 30% 80%, #4dd0e1 50%, transparent),
    radial-gradient(1px 1px at 60% 40%, #81d4fa 50%, transparent),
    radial-gradient(2px 2px at 80% 70%, #29b6f6 50%, transparent),
    radial-gradient(1px 1px at 90% 15%, #80deea 50%, transparent),
    radial-gradient(1px 1px at 45% 55%, #4fc3f7 50%, transparent),
    radial-gradient(2px 2px at 25% 65%, #26c6da 50%, transparent);
  background-size: 800px 800px;
  opacity: 0.5;
  animation: starShift 60s linear infinite;
}
@keyframes starShift {
  0%   { background-position: 0 0; }
  100% { background-position: 800px 800px; }
}

.header {
  height: 80px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  background: linear-gradient(90deg, rgba(13,35,75,0.6) 0%, rgba(30,80,160,0.4) 50%, rgba(13,35,75,0.6) 100%);
  border: 1px solid rgba(64,196,255,0.3);
  border-radius: 4px;
  position: relative;
  overflow: visible;
  z-index: 10;
}

/* 左上角下拉菜单 */
.dropdown {
  position: relative;
  flex-shrink: 0;
}
.menu-btn {
  display: flex; align-items: center; gap: 8px;
  background: rgba(0, 229, 255, 0.12);
  border: 1px solid rgba(0, 229, 255, 0.5);
  color: #00e5ff;
  padding: 8px 16px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-family: inherit;
  letter-spacing: 1px;
  transition: all 0.3s;
}
.menu-btn:hover {
  background: rgba(0, 229, 255, 0.25);
  box-shadow: 0 0 16px rgba(0, 229, 255, 0.5);
}
.menu-icon { font-size: 18px; line-height: 1; }
.menu-arrow {
  font-size: 10px;
  transition: transform 0.25s;
}
.menu-arrow.open { transform: rotate(180deg); }

.menu-panel {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  min-width: 260px;
  background: rgba(8, 24, 56, 0.96);
  border: 1px solid rgba(0, 229, 255, 0.4);
  border-radius: 4px;
  padding: 6px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6), 0 0 24px rgba(0, 229, 255, 0.15);
  z-index: 100;
  backdrop-filter: blur(8px);
}
.menu-panel::before {
  content: ""; position: absolute; top: -6px; left: 20px;
  width: 10px; height: 10px;
  background: rgba(8, 24, 56, 0.96);
  border-left: 1px solid rgba(0, 229, 255, 0.4);
  border-top: 1px solid rgba(0, 229, 255, 0.4);
  transform: rotate(45deg);
}
.menu-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px;
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.2s, transform 0.2s;
}
.menu-item:hover {
  background: rgba(0, 229, 255, 0.15);
  transform: translateX(3px);
}
.item-icon { font-size: 22px; line-height: 1; }
.item-text { flex: 1; }
.item-title {
  color: #e3f2fd;
  font-size: 13px;
  font-weight: bold;
  letter-spacing: 1px;
}
.item-desc {
  color: #7da3d4;
  font-size: 11px;
  margin-top: 2px;
}

/* 下拉淡入动画 */
.menu-fade-enter-active, .menu-fade-leave-active {
  transition: opacity 0.2s, transform 0.2s;
  transform-origin: top left;
}
.menu-fade-enter-from, .menu-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
}

/* 右上角下拉菜单专属：面板右对齐，三角靠右 */
.dropdown-right { align-self: center; margin-left: 20px; }
.menu-panel-right {
  left: auto;
  right: 0;
  min-width: 280px;
}
.menu-panel-right::before {
  left: auto;
  right: 20px;
}
.menu-fade-enter-active.menu-panel-right,
.menu-fade-leave-active.menu-panel-right {
  transform-origin: top right;
}

.header::before {
  content: "";
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, transparent, #00e5ff, transparent);
  animation: scanLine 4s linear infinite;
}
@keyframes scanLine {
  0%   { left: -100%; }
  100% { left: 100%; }
}
.title {
  font-size: 32px;
  font-weight: bold;
  background: linear-gradient(180deg, #ffffff 0%, #4fc3f7 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: 4px;
  text-shadow: 0 0 20px rgba(64,196,255,0.5);
}
.subtitle {
  font-size: 13px;
  color: #7da3d4;
  letter-spacing: 2px;
  margin-top: 4px;
}
.header-right {
  display: flex;
  gap: 30px;
  font-size: 13px;
}
.stat-item { text-align: center; }
.stat-item .num {
  font-size: 22px;
  font-weight: bold;
  color: #00e5ff;
  text-shadow: 0 0 10px rgba(0,229,255,0.6);
  font-family: 'Courier New', monospace;
}
.stat-item .lbl {
  font-size: 11px;
  color: #7da3d4;
}

.grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 10px;
  margin-top: 10px;
  z-index: 1;
}
.card {
  background: rgba(8, 24, 56, 0.55);
  border: 1px solid rgba(64,196,255,0.25);
  border-radius: 4px;
  padding: 10px;
  position: relative;
  display: flex;
  flex-direction: column;
  box-shadow: inset 0 0 30px rgba(0,150,255,0.08);
  min-height: 0;
  min-width: 0;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}
.card.clickable {
  cursor: pointer;
}
.card.clickable:hover {
  border-color: #00e5ff;
  box-shadow: inset 0 0 30px rgba(0,150,255,0.08), 0 0 24px rgba(0,229,255,0.45);
  transform: translateY(-2px);
}
.card::before,
.card::after {
  content: "";
  position: absolute;
  width: 14px;
  height: 14px;
  border-color: #00e5ff;
  border-style: solid;
  border-width: 0;
}
.card::before {
  top: 0;
  left: 0;
  border-top-width: 2px;
  border-left-width: 2px;
}
.card::after {
  bottom: 0;
  right: 0;
  border-bottom-width: 2px;
  border-right-width: 2px;
}
.card-title {
  font-size: 15px;
  font-weight: bold;
  color: #4fc3f7;
  padding-left: 10px;
  border-left: 3px solid #00e5ff;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.card-title .tag {
  font-size: 10px;
  color: #7da3d4;
  background: rgba(0,229,255,0.1);
  padding: 1px 6px;
  border-radius: 2px;
  border: 1px solid rgba(0,229,255,0.3);
  font-weight: normal;
  letter-spacing: 1px;
}
.chart-box {
  flex: 1;
  width: 100%;
  min-height: 260px;
}
</style>
