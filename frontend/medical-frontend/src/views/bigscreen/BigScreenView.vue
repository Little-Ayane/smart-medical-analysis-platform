<template>
  <div class="bigscreen" ref="screenRef">
    <div class="header-wrap" :class="{ 'header-visible': animationReady }">
      <ScreenHeader :summary="data.summary" />
    </div>
    <div class="screen-body">
      <div class="panel-left-wrap" :class="{ 'panel-visible': panelsReady }">
        <PanelLeft :topDiseases="data.top_diseases" :ageDistribution="data.age_distribution" :serviceAreas="data.service_areas" />
      </div>
      <div class="map-area">
        <Map3D :serviceAreas="data.service_areas" :topHospitals="data.top_hospitals" @animationDone="onMapAnimationDone" />
      </div>
      <div class="panel-right-wrap" :class="{ 'panel-visible': panelsReady }">
        <PanelRight :paymentTypes="data.payment_types" :severityDist="data.severity_dist" :topDrg="data.top_drg" />
      </div>
    </div>
    <div class="footer-wrap" :class="{ 'footer-visible': panelsReady }">
      <ScreenFooter :summary="data.summary" />
    </div>
    <!-- Loading -->
    <div class="loading-overlay" v-if="loading">
      <div class="loading-spinner"></div>
      <div class="loading-text">数据加载中...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import axios from 'axios'
import ScreenHeader from './components/ScreenHeader.vue'
import PanelLeft from './components/PanelLeft.vue'
import PanelRight from './components/PanelRight.vue'
import Map3D from './components/Map3D.vue'
import ScreenFooter from './components/ScreenFooter.vue'

const screenRef = ref(null)
const loading = ref(true)
const animationReady = ref(false)
const panelsReady = ref(false)

const data = reactive({
  service_areas: [],
  top_hospitals: [],
  summary: {},
  top_diseases: [],
  age_distribution: [],
  payment_types: [],
  severity_dist: [],
  top_drg: []
})

// 地图入场动画完成后触发
function onMapAnimationDone() {
  // 先显示 header 和 footer
  animationReady.value = true
  // 延迟后显示左右面板
  setTimeout(() => {
    panelsReady.value = true
  }, 300)
}

async function fetchData() {
  loading.value = true
  try {
    const res = await axios.get('/api/v1/bigscreen/overview')
    if (res.data && res.data.code === 0) {
      const d = res.data.data
      data.service_areas = d.service_areas || []
      data.top_hospitals = d.top_hospitals || []
      data.summary = d.summary || {}
      data.top_diseases = d.top_diseases || []
      data.age_distribution = d.age_distribution || []
      data.payment_types = d.payment_types || []
      data.severity_dist = d.severity_dist || []
      data.top_drg = d.top_drg || []
    }
  } catch (e) {
    console.error('数据加载失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

.bigscreen {
  width: 100vw;
  height: 100vh;
  background: linear-gradient(135deg, #0a1628 0%, #0d2137 50%, #0a1628 100%);
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  color: #e3f2fd;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* 网格背景 */
.bigscreen::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0, 229, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 229, 255, 0.03) 1px, transparent 1px);
  background-size: 50px 50px;
  pointer-events: none;
  z-index: 0;
}

/* Header 动画 */
.header-wrap {
  opacity: 0;
  transform: translateY(-100%);
  transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}
.header-wrap.header-visible {
  opacity: 1;
  transform: translateY(0);
}

.screen-body {
  flex: 1;
  display: flex;
  gap: 0;
  padding: 0 24px 24px;
  min-height: 0;
  position: relative;
  z-index: 1;
}

/* 左侧面板动画 - 使用绝对定位，不影响地图 */
.panel-left-wrap {
  position: absolute;
  left: 24px;
  top: 0;
  bottom: 0;
  width: 320px;
  opacity: 0;
  transform: translateX(-100%);
  transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 10;
}
.panel-left-wrap.panel-visible {
  opacity: 1;
  transform: translateX(0);
}

/* 右侧面板动画 - 使用绝对定位，不影响地图 */
.panel-right-wrap {
  position: absolute;
  right: 24px;
  top: 0;
  bottom: 0;
  width: 320px;
  opacity: 0;
  transform: translateX(100%);
  transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 10;
}
.panel-right-wrap.panel-visible {
  opacity: 1;
  transform: translateX(0);
}

.map-area {
  flex: 1;
  min-width: 0;
  position: relative;
  border-radius: 8px;
  background: rgba(0, 229, 255, 0.02);
  border: 1px solid rgba(0, 229, 255, 0.1);
  box-shadow: 0 0 30px rgba(0, 229, 255, 0.05);
  margin: 0 16px;
}

/* Footer 动画 */
.footer-wrap {
  opacity: 0;
  transform: translateY(100%);
  transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}
.footer-wrap.footer-visible {
  opacity: 1;
  transform: translateY(0);
}

/* Loading overlay */
.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(2, 14, 42, 0.95);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(10px);
}

.loading-spinner {
  width: 50px;
  height: 50px;
  border: 3px solid rgba(0, 229, 255, 0.1);
  border-top-color: #00e5ff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  box-shadow: 0 0 20px rgba(0, 229, 255, 0.3);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-text {
  margin-top: 16px;
  color: #7da3d4;
  font-size: 14px;
  letter-spacing: 2px;
  text-shadow: 0 0 10px rgba(0, 229, 255, 0.5);
}
</style>
