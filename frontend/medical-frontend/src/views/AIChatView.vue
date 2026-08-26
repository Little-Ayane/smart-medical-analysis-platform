<template>
  <div class="ai-page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>🤖 AI 智能助手</h2>
      <div class="header-right-group">
        <div class="mode-switch">
          <span class="mode-label" :class="{ active: mode === 'general' }" @click="mode = 'general'">💬 通用</span>
          <div class="switch-track" @click="toggleMode">
            <div class="switch-thumb" :class="{ 'data-mode': mode === 'data' }"></div>
          </div>
          <span class="mode-label" :class="{ active: mode === 'data' }" @click="mode = 'data'">📊 数据</span>
        </div>
        <span class="status" :class="loading ? 'loading' : 'ready'">
          {{ loading ? '思考中...' : '就绪' }}
        </span>
      </div>
    </div>

    <!-- 聊天消息区 -->
    <div class="chat-box" ref="chatBoxRef">
      <div v-for="(msg, idx) in messages" :key="idx" class="message" :class="msg.role">
        <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="msg-body">
          <div class="content" v-html="msg.content.replace(/\n/g, '<br>')"></div>
          <div v-if="msg.chart" :id="`chart-${idx}`" class="chart-box"></div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <input
        v-model="inputText"
        @keydown.enter="sendMessage"
        :placeholder="mode === 'general' ? '问概念/知识类问题，如：什么是DRG付费？（通用模式不查数据库）' : '输入数据查询问题，如：2021年住院人数最多的疾病？（含图表）'"
        :disabled="loading"
      />
      <button @click="sendMessage" :disabled="loading || !inputText.trim()">
        {{ loading ? '⏳' : '发送' }}
      </button>
    </div>

    <!-- 快捷问题 -->
    <div class="suggestions">
      <span class="suggestion" v-for="q in suggestions" :key="q" @click="quickAsk(q)">
        {{ q }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

// ====== P4 AI 服务地址（通用 / 数据 两种模式都走这里，端口 5001）======
// 用 window.location.hostname 自适应本机 / 局域网访问（不用硬编码 127.0.0.1）
const AI_HOST = window.location.hostname || '127.0.0.1'
const AI_BASE = `http://${AI_HOST}:5001`

// ====== 状态 ======
const messages = ref([
  { role: 'assistant', content: '👋 我是医疗数据分析助手。💬 通用模式：日常问答；📊 数据模式：查询真实医疗数据。' }
])
const inputText = ref('')
const loading = ref(false)
const chatBoxRef = ref(null)
const chartInstances = new Map()  // idx -> echarts 实例（用于 dispose / resize）

// ====== 模式切换 ======
const mode = ref('general')  // 'general' 或 'data'

const toggleMode = () => {
  mode.value = mode.value === 'general' ? 'data' : 'general'
}

// ====== 快捷问题（数据模式代表性问法，覆盖疾病排行/支付占比/地区分布）======
const suggestions = ref([
  '2021年住院人数最多的10种疾病？',
  '各支付方式的占比分布？',
  '各地区住院人数分布排名？'
])

const scrollToBottom = () => {
  nextTick(() => {
    const el = chatBoxRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// ====== 渲染 ECharts 图表 ======
const renderCharts = () => {
  nextTick(() => {
    messages.value.forEach((msg, idx) => {
      if (!msg.chart) return
      const el = document.getElementById(`chart-${idx}`)
      if (!el) return
      // 已渲染过则只更新 option（避免重复 init）
      if (chartInstances.has(idx)) {
        chartInstances.get(idx).setOption(msg.chart, true)
        return
      }
      const chart = echarts.init(el, 'medical')
      chart.setOption(msg.chart)
      chartInstances.set(idx, chart)
    })
  })
}

const handleResize = () => {
  chartInstances.forEach((c) => c.resize())
}

// ====== 发送消息 ======
const sendMessage = async () => {
  const text = inputText.value.trim()
  if (!text || loading.value) return

  // 添加用户消息
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  scrollToBottom()
  loading.value = true

  try {
    const history = messages.value.slice(-6).map(m => ({
      role: m.role,
      content: m.content
    }))

    if (mode.value === 'general') {
      // ====== 通用模式：走 P4 的 /api/general-chat（SiliconFlow LLM）======
      const response = await fetch(`${AI_BASE}/api/general-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, history })
      })
      const result = await response.json()
      if (result.code === 0) {
        messages.value.push({ role: 'assistant', content: result.answer })
      } else {
        messages.value.push({ role: 'assistant', content: `❌ 通用问答异常：${result.message || '请确认 AI 服务已启动'}` })
      }

    } else {
      // ====== 数据模式：走 P4 的 /api/chat ======
      const response = await fetch(`${AI_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text,
          with_report: false,
          conversation_id: null
        })
      })
      const result = await response.json()
      if (result.code === 0) {
        const msg = { role: 'assistant', content: result.answer }
        // 有图表配置（ECharts option）时随消息一起渲染
        if (result.chart && result.chart.option) {
          msg.chart = result.chart.option
        }
        messages.value.push(msg)
      } else {
        messages.value.push({ role: 'assistant', content: `❌ 数据服务异常：${result.message || '请确认 AI 服务已启动'}` })
      }
    }

  } catch (err) {
    messages.value.push({
      role: 'assistant',
      content: `❌ 请求失败：${err.message}。请确认 AI 服务已启动（${AI_BASE}）。`
    })
  } finally {
    loading.value = false
    scrollToBottom()
    renderCharts()
  }
}

const quickAsk = (q) => {
  inputText.value = q
  sendMessage()
}

onMounted(() => {
  scrollToBottom()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstances.forEach((c) => c.dispose())
  chartInstances.clear()
})
</script>

<style scoped>
/* ====== 整体布局 ====== */
.ai-page {
  padding: 24px 32px 20px;
  background: #f0f4f8;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* ====== 顶部导航 ====== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 900px;
  width: 100%;
  margin: 0 auto 16px;
}
.page-header h2 { font-size: 22px; color: #1a2a3a; }
.back-btn {
  background: #e8ecf1;
  border: none;
  padding: 6px 18px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}
.back-btn:hover { background: #d0d7e2; }

.header-right-group {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* ====== 模式切换开关 ====== */
.mode-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(0,0,0,0.04);
  padding: 4px 10px 4px 14px;
  border-radius: 24px;
  border: 1px solid rgba(0,0,0,0.06);
}
.mode-label {
  font-size: 13px;
  color: #7a8a9a;
  cursor: pointer;
  transition: color 0.3s;
  user-select: none;
}
.mode-label.active {
  color: #1a2a3a;
  font-weight: 600;
}
.switch-track {
  width: 36px;
  height: 20px;
  background: #d0d7e2;
  border-radius: 10px;
  cursor: pointer;
  position: relative;
  transition: background 0.3s;
  flex-shrink: 0;
}
.switch-thumb {
  width: 14px;
  height: 14px;
  background: #4A90D9;
  border-radius: 50%;
  position: absolute;
  top: 3px;
  left: 3px;
  transition: transform 0.3s, background 0.3s;
}
.switch-thumb.data-mode {
  transform: translateX(16px);
  background: #7b61ff;
}

/* ====== 状态标签 ====== */
.status {
  font-size: 13px;
  padding: 2px 14px;
  border-radius: 20px;
}
.status.ready { color: #4CAF50; background: #e8f5e9; }
.status.loading { color: #F5A623; background: #fff8e1; }

/* ====== 聊天框 ====== */
.chat-box {
  flex: 1;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
  background: #fff;
  border-radius: 14px;
  padding: 20px 24px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  overflow-y: auto;
  max-height: 55vh;
  min-height: 300px;
}
.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.message .avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #e8ecf1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.message .msg-body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  max-width: 80%;
}
.message.user .msg-body { align-items: flex-end; }
.message .content {
  background: #f5f7fa;
  padding: 10px 16px;
  border-radius: 12px;
  line-height: 1.7;
  font-size: 14px;
  color: #1a2a3a;
  word-break: break-word;
}
.chart-box {
  width: 100%;
  min-width: 320px;
  height: 320px;
  margin-top: 10px;
}
.message.user { flex-direction: row-reverse; }
.message.user .content { background: #1a4a7a; color: #fff; }
.message.assistant .content { background: #f0f4fa; }

/* ====== 输入区 ====== */
.input-area {
  max-width: 900px;
  width: 100%;
  margin: 14px auto 0;
  display: flex;
  gap: 10px;
}
.input-area input {
  flex: 1;
  padding: 10px 16px;
  border: 1px solid #d0d7e2;
  border-radius: 10px;
  font-size: 14px;
  outline: none;
}
.input-area input:focus { border-color: #1a4a7a; }
.input-area button {
  padding: 10px 28px;
  background: #1a4a7a;
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.input-area button:disabled { opacity: 0.5; cursor: not-allowed; }

/* ====== 快捷问题 ====== */
.suggestions {
  max-width: 900px;
  width: 100%;
  margin: 12px auto 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.suggestion {
  background: #e8ecf1;
  padding: 4px 14px;
  border-radius: 20px;
  font-size: 12px;
  cursor: pointer;
}
.suggestion:hover { background: #d0d7e2; }
</style>