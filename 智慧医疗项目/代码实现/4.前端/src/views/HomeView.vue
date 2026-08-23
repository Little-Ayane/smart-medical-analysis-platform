<template>
  <div class="dashboard">
    <!-- ====== 粒子背景装饰 ====== -->
    <div class="bg-particles"></div>

    <!-- ====== 顶部导航 ====== -->
    <header class="header">
      <div class="header-content">
        <div class="logo">
          <span class="logo-icon">🏥</span>
          <span class="logo-text">智慧医疗数据指挥中心</span>
        </div>
        <div class="header-right">
          <span class="status-dot"></span>
          <span class="status-text">系统运行中</span>
          <span class="header-time">{{ currentTime }}</span>
        </div>
      </div>
    </header>

    <!-- ====== 核心指标行 ====== -->
    <div class="stats-row">
      <div class="stat-item" v-for="s in stats" :key="s.label">
        <div class="stat-icon">{{ s.icon }}</div>
        <div class="stat-info">
          <div class="stat-label">{{ s.label }}</div>
          <div class="stat-value"><span class="num-roll">{{ s.value }}</span></div>
          <div class="stat-change" :class="s.change >= 0 ? 'up' : 'down'">
            {{ s.change >= 0 ? '↑' : '↓' }} {{ Math.abs(s.change) }}%
          </div>
        </div>
      </div>
    </div>

    <!-- ====== 轮播图区域 ====== -->
    <div class="carousel-section">
      <div class="chart-panel">
        <div class="panel-header">
          <span class="panel-title">📊 模块预览（点击进入大屏）</span>
          <span class="panel-tag">{{ slides[currentSlide].title }}</span>
        </div>
        <div class="carousel-wrapper" @wheel.prevent="onWheel">
          <div class="carousel-track" :style="{ transform: 'translateX(-' + currentSlide * 100 + '%)' }">
            <div
              class="carousel-slide"
              v-for="(slide, idx) in slides"
              :key="idx"
              @click="goTo('/dashboard')"
            >
              <div :ref="el => { if (el) slideEls[idx] = el }" class="slide-chart"></div>
              <div class="slide-label">{{ slide.title }} · 点击查看大屏</div>
            </div>
          </div>
        </div>
        <div class="carousel-dots">
          <span
            class="dot"
            v-for="(slide, idx) in slides"
            :key="idx"
            :class="{ active: idx === currentSlide }"
            @click="goToSlide(idx)"
          ></span>
        </div>
      </div>
    </div>

    <!-- ====== 功能入口（独立区域） ====== -->
    <div class="modules-section">
      <div class="modules-panel">
        <div class="panel-header">
          <span class="panel-title">🎯 功能入口</span>
          <span class="panel-tag">点击进入分析</span>
        </div>
        <div class="modules-grid">
          <div class="module-card" v-for="m in modules" :key="m.path" @click="goTo(m.path)">
            <div class="module-icon">{{ m.icon }}</div>
            <div class="module-name">{{ m.title }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ====== 底部：数据摘要 ====== -->
    <footer class="footer">
      <div class="footer-left">
        <span>数据更新：{{ updateTime }}</span>
        <span class="divider">|</span>
        <span>数据源：纽约州 SPARCS 住院病案数据</span>
        <span class="divider">|</span>
        <span>记录数：10,378,775 条</span>
      </div>
      <div class="footer-right">
        <span>© 2026 智慧医疗大数据平台 v2.0</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import 'echarts-gl'

const router = useRouter()

// ====== 当前时间 ======
const currentTime = ref('')
let timer = null

const refreshTime = () => {
  const now = new Date()
  currentTime.value = now.toLocaleTimeString('zh-CN', { hour12: false })
}

// ====== 顶部指标（来自 star_schema.sql 真实数据） ======
const stats = ref([
  { icon: '📋', label: '总出院记录', value: '10,378,775', change: 3.2 },
  { icon: '🏥', label: '医院数', value: '218', change: 1.1 },
  { icon: '🩺', label: '诊断数', value: '485', change: 2.4 },
  { icon: '🔬', label: '手术数', value: '322', change: 1.8 }
])

// ====== 功能模块 ======
const modules = [
  { path: '/disease', icon: '📊', title: '疾病谱分析' },
  { path: '/payment', icon: '🧾', title: '支付结构' },
  { path: '/hospital', icon: '🏥', title: '医院对比' },
  { path: '/quality', icon: '📉', title: '质量监测' },
  { path: '/emergency', icon: '🚑', title: '急诊效率' },
  { path: '/cost', icon: '💰', title: '费用成本' },
  { path: '/drill', icon: '🔍', title: '多维下钻' },
  { path: '/ai', icon: '🤖', title: 'AI助手' }
]

// ====== 轮播数据：与 DashboardView 一致的 6 个图 ======
const YEARS = ['2020', '2021', '2022', '2023', '2024']
const slides = [
  { title: '疾病谱分析', type: 'bar3D' },
  { title: '支付结构', type: 'pie' },
  { title: '医院对比', type: 'scatter3D' },
  { title: '质量监测', type: 'surface' },
  { title: '急诊效率', type: 'line' },
  { title: '费用成本', type: 'bar3DMix' }
]

const currentSlide = ref(0)
const slideEls = ref([])
let slideCharts = []
let slideTimer = null

// ====== 更新时间 ======
const updateTime = ref('2026-08-23 数据星型模式')

// ====== 跳转到大屏 ======
const goTo = (path) => {
  router.push(path)
}

/* ===== 通用配置（迷你版，简化后处理避免 6 个 WebGL 上下文崩溃） ===== */
const axisStyle = {
  axisLine: { lineStyle: { color: 'rgba(64,196,255,0.5)' } },
  axisLabel: { color: '#a8c5f0', fontSize: 9 },
  splitLine: { lineStyle: { color: 'rgba(64,196,255,0.15)' } },
  axisTick:  { lineStyle: { color: 'rgba(64,196,255,0.3)' } }
}
const grid3DBase = {
  boxWidth: 70, boxDepth: 55, boxHeight: 45,
  viewControl: { autoRotate: true, autoRotateSpeed: 6, distance: 140, alpha: 15, beta: 40 },
  light: { main: { intensity: 1.2, shadow: false, alpha: 30, beta: 40 }, ambient: { intensity: 0.5 } },
  environment: 'none'
}

/* 1. 疾病谱 bar3D 迷你版 */
function optDisease() {
  const CAT = ['循环', '呼吸', '消化', '肿瘤', '损伤', '内分泌', '神经', '泌尿']
  const base = [240, 180, 130, 150, 110, 90, 80, 100]
  const data = []
  YEARS.forEach((y, yi) => {
    CAT.forEach((c, ci) => {
      data.push([yi, ci, Math.round(base[ci] * (1 + yi * 0.04))])
    })
  })
  return {
    tooltip: { show: false },
    visualMap: { show: false, max: 280, min: 0,
      inRange: { color: ['#0d47a1', '#1976d2', '#40c4ff', '#00e5ff', '#ffd740'] } },
    xAxis3D: Object.assign({ name: '年份', type: 'category', data: YEARS, nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    yAxis3D: Object.assign({ name: '类别', type: 'category', data: CAT, nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    zAxis3D: Object.assign({ name: '病例', nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    grid3D: grid3DBase,
    series: [{ type: 'bar3D', shading: 'lambert', data,
      label: { show: false },
      emphasis: { label: { show: false }, itemStyle: { color: '#00e5ff' } } }]
  }
}

/* 2. 支付结构 饼图迷你版 */
function optPayment() {
  const data = [
    { value: 38, name: '联邦医保',    itemStyle: { color: '#00e5ff' } },
    { value: 25, name: '州医疗补助',  itemStyle: { color: '#40c4ff' } },
    { value: 18, name: '商业保险',    itemStyle: { color: '#7c4dff' } },
    { value: 10, name: '蓝十字',      itemStyle: { color: '#ffd740' } },
    { value: 5,  name: '自费',        itemStyle: { color: '#ff5252' } },
    { value: 4,  name: '其他',        itemStyle: { color: '#69f0ae' } }
  ]
  return {
    tooltip: { show: false },
    legend: { orient: 'vertical', right: 4, top: 'center',
      textStyle: { color: '#a8c5f0', fontSize: 9 }, itemWidth: 8, itemHeight: 8 },
    series: [{
      type: 'pie', radius: ['28%', '58%'], center: ['38%', '50%'],
      roseType: 'radius',
      label: { color: '#e3f2fd', fontSize: 9, formatter: '{d}%' },
      labelLine: { length: 5, length2: 6, lineStyle: { color: 'rgba(64,196,255,0.5)' } },
      itemStyle: { borderColor: '#0a2a5e', borderWidth: 2,
        shadowBlur: 18, shadowColor: 'rgba(0,229,255,0.6)' },
      emphasis: {
        scale: true, scaleSize: 10,
        label: { fontSize: 11, fontWeight: 'bold', color: '#fff' },
        itemStyle: { shadowBlur: 30, shadowColor: 'rgba(0,229,255,0.95)', borderColor: '#00e5ff' }
      },
      blur: { itemStyle: { opacity: 0.25 } },
      data
    }]
  }
}

/* 3. 医院对比 scatter3D 迷你版 */
function optHospital() {
  const data = []
  for (let i = 0; i < 50; i++) {
    const cases = 2000 + Math.floor(Math.random() * 45000)
    const charge = 8000 + Math.floor(Math.random() * 42000)
    const los = 2 + Math.random() * 6
    data.push([cases, charge, +los.toFixed(1), i % 7])
  }
  return {
    tooltip: { show: false },
    visualMap: { show: false, min: 0, max: 7,
      inRange: { color: ['#00e5ff','#40c4ff','#7c4dff','#ffd740','#ff5252','#69f0ae','#ff80ab'] } },
    xAxis3D: Object.assign({ name: '病例', nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    yAxis3D: Object.assign({ name: '费用', nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    zAxis3D: Object.assign({ name: '天数', nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    grid3D: Object.assign(grid3DBase, {
      viewControl: { autoRotate: true, autoRotateSpeed: 6, distance: 130, alpha: 12, beta: 35 }
    }),
    series: [{
      type: 'scatter3D', data,
      symbolSize: d => Math.sqrt(d[0]) / 24 + 2,
      shading: 'color',
      itemStyle: { borderColor: '#ffffff', borderWidth: 0.5, opacity: 0.85 },
      label: { show: false }
    }]
  }
}

/* 4. 质量监测 surface 迷你版 */
function optQuality() {
  const GRADES = ['A', 'B', 'C', 'D', 'E', 'F']
  const data = []
  for (let xi = 0; xi < 5; xi++) {
    for (let yi = 0; yi < 6; yi++) {
      data.push([xi, yi, 95 - yi * 7 + Math.sin(xi * 0.8) * 3])
    }
  }
  return {
    tooltip: { show: false },
    visualMap: { show: false, min: 55, max: 100,
      inRange: { color: ['#1a237e', '#1565c0', '#26c6da', '#69f0ae', '#ffd740'] } },
    xAxis3D: Object.assign({ name: '年份', type: 'category', data: YEARS, nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    yAxis3D: Object.assign({ name: '等级', type: 'category', data: GRADES, nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    zAxis3D: Object.assign({ name: '评分', nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    grid3D: Object.assign(grid3DBase, {
      viewControl: { autoRotate: true, autoRotateSpeed: 5, distance: 120, alpha: 20, beta: 50 }
    }),
    series: [{
      type: 'surface', data, shading: 'lambert',
      wireframe: { show: true, lineStyle: { color: 'rgba(0,229,255,0.4)', width: 1 } },
      itemStyle: { opacity: 0.92 }
    }]
  }
}

/* 5. 急诊效率 折线图迷你版 */
function optEmergency() {
  const AREAS = ['纽约市', '长岛', '哈德逊', '首都区', '西部NY', '中部NY', '手指湖']
  const emergBase = [42, 28, 35, 24, 31, 30, 26]
  const areaColors = ['#00e5ff', '#40c4ff', '#7c4dff', '#ffd740', '#ff5252', '#69f0ae', '#ff80ab']
  return {
    tooltip: { show: false },
    legend: { top: 2, right: 6, textStyle: { color: '#a8c5f0', fontSize: 8 }, itemWidth: 8, itemHeight: 4 },
    grid: { left: 32, right: 12, top: 24, bottom: 24 },
    xAxis: Object.assign({ type: 'category', data: YEARS }, axisStyle),
    yAxis: Object.assign({ type: 'value', name: '急诊占比%', nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    series: AREAS.map((a, ai) => ({
      name: a, type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
      data: YEARS.map((y, yi) => +(emergBase[ai] - yi * 1.5 + Math.random() * 3).toFixed(1)),
      lineStyle: { width: 2, color: areaColors[ai] },
      itemStyle: { color: areaColors[ai] },
      areaStyle: { opacity: 0.08 }
    }))
  }
}

/* 6. 费用成本 bar3D 迷你版（费用蓝 vs 成本金） */
function optCost() {
  const MDC = ['内科', '外科', '妇产', '新生儿']
  const yCats = MDC.map(m => m + '·费用').concat(MDC.map(m => m + '·成本'))
  const data = []
  YEARS.forEach((y, yi) => {
    MDC.forEach((m, mi) => {
      const mult = 1 + mi * 0.3
      data.push([yi, mi, 3800 * (1 + yi * 0.1) * mult, 0])
      data.push([yi, mi + 4, 3200 * (1 + yi * 0.1) * mult, 1])
    })
  })
  return {
    tooltip: { show: false },
    visualMap: { show: false, dimension: 3, min: 0, max: 1,
      inRange: { color: ['#40c4ff', '#ffd740'] } },
    legend: { top: 2, right: 8, textStyle: { color: '#a8c5f0', fontSize: 9 },
      data: [{ name: '总费用' }, { name: '总成本' }], formatter: () => '' },
    xAxis3D: Object.assign({ name: '年份', type: 'category', data: YEARS, nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    yAxis3D: Object.assign({ name: 'MDC·类型', type: 'category', data: yCats,
      nameTextStyle: { color: '#7da3d4', fontSize: 9 },
      axisLabel: Object.assign({}, axisStyle.axisLabel, { fontSize: 8, interval: 0 }) }, axisStyle),
    zAxis3D: Object.assign({ name: '金额', nameTextStyle: { color: '#7da3d4', fontSize: 9 } }, axisStyle),
    grid3D: Object.assign(grid3DBase, { boxDepth: 90,
      viewControl: { autoRotate: true, autoRotateSpeed: 7, distance: 130, alpha: 12, beta: 45 } }),
    series: [{ type: 'bar3D', shading: 'lambert', data, barSize: 5,
      label: { show: false }, emphasis: { label: { show: false } } }]
  }
}

// ====== 初始化轮播图表 ======
const initSlideCharts = () => {
  const optMap = {
    bar3D: optDisease,
    pie: optPayment,
    scatter3D: optHospital,
    surface: optQuality,
    line: optEmergency,
    bar3DMix: optCost
  }
  slides.forEach((slide, idx) => {
    const el = slideEls.value[idx]
    if (!el) return
    try {
      const chart = echarts.init(el)
      chart.setOption(optMap[slide.type]())
      // 拦截 ECharts canvas 上的 wheel 事件：阻止 3D 图缩放，并手动调用 onWheel 切换轮播
      const canvas = el.querySelector('canvas')
      if (canvas) {
        canvas.addEventListener('wheel', (e) => {
          e.preventDefault()
          e.stopImmediatePropagation()
          onWheel(e)
        }, { capture: true, passive: false })
      }
      slideCharts[idx] = chart
    } catch (e) {
      console.error(`[轮播图初始化失败] ${slide.title}:`, e)
    }
  })
}

// ====== 轮播自动切换 ======
const startAutoPlay = () => {
  slideTimer = setInterval(() => {
    currentSlide.value = (currentSlide.value + 1) % slides.length
  }, 4500)
}
const stopAutoPlay = () => {
  if (slideTimer) { clearInterval(slideTimer); slideTimer = null }
}

// ====== 轮播控制 ======
const goToSlide = (idx) => {
  currentSlide.value = idx
}

// ====== 滚轮切换：向上→前一张(左)，向下→后一张(右) ======
let wheelLock = false
function onWheel(e) {
  if (wheelLock) return
  // deltaY > 0 表示向下滚（往右/下一张），< 0 表示向上滚（往左/上一张）
  const next = e.deltaY > 0
    ? (currentSlide.value + 1) % slides.length
    : (currentSlide.value - 1 + slides.length) % slides.length
  currentSlide.value = next
  // 节流：300ms 内只允许一次切换，避免滚轮连续触发跳太多张
  wheelLock = true
  setTimeout(() => { wheelLock = false }, 300)
}

// ====== 生命周期 ======
onMounted(async () => {
  refreshTime()
  timer = setInterval(refreshTime, 1000)
  await nextTick()
  setTimeout(() => {
    initSlideCharts()
    startAutoPlay()
  }, 200)
})

onUnmounted(() => {
  clearInterval(timer)
  stopAutoPlay()
  slideCharts.forEach(chart => {
    if (chart && chart.dispose) chart.dispose()
  })
  slideCharts = []
})
</script>

<style scoped>
/* ====== 全局暗色背景 ====== */
.dashboard {
  min-height: 100vh;
  background: #0a1628;
  background-image:
    radial-gradient(ellipse at 10% 20%, rgba(0, 100, 200, 0.08) 0%, transparent 60%),
    radial-gradient(ellipse at 90% 80%, rgba(0, 200, 255, 0.06) 0%, transparent 50%);
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
  padding: 16px 24px 10px;
  position: relative;
  overflow-x: hidden;
}

/* ====== 粒子背景装饰 ====== */
.bg-particles {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
  background-image:
    radial-gradient(2px 2px at 20% 30%, rgba(255,255,255,0.15), transparent),
    radial-gradient(2px 2px at 40% 70%, rgba(255,255,255,0.1), transparent),
    radial-gradient(2px 2px at 60% 20%, rgba(255,255,255,0.12), transparent),
    radial-gradient(2px 2px at 80% 80%, rgba(255,255,255,0.08), transparent),
    radial-gradient(2px 2px at 10% 90%, rgba(255,255,255,0.1), transparent),
    radial-gradient(2px 2px at 90% 10%, rgba(255,255,255,0.06), transparent),
    radial-gradient(2px 2px at 50% 50%, rgba(255,255,255,0.1), transparent);
  background-size: 200px 200px;
  z-index: -1;
}

/* ====== 顶部导航 ====== */
.header {
  position: relative;
  z-index: 1;
  background: rgba(10, 22, 40, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(0, 212, 255, 0.15);
  border-radius: 16px;
  padding: 14px 28px;
  margin-bottom: 18px;
  box-shadow: 0 0 40px rgba(0, 212, 255, 0.05);
}
.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo-icon { font-size: 28px; }
.logo-text {
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1.5px;
  background: linear-gradient(90deg, #00d4ff, #7b61ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.status-dot {
  width: 8px;
  height: 8px;
  background: #00ff88;
  border-radius: 50%;
  animation: pulse-dot 1.5s infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; box-shadow: 0 0 8px #00ff88; }
  50% { opacity: 0.4; box-shadow: 0 0 2px #00ff88; }
}
.status-text {
  color: #00ff88;
  font-size: 13px;
}
.header-time {
  color: #8ab4d6;
  font-size: 14px;
  font-weight: 500;
  background: rgba(0,212,255,0.08);
  padding: 4px 14px;
  border-radius: 20px;
  border: 1px solid rgba(0,212,255,0.1);
}

/* ====== 指标行 ====== */
.stats-row {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 18px;
}
.stat-item {
  background: rgba(10, 22, 40, 0.6);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(0, 212, 255, 0.12);
  border-radius: 12px;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: all 0.3s;
}
.stat-item:hover {
  border-color: rgba(0, 212, 255, 0.35);
  box-shadow: 0 0 30px rgba(0, 212, 255, 0.06);
}
.stat-icon { font-size: 28px; }
.stat-info { flex: 1; }
.stat-label {
  font-size: 12px;
  color: #7a9aaa;
  letter-spacing: 0.5px;
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #fff;
  line-height: 1.3;
}
.stat-value .num-roll {
  background: linear-gradient(90deg, #fff, #8ab4d6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.stat-change {
  font-size: 12px;
  margin-top: 2px;
}
.stat-change.up { color: #00ff88; }
.stat-change.down { color: #ff6b6b; }

/* ====== 轮播图区域 ====== */
.carousel-section {
  position: relative;
  z-index: 1;
  margin-bottom: 18px;
}

.chart-panel {
  background: rgba(10, 22, 40, 0.6);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(0, 212, 255, 0.12);
  border-radius: 12px;
  padding: 16px 18px 12px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.panel-title {
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
.panel-tag {
  color: #8ab4d6;
  font-size: 11px;
  background: rgba(0,212,255,0.08);
  padding: 2px 12px;
  border-radius: 12px;
  border: 1px solid rgba(0,212,255,0.08);
}

/* ====== 功能入口（独立区域） ====== */
.modules-section {
  position: relative;
  z-index: 1;
  margin-bottom: 16px;
}

.modules-panel {
  background: rgba(10, 22, 40, 0.6);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(0, 212, 255, 0.12);
  border-radius: 12px;
  padding: 16px 18px 14px;
}

.modules-grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 12px;
  padding-top: 2px;
}

.module-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 18px 8px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  backdrop-filter: blur(4px);
}
.module-card:hover {
  background: rgba(0, 212, 255, 0.1);
  border-color: rgba(0, 212, 255, 0.4);
  transform: translateY(-4px) scale(1.02);
  box-shadow: 0 8px 30px rgba(0, 212, 255, 0.12);
}
.module-icon { font-size: 28px; }
.module-name {
  font-size: 12px;
  color: #e8f0f8;
  margin-top: 4px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

/* ====== 轮播样式 ====== */
.carousel-wrapper {
  overflow: hidden;
  border-radius: 8px;
  position: relative;
}
.carousel-track {
  display: flex;
  transition: transform 0.6s ease;
}
.carousel-slide {
  min-width: 100%;
  cursor: pointer;
  padding: 4px 0;
}
.carousel-slide .slide-chart {
  width: 100%;
  height: 220px;
}
.carousel-slide .slide-label {
  text-align: center;
  font-size: 13px;
  color: #8ab4d6;
  margin-top: 2px;
  letter-spacing: 1px;
}
.carousel-dots {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}
.carousel-dots .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255,255,255,0.2);
  cursor: pointer;
  transition: all 0.3s;
}
.carousel-dots .dot.active {
  background: #00d4ff;
  box-shadow: 0 0 12px rgba(0,212,255,0.4);
  width: 20px;
  border-radius: 4px;
}

/* ====== Footer ====== */
.footer {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid rgba(0, 212, 255, 0.06);
  color: #5a7a8a;
  font-size: 12px;
}
.footer-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.footer-left .divider { color: #3a5a6a; }
.footer-right { color: #4a6a7a; }

/* ====== 响应式 ====== */
@media (max-width: 1024px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .modules-grid { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 640px) {
  .header-content { flex-direction: column; align-items: flex-start; gap: 10px; }
  .stats-row { grid-template-columns: 1fr; }
  .modules-grid { grid-template-columns: repeat(4, 1fr); }
  .dashboard { padding: 10px 12px; }
}
</style>