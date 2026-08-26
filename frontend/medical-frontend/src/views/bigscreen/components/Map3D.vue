<template>
  <div ref="wrap" class="map3d-wrap">
    <canvas ref="canvas" class="map3d-canvas" />
    <div v-if="tooltip.show" class="map-tooltip" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }">
      <div class="tip-title">{{ tooltip.name }}</div>
      <div class="tip-row"><span class="tip-label">住院人次</span><span class="tip-value">{{ tooltip.cases }}</span></div>
      <div class="tip-row"><span class="tip-label">平均费用</span><span class="tip-value">${{ tooltip.cost }}</span></div>
      <div class="tip-row"><span class="tip-label">平均住院天数</span><span class="tip-value">{{ tooltip.los }}天</span></div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { geoMercator } from 'd3-geo'
import gsap from 'gsap'
import regionsData from '../../../assets/ny_regions.json'
import nyStateData from '../../../assets/ny.json'

const props = defineProps({
  serviceAreas: { type: Array, default: () => [] },
  topHospitals: { type: Array, default: () => [] }
})

const emit = defineEmits(['animationDone'])

const wrap = ref(null)
const canvas = ref(null)
const tooltip = ref({ show: false, x: 0, y: 0, name: '', cases: '', cost: '', los: '' })

let scene, camera, renderer, controls, clock
let mapGroup, innerGroup, effectGroup
let raycaster, mouse
let animTimer = null
let interactiveObjects = []
let regionCenters = []
let boundaryPoints = []
let scanTime = 0
let hoveredObject = null
let outlineLine = null

const projection = geoMercator().center([-75.81, 42.76]).scale(600).translate([0, 0])

const REGION_COLORS = {
  'New York City': 0x00e5ff,
  'Long Island': 0x18ffff,
  'Hudson Valley': 0x69f0ae,
  'Mid-Hudson': 0xb388ff,
  'Capital District': 0xff5252,
  'North Country': 0x448aff,
  'Mohawk Valley': 0xff9100,
  'Central NY': 0x00bfa5,
  'Finger Lakes': 0xffd740,
  'Southern Tier': 0xff80ab,
  'Western NY': 0x7c4dff
}

/* ── 扫描带 Shader (sc-datav: 颜色混合，每区域独立色) ── */
const shiftVertexShader = `
  varying vec2 vUv;
  varying float vZ;
  void main() {
    vUv = uv;
    vZ = position.z;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const shiftFragmentShader = `
  uniform float time;
  uniform float depth;
  uniform vec4 baseColor;
  uniform vec4 scanColor;
  varying vec2 vUv;
  varying float vZ;

  void main() {
    float scanEffect = smoothstep(0.0, 0.3, abs(sin(vZ * 2.0 / depth + time)));
    vec4 finalColor = mix(baseColor, scanColor, scanEffect);
    gl_FragColor = finalColor;
  }
`

/* ── 边界渐变 Shader ── */
const boundaryVertexShader = `
  varying vec3 vPosition;
  varying vec3 vNormal;
  varying vec2 vUv;
  void main() {
    vPosition = position;
    vNormal = normal;
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const boundaryFragmentShader = `
  varying vec3 vPosition;
  varying vec3 vNormal;
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uDepth;
  void main() {
    if(vNormal.z == 1.0 || vNormal.z == -1.0 || vUv.y == 0.0) { discard; }
    float h = mix(1.0, 0.0, vPosition.z / uDepth);
    gl_FragColor = vec4(uColor, h * uOpacity);
  }
`

/* ── 光柱 Shader ── */
const beamVertexShader = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const beamFragmentShader = `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying vec2 vUv;
  void main() {
    float strength = 1.0 - abs(vUv.x - 0.5) * 2.0;
    strength = pow(strength, 2.0);
    float verticalFade = sin(vUv.y * 3.14159);
    verticalFade = pow(verticalFade, 0.5);
    float brightness = strength * verticalFade * 1.0;
    vec3 finalColor = uColor * brightness * 2.0;
    gl_FragColor = vec4(finalColor, brightness * uOpacity);
  }
`

/* ── 初始化 ── */
function init() {
  const el = wrap.value
  const w = el.clientWidth, h = el.clientHeight

  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0a1628)
  scene.fog = new THREE.FogExp2(0x0a1628, 0.015)

  camera = new THREE.PerspectiveCamera(70, w / h, 0.1, 1000)
  camera.position.set(3, 30, 20)

  renderer = new THREE.WebGLRenderer({ canvas: canvas.value, antialias: true })
  renderer.setSize(w, h)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.shadowMap.enabled = true
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.3

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05
  controls.zoomSpeed = 0.3
  controls.minDistance = 5
  controls.maxDistance = 25
  controls.maxPolarAngle = 1.5
  controls.target.set(0, 0, 0)

  clock = new THREE.Clock()

  // 优化灯光系统
  const ambientLight = new THREE.AmbientLight(0x1a2a4a, 0.6)
  scene.add(ambientLight)

  // 主方向光 - 模拟月光效果
  const dirLight = new THREE.DirectionalLight(0x4fc3f7, 0.8)
  dirLight.position.set(8, 20, 10)
  dirLight.castShadow = true
  scene.add(dirLight)

  // 补光 - 暖色调
  const fillLight = new THREE.DirectionalLight(0xffd740, 0.3)
  fillLight.position.set(-5, 10, -5)
  scene.add(fillLight)

  // 底部环境光
  const hemiLight = new THREE.HemisphereLight(0x4fc3f7, 0x0a1628, 0.4)
  scene.add(hemiLight)

  // 点光源 - 营造氛围
  const pointLight1 = new THREE.PointLight(0x00e5ff, 0.8, 20)
  pointLight1.position.set(0, 8, 0)
  scene.add(pointLight1)

  const pointLight2 = new THREE.PointLight(0x7c4dff, 0.4, 15)
  pointLight2.position.set(-5, 3, 5)
  scene.add(pointLight2)

  raycaster = new THREE.Raycaster()
  mouse = new THREE.Vector2()

  buildMap()
  buildMirror()
  buildBeamLights()
  buildParticles()
  canvas.value.addEventListener('mousemove', onMouseMove)
  window.addEventListener('resize', onResize)
  animate()
  playEntrance()
}

/* ── 地图构建 ── */
function buildMap() {
  // 外层: 固定缩放 + 旋转 (初始较大，动画结束后缩小)
  mapGroup = new THREE.Group()
  mapGroup.rotation.x = -Math.PI / 2
  mapGroup.scale.set(0.35, 0.35, 0.35)

  // 内层: 入场动画控制
  innerGroup = new THREE.Group()
  innerGroup.scale.set(1, 1, 0)
  innerGroup.position.set(0, 0, -0.01)

  const depth = 3
  const serviceAreas = props.serviceAreas || []

  // 1. 各服务区
  regionsData.features.forEach(feature => {
    const regionName = feature.properties.name
    const regionColor = REGION_COLORS[regionName] || 0x8fc2ff
    const c = new THREE.Color(regionColor)

    let polygons = feature.geometry.type === 'MultiPolygon'
      ? feature.geometry.coordinates
      : [feature.geometry.coordinates]

    polygons.forEach(polyCoords => {
      const ring = polyCoords[0]
      const shapePoints = []
      ring.forEach(([lon, lat]) => {
        const [x, y] = projection([lon, lat])
        shapePoints.push(new THREE.Vector2(x, -y))
      })

      const shape = new THREE.Shape(shapePoints)
      const geometry = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false })

      // 半透明色块材质 - 增强发光效果
      const regionMat = new THREE.MeshPhysicalMaterial({
        color: regionColor,
        emissive: regionColor,
        emissiveIntensity: 0.6,
        metalness: 0.3,
        roughness: 0.4,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: -1,
        polygonOffsetUnits: -1,
        depthWrite: false,
        clearcoat: 0.3,
        clearcoatRoughness: 0.2
      })

      const mesh = new THREE.Mesh(geometry, regionMat)
      mesh.castShadow = true
      mesh.receiveShadow = true
      mesh.userData = {
        type: 'region', name: regionName, regionColor,
        areaData: serviceAreas.find(a => {
          const n = a.area || ''
          return n.includes(regionName) || regionName.includes(n) ||
            (regionName === 'Capital District' && n.includes('Capital')) ||
            (regionName === 'Mid-Hudson' && n.includes('Hudson'))
        })
      }
      innerGroup.add(mesh)
      interactiveObjects.push(mesh)

      // 不添加边缘线，避免白色轮廓
    })

    // 区域中心
    const allCoords = []
    polygons.forEach(p => p[0].forEach(c => allCoords.push(c)))
    const centerLon = allCoords.reduce((s, c) => s + c[0], 0) / allCoords.length
    const centerLat = allCoords.reduce((s, c) => s + c[1], 0) / allCoords.length
    const [cx, cy] = projection([centerLon, centerLat])
    regionCenters.push({
      name: regionName, x: cx, y: -cy, color: regionColor,
      data: serviceAreas.find(a => {
        const n = a.area || ''
        return n.includes(regionName) || regionName.includes(n)
      })
    })
  })

  // 2. 纽约州外轮廓 + 边界渐变
  const features = nyStateData.features || [nyStateData]
  features.forEach(feature => {
    let rings = feature.geometry.type === 'MultiPolygon'
      ? feature.geometry.coordinates.map(p => p[0])
      : [feature.geometry.coordinates[0]]

    rings.forEach(ring => {
      const shapePoints = []
      ring.forEach(([lon, lat]) => {
        const [x, y] = projection([lon, lat])
        shapePoints.push(new THREE.Vector2(x, -y))
        boundaryPoints.push(new THREE.Vector3(x, 0, -y))
      })

      // 外轮廓线 (用于加载动画)
      const outlinePts = shapePoints.map(p => new THREE.Vector3(p.x, p.y, 0.01))
      const outlineGeo = new THREE.BufferGeometry().setFromPoints(outlinePts)
      const outlineMat = new THREE.LineDashedMaterial({
        color: 0x8fc2ff, transparent: true, opacity: 0,
        dashSize: 2, gapSize: 1, depthTest: false
      })
      outlineLine = new THREE.Line(outlineGeo, outlineMat)
      outlineLine.computeLineDistances()
      outlineLine.renderOrder = 100
      innerGroup.add(outlineLine)
    })
  })

  // 3. Cones
  regionCenters.forEach(rc => {
    // 找到对应的服务区数据
    const areaData = serviceAreas.find(a => {
      const n = a.area || ''
      return n.includes(rc.name) || rc.name.includes(n) ||
        (rc.name === 'Capital District' && n.includes('Capital')) ||
        (rc.name === 'Mid-Hudson' && n.includes('Hudson'))
    })

    const coneGeo = new THREE.ConeGeometry(0.6, 1.2, 4)
    const coneMat = new THREE.MeshBasicMaterial({
      color: rc.color, transparent: true, opacity: 0,
      side: THREE.DoubleSide
    })
    const cone = new THREE.Mesh(coneGeo, coneMat)
    cone.rotation.x = -Math.PI / 2
    cone.position.set(rc.x, depth + 0.5, rc.y)
    cone.userData.type = 'cone'
    cone.userData.name = rc.name
    cone.userData.areaData = areaData
    cone.userData.baseY = depth + 0.5
    cone.userData.dir = 1
    innerGroup.add(cone)

    const quanGeo = new THREE.PlaneGeometry(1.5, 1.5)
    const quanMat = new THREE.MeshBasicMaterial({
      color: rc.color, transparent: true, opacity: 0,
      depthTest: false, side: THREE.DoubleSide
    })
    const quan = new THREE.Mesh(quanGeo, quanMat)
    quan.position.set(rc.x, depth + 0.7, rc.y)
    quan.userData.type = 'quan'
    innerGroup.add(quan)
  })

  mapGroup.add(innerGroup)
  scene.add(mapGroup)
}

/* ── 镜面地板 ── */
function buildMirror() {
  // 主地板 - 深色渐变效果
  const mirrorGeo = new THREE.PlaneGeometry(60, 60)
  const mirrorMat = new THREE.MeshStandardMaterial({
    color: 0x0a1628,
    metalness: 0.85,
    roughness: 0.15,
    envMapIntensity: 0.5
  })
  const mirror = new THREE.Mesh(mirrorGeo, mirrorMat)
  mirror.rotation.x = -Math.PI / 2
  mirror.position.y = -0.05
  mirror.receiveShadow = true
  scene.add(mirror)

  // 网格线
  const gridHelper = new THREE.GridHelper(40, 40, 0x00e5ff, 0x0a2a5e)
  gridHelper.position.y = -0.04
  gridHelper.material.opacity = 0.15
  gridHelper.material.transparent = true
  scene.add(gridHelper)

  // 外圈发光环
  const ringGeo = new THREE.RingGeometry(8, 8.1, 64)
  const ringMat = new THREE.MeshBasicMaterial({
    color: 0x00e5ff,
    transparent: true,
    opacity: 0.3,
    side: THREE.DoubleSide
  })
  const ring = new THREE.Mesh(ringGeo, ringMat)
  ring.rotation.x = -Math.PI / 2
  ring.position.y = -0.03
  scene.add(ring)
}

/* ── 浮升光柱 ── */
function buildBeamLights() {
  effectGroup = new THREE.Group()
  const range = 10

  const beamColors = [0x00e5ff, 0x4fc3f7, 0x7c4dff, 0xffd740]

  for (let i = 0; i < 25; i++) {
    const geo = new THREE.CylinderGeometry(0.01, 0.01, 1, 6, 1, true)
    const color = beamColors[Math.floor(Math.random() * beamColors.length)]
    const mat = new THREE.ShaderMaterial({
      vertexShader: beamVertexShader,
      fragmentShader: beamFragmentShader,
      transparent: true, depthWrite: false, side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      uniforms: {
        uColor: { value: new THREE.Color(color) },
        uOpacity: { value: 0 }
      }
    })
    const beam = new THREE.Mesh(geo, mat)
    beam.position.set(
      (Math.random() - 0.5) * range,
      1 - Math.random() * 3,
      (Math.random() - 0.5) * range
    )
    beam.scale.y = 2.0 + Math.random() * 3.0
    beam.userData.speed = 1.5 + Math.random()
    beam.userData.resetHeight = 5 + Math.random() * 10
    beam.userData.type = 'beamLight'
    beam.userData.targetOpacity = 0.2 + Math.random() * 0.15
    effectGroup.add(beam)
  }
  scene.add(effectGroup)
}

/* ── 环境粒子 ── */
function buildParticles() {
  const particleCount = 200
  const positions = new Float32Array(particleCount * 3)
  const colors = new Float32Array(particleCount * 3)

  for (let i = 0; i < particleCount; i++) {
    positions[i * 3] = (Math.random() - 0.5) * 30
    positions[i * 3 + 1] = Math.random() * 15
    positions[i * 3 + 2] = (Math.random() - 0.5) * 30

    const color = new THREE.Color().setHSL(0.55 + Math.random() * 0.1, 0.8, 0.6)
    colors[i * 3] = color.r
    colors[i * 3 + 1] = color.g
    colors[i * 3 + 2] = color.b
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))

  const material = new THREE.PointsMaterial({
    size: 0.05,
    vertexColors: true,
    transparent: true,
    opacity: 0.6,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  })

  const particles = new THREE.Points(geometry, material)
  particles.userData.type = 'particles'
  scene.add(particles)
}

/* ── 鼠标交互 ── */
function onMouseMove(e) {
  const rect = canvas.value.getBoundingClientRect()
  mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1

  raycaster.setFromCamera(mouse, camera)

  // 使用递归检测，包括所有子对象
  const intersects = raycaster.intersectObjects([mapGroup], true)

  if (intersects.length > 0) {
    const mesh = intersects[0].object
    if (mesh.userData && (mesh.userData.type === 'region' || mesh.userData.type === 'cone')) {
      hoveredObject = mesh
      const area = mesh.userData.areaData
      if (area) {
        tooltip.value = {
          show: true,
          x: e.clientX - wrap.value.getBoundingClientRect().left + 15,
          y: e.clientY - wrap.value.getBoundingClientRect().top - 10,
          name: mesh.userData.name,
          cases: (area.cases || 0).toLocaleString(),
          cost: (area.avg_charges || 0).toLocaleString(),
          los: area.avg_los || '-'
        }
      } else {
        tooltip.value.show = false
      }
    } else {
      hoveredObject = null
      tooltip.value.show = false
    }
  } else {
    hoveredObject = null
    tooltip.value.show = false
  }
}

/* ── 入场动画: 加载线扫描 → 地图拔起 → 材质渐显 ── */
function playEntrance() {
  // 初始: 所有材质不可见
  innerGroup.traverse(obj => {
    if (!obj.material) return
    obj.material.opacity = 0
    obj.material.transparent = true
  })
  effectGroup?.traverse(child => {
    if (child.material && child.material.uniforms && child.material.uniforms.uOpacity) {
      child.material.uniforms.uOpacity.value = 0
    }
  })

  const tl = gsap.timeline()

  // 1) 相机飞入
  tl.to(camera.position, {
    x: 0, y: 8, z: 12,
    duration: 2.5,
    ease: 'circ.out'
  })

  // 2) 加载线: 先淡入，然后通过 dashOffset 动画产生移动效果
  if (outlineLine) {
    outlineLine.material.dashOffset = 0
    tl.to(outlineLine.material, { opacity: 0.8, duration: 0.5 }, 0)
    tl.to(outlineLine.material, { dashOffset: -100, duration: 2, ease: 'none' }, 0)
  }

  // 3) 2s 后: 地图拔起 (scale.z 0→1)
  tl.to(innerGroup.scale, {
    x: 1, y: 1, z: 1,
    duration: 1.5,
    ease: 'circ.out'
  }, 2)

  tl.to(innerGroup.position, {
    x: 0, y: 0, z: 0,
    duration: 1.5
  }, 2)

  // 4) 2s 后: 加载线淡出
  if (outlineLine) {
    tl.to(outlineLine.material, { opacity: 0, duration: 0.5 }, 2)
  }

  // 5) 2s 后: 材质渐显 (半透明)
  tl.add(() => {
    innerGroup.traverse(obj => {
      if (!obj.material) return
      // Cones 和 quan 使用更高的透明度
      const targetOpacity = obj.userData.type === 'cone' ? 0.9 :
                           obj.userData.type === 'quan' ? 0.8 : 0.7
      gsap.to(obj.material, { opacity: targetOpacity, duration: 1, ease: 'circ.out' })
    })
  }, 2)

  // 6) 3s 后: 光柱渐显
  animTimer = setTimeout(() => {
    effectGroup?.traverse(child => {
      if (child.material && child.material.uniforms && child.material.uniforms.uOpacity) {
        gsap.to(child.material.uniforms.uOpacity, {
          value: child.userData.targetOpacity || 0.3,
          duration: 1, ease: 'circ.out'
        })
      }
    })
  }, 3000)

  // 7) 3.5s 后: 通知父组件动画完成，触发面板滑入，同时地图缩小
  setTimeout(() => {
    emit('animationDone')
    // 地图缩放从 0.35 平滑变为 0.2
    gsap.to(mapGroup.scale, {
      x: 0.2, y: 0.2, z: 0.2,
      duration: 1,
      ease: 'power2.inOut'
    })
  }, 3500)
}

/* ── 动画循环 ── */
function animate() {
  requestAnimationFrame(animate)
  const delta = clock.getDelta()
  const t = clock.getElapsedTime()
  controls.update()

  // Hover: scale.z 平滑插值
  interactiveObjects.forEach(obj => {
    const target = obj === hoveredObject ? 1.5 : 1
    obj.scale.z += (target - obj.scale.z) * 0.1
  })

  // Cones 浮动
  innerGroup?.traverse(child => {
    if (child.userData.type === 'cone') {
      child.rotation.y += delta
      child.position.y += child.userData.dir * delta * 0.3
      if (child.position.y > child.userData.baseY + 0.5) child.userData.dir = -1
      if (child.position.y < child.userData.baseY) child.userData.dir = 1
    }
    if (child.userData.type === 'quan') {
      child.rotation.z += delta * 0.5
    }
  })

  // BeamLight 浮升
  effectGroup?.children.forEach(beam => {
    beam.position.y += beam.userData.speed * delta
    if (beam.position.y > beam.userData.resetHeight) {
      beam.position.x = (Math.random() - 0.5) * 10
      beam.position.z = (Math.random() - 0.5) * 10
      beam.position.y = 1 - Math.random() * 3
      beam.scale.y = 2.0 + Math.random() * 3.0
    }
  })

  // 粒子动画
  scene.children.forEach(child => {
    if (child.userData.type === 'particles') {
      child.rotation.y += delta * 0.02
      const positions = child.geometry.attributes.position.array
      for (let i = 0; i < positions.length; i += 3) {
        positions[i + 1] += Math.sin(t + i) * 0.001
      }
      child.geometry.attributes.position.needsUpdate = true
    }
  })

  renderer.render(scene, camera)
}

function onResize() {
  const el = wrap.value
  if (!el) return
  const w = el.clientWidth, h = el.clientHeight
  camera.aspect = w / h
  camera.updateProjectionMatrix()
  renderer.setSize(w, h)
}

// 当 serviceAreas 数据异步到达时，更新已有 mesh 的 areaData
watch(() => props.serviceAreas, (areas) => {
  if (!areas || areas.length === 0) return
  innerGroup?.traverse(obj => {
    if (obj.userData && obj.userData.type === 'region' && !obj.userData.areaData) {
      obj.userData.areaData = areas.find(a => {
        const n = a.area || ''
        const rn = obj.userData.name
        return n.includes(rn) || rn.includes(n) ||
          (rn === 'Capital District' && n.includes('Capital')) ||
          (rn === 'Mid-Hudson' && n.includes('Hudson'))
      })
    }
  })
  // 同时更新 regionCenters 的 data
  regionCenters.forEach(rc => {
    if (!rc.data) {
      rc.data = areas.find(a => {
        const n = a.area || ''
        return n.includes(rc.name) || rc.name.includes(n) ||
          (rc.name === 'Capital District' && n.includes('Capital')) ||
          (rc.name === 'Mid-Hudson' && n.includes('Hudson'))
      })
    }
  })
}, { immediate: true })

onMounted(() => { nextTick(() => init()) })
onBeforeUnmount(() => {
  clearTimeout(animTimer)
  canvas?.value?.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('resize', onResize)
  renderer?.dispose()
  controls?.dispose()
})
</script>

<style scoped>
.map3d-wrap {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
}
.map3d-canvas {
  width: 100% !important;
  height: 100% !important;
  display: block;
}
.map-tooltip {
  position: absolute;
  pointer-events: none;
  background: rgba(0, 0, 0, 0.9);
  border: 1px solid rgba(143, 194, 255, 0.5);
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 12px;
  color: #8fc2ff;
  box-shadow: 0 0 20px rgba(143, 194, 255, 0.3), inset 0 0 15px rgba(143, 194, 255, 0.05);
  z-index: 10;
  backdrop-filter: blur(4px);
}
.tip-title { font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 6px; border-bottom: 1px solid rgba(143, 194, 255, 0.2); padding-bottom: 4px; }
.tip-row { display: flex; justify-content: space-between; gap: 20px; line-height: 2; }
.tip-label { color: rgba(143, 194, 255, 0.7); }
.tip-value { color: #fff; font-weight: 600; }
</style>
