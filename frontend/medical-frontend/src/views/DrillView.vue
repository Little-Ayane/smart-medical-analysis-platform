<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>🔍 多维下钻分析</h2>
      <span></span>
    </div>

    <div class="page-body">
      <!-- 面包屑：显示当前下钻路径，点击可回退 -->
      <div class="breadcrumb" v-if="breadcrumb.length">
        <span class="crumb" @click="resetAll">全部</span>
        <template v-for="(c, i) in breadcrumb" :key="i">
          <span class="sep">›</span>
          <span class="crumb" @click="jumpTo(i)">{{ dimLabel(c.level) }}：{{ fmtCell(c.value, c.level) }}</span>
        </template>
      </div>

      <!-- 下钻配置：全部下拉选择，无文本输入 -->
      <div class="drill-config">
        <div class="config-item">
          <label>📌 当前维度</label>
          <select v-model="currentLevel" @change="onLevelChange">
            <option v-for="d in drillDimensions" :key="d.name" :value="d.name">{{ d.label }}</option>
          </select>
        </div>
        <div class="config-item">
          <label>🎯 当前值</label>
          <select v-model="currentValue" :disabled="!currentValues.length">
            <option value="">请选择</option>
            <option v-for="v in currentValues" :key="String(v)" :value="v">{{ displayValue(currentLevel, v) }}</option>
          </select>
        </div>
        <div class="config-item">
          <label>⬇️ 下钻维度</label>
          <select v-model="drillTo">
            <option value="">请选择</option>
            <option v-for="d in drillDimensions" :key="d.name" :value="d.name"
                    :disabled="d.name === currentLevel">{{ d.label }}</option>
          </select>
        </div>
        <button class="query-btn" :disabled="loading" @click="runDrill">
          {{ loading ? '查询中…' : '🔍 查询' }}
        </button>
        <button class="reset-btn" @click="resetAll">重置</button>
      </div>

      <!-- 指标多选 -->
      <div class="metric-bar">
        <span class="metric-title">指标：</span>
        <label v-for="m in metricOptions" :key="m.name" class="metric-chip"
               :class="{ active: selectedMetrics.includes(m.name) }">
          <input type="checkbox" :value="m.name" v-model="selectedMetrics" />
          {{ m.label }}
        </label>
      </div>

      <!-- 错误提示 -->
      <div class="error-msg" v-if="errorMsg">{{ errorMsg }}</div>

      <!-- 结果表 -->
      <div class="drill-table" v-if="rows.length">
        <div class="table-caption">
          按「{{ dimLabel(drillTo) }}」分组
          <span class="total-hint">共 {{ rows.length }} 组</span>
        </div>
        <table>
          <thead>
            <tr>
              <th v-for="col in columns" :key="col">{{ colLabel(col) }}</th>
              <th class="op-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in rows" :key="idx">
              <td v-for="col in columns" :key="col">
                <span v-if="col === columns[0]" class="drill-link" @click="drillInto(row)">
                  {{ fmtCell(row[col], col) }}
                </span>
                <span v-else>{{ fmtCell(row[col], col) }}</span>
              </td>
              <td class="op-col">
                <button class="drill-btn" @click="drillInto(row)">下钻</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 空状态 / 加载状态 -->
      <div class="empty-state" v-else-if="loading">⏳ 正在加载元数据 / 执行查询…</div>
      <div class="empty-state" v-else>请选择当前维度、当前值、下钻维度与指标后，点击「查询」开始下钻分析。</div>
    </div>
  </div>
</template>

<script setup>
import api from '@/api'
import { ref, computed, onMounted } from 'vue'

// ---- 维度/指标中文标签（key 与后端 DIMENSION_MAP / METRIC_MAP 完全一致）----
const DIM_LABELS = {
  year: '年份', hospital_area: '服务区', hospital_county: '县', hospital_name: '机构',
  age_group: '年龄段', gender: '性别', race: '种族',
  severity_desc: '严重程度', risk_mortality: '死亡风险', medical_surgical: '内外科',
  payment_type: '支付方式', drg_desc: 'DRG 分组', mdc_desc: 'MDC 分类'
}
const METRIC_LABELS = {
  cases: '住院人次', total_charges: '总费用', avg_charges: '平均费用',
  total_costs: '总成本', avg_costs: '平均成本', avg_stay: '平均住院日',
  max_stay: '最长住院日', min_stay: '最短住院日', total_stay: '总住院日'
}
const MONEY_METRICS = new Set(['total_charges', 'avg_charges', 'total_costs', 'avg_costs'])
// 性别值显示映射（数据值为 M/F）
const GENDER_DISPLAY = { M: '男', F: '女' }

const drillDimensions = Object.keys(DIM_LABELS).map(name => ({ name, label: DIM_LABELS[name] }))
const metricOptions = Object.keys(METRIC_LABELS).map(name => ({ name, label: METRIC_LABELS[name] }))

// ---- 状态 ----
const metadata = ref(null)
const loading = ref(false)
const errorMsg = ref('')

const currentLevel = ref('year')
const currentValue = ref('')
const drillTo = ref('hospital_area')
const selectedMetrics = ref(['cases', 'total_charges', 'avg_charges'])

const breadcrumb = ref([])   // [{ level, value }] 祖先过滤链
const columns = ref([])
const rows = ref([])

// 当前维度的候选值（来自 metadata 全量 distinct，已过滤 null）
const currentValues = computed(() => {
  if (!metadata.value || !currentLevel.value) return []
  const info = metadata.value.dimensions?.[currentLevel.value]
  return (info?.values || []).filter(v => v !== null && v !== undefined)
})

function dimLabel(name) { return DIM_LABELS[name] || name }
function metricLabel(name) { return METRIC_LABELS[name] || name }
function colLabel(col) { return DIM_LABELS[col] || METRIC_LABELS[col] || col }

function displayValue(dim, v) {
  if (dim === 'gender') return GENDER_DISPLAY[v] || v
  return v
}

function fmtCell(v, col) {
  if (v === null || v === undefined || v === '') return '—'
  // 后端 Decimal 列会序列化为字符串，这里统一转数值再格式化
  const num = typeof v === 'number' ? v : (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v)) ? Number(v) : null)
  if (num !== null) {
    if (MONEY_METRICS.has(col)) {
      return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }
    return num.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  }
  return String(v)
}

// 面包屑 → 过滤字典（维度名 → 值）
function filtersFromBreadcrumb() {
  const f = {}
  for (const c of breadcrumb.value) f[c.level] = c.value
  return f
}

function onLevelChange() {
  // 切换维度时清空已选值
  currentValue.value = ''
}

async function loadMetadata() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api.getMetadata()
    metadata.value = res.data
  } catch (e) {
    errorMsg.value = '元数据加载失败：' + (e.response?.data?.detail || e.message)
  } finally {
    loading.value = false
  }
}

async function runDrill() {
  errorMsg.value = ''
  if (!currentLevel.value) { errorMsg.value = '请选择当前维度'; return }
  if (!currentValue.value && currentValue.value !== 0) { errorMsg.value = '请选择当前值'; return }
  if (!drillTo.value) { errorMsg.value = '请选择下钻维度'; return }
  if (!selectedMetrics.value.length) { errorMsg.value = '请至少选择一个指标'; return }

  loading.value = true
  try {
    const res = await api.getDrillDown({
      current_level: currentLevel.value,
      current_value: currentValue.value,
      drill_to: drillTo.value,
      metrics: selectedMetrics.value,
      filters: filtersFromBreadcrumb()
    })
    columns.value = res.data.columns
    rows.value = res.data.rows
  } catch (e) {
    errorMsg.value = '下钻查询失败：' + (e.response?.data?.detail || e.message)
    rows.value = []
  } finally {
    loading.value = false
  }
}

// 点击行 → 下钻到该值
function drillInto(row) {
  const val = row[columns.value[0]]
  if (val === null || val === undefined) return
  breadcrumb.value.push({ level: currentLevel.value, value: currentValue.value })
  currentLevel.value = drillTo.value
  currentValue.value = val
  drillTo.value = ''          // 清空，提示用户选择更深一级维度
  columns.value = []
  rows.value = []
}

// 点击面包屑第 i 层 → 回退到该层
function jumpTo(i) {
  const target = breadcrumb.value[i]
  breadcrumb.value = breadcrumb.value.slice(0, i)
  currentLevel.value = target.level
  currentValue.value = target.value
  drillTo.value = ''
  columns.value = []
  rows.value = []
}

function resetAll() {
  breadcrumb.value = []
  currentLevel.value = drillDimensions[0].name
  currentValue.value = ''
  drillTo.value = drillDimensions[1]?.name || ''
  columns.value = []
  rows.value = []
  errorMsg.value = ''
}

onMounted(loadMetadata)
</script>

<style scoped>
.page { padding: 30px 40px; background: #f5f7fa; min-height: 100vh; }
.page-header { display: flex; justify-content: space-between; align-items: center; max-width: 1200px; margin: 0 auto 20px; }
.page-header h2 { font-size: 24px; color: #1a2a3a; }
.back-btn { background: #e8ecf1; border: none; padding: 8px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; color: #1a2a3a; }
.back-btn:hover { background: #d0d7e2; }
.page-body { max-width: 1200px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 20px 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }

.breadcrumb { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; padding: 10px 14px; background: #f7f9fc; border: 1px solid #e6ecf3; border-radius: 8px; margin-bottom: 16px; font-size: 13px; }
.crumb { color: #4A90D9; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.crumb:hover { background: #e3ecf7; }
.sep { color: #b0b8c4; }

.drill-config { display: flex; flex-wrap: wrap; gap: 14px 18px; align-items: flex-end; margin-bottom: 14px; }
.config-item { display: flex; flex-direction: column; gap: 4px; }
.config-item label { font-size: 12px; color: #888; }
.config-item select { padding: 6px 10px; border: 1px solid #d0d7e2; border-radius: 6px; font-size: 13px; background: #fff; min-width: 150px; height: 34px; max-width: 260px; }
.config-item select:disabled { background: #f2f4f7; color: #999; cursor: not-allowed; }
.query-btn { padding: 6px 24px; background: #4A90D9; color: #fff; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; height: 34px; font-weight: 600; }
.query-btn:hover { background: #357abd; }
.query-btn:disabled { background: #a8c6e8; cursor: not-allowed; }
.reset-btn { padding: 6px 20px; background: #fff; color: #666; border: 1px solid #d0d7e2; border-radius: 6px; font-size: 14px; cursor: pointer; height: 34px; }
.reset-btn:hover { background: #f2f4f7; }

.metric-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; padding: 8px 0; border-top: 1px dashed #eef1f5; }
.metric-title { font-size: 13px; color: #666; }
.metric-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border: 1px solid #d0d7e2; border-radius: 20px; font-size: 12px; color: #555; cursor: pointer; user-select: none; }
.metric-chip input { cursor: pointer; }
.metric-chip.active { background: #e8f1fb; border-color: #4A90D9; color: #2f6cb3; }

.error-msg { margin: 10px 0; padding: 10px 14px; background: #fdecea; color: #c0392b; border-radius: 6px; font-size: 13px; }

.drill-table { margin-top: 8px; }
.table-caption { font-size: 13px; color: #555; margin-bottom: 8px; display: flex; justify-content: space-between; }
.total-hint { color: #999; font-size: 12px; }
.drill-table table { width: 100%; border-collapse: collapse; font-size: 13px; }
.drill-table th { background: #f5f7fa; padding: 9px 10px; text-align: left; font-weight: 600; color: #1a2a3a; border-bottom: 2px solid #e0e4ea; }
.drill-table td { padding: 8px 10px; border-bottom: 1px solid #eee; }
.drill-link { color: #4A90D9; cursor: pointer; text-decoration: underline; }
.drill-link:hover { color: #357abd; }
.op-col { width: 64px; text-align: center; }
.drill-btn { padding: 3px 12px; background: #4A90D9; color: #fff; border: none; border-radius: 4px; font-size: 12px; cursor: pointer; }
.drill-btn:hover { background: #357abd; }
.empty-state { margin-top: 24px; text-align: center; color: #999; font-size: 13px; padding: 30px 0; }
</style>
