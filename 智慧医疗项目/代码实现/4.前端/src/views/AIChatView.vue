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
        <div class="content" v-html="msg.content.replace(/\n/g, '<br>')"></div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <input
        v-model="inputText"
        @keydown.enter="sendMessage"
        :placeholder="mode === 'general' ? '问医疗相关的问题，如：2024年呼吸系统疾病住院趋势？' : '输入数据查询问题，如：2021年住院人数最多的疾病？'"
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
import { ref, nextTick, onMounted } from 'vue'

// ====== 在这里填你的 DeepSeek API Key（仅通用模式使用） ======
const API_KEY = 'sk-328b5a9db46944e4bb599f79bf6bf3c5'

// ====== 状态 ======
const messages = ref([
  { role: 'assistant', content: '👋 我是医疗数据分析助手。💬 通用模式：日常问答；📊 数据模式：查询真实医疗数据。' }
])
const inputText = ref('')
const loading = ref(false)
const chatBoxRef = ref(null)

// ====== 模式切换 ======
const mode = ref('general')  // 'general' 或 'data'

const toggleMode = () => {
  mode.value = mode.value === 'general' ? 'data' : 'general'
}

// ====== 快捷问题 ======
const suggestions = ref([
  '2024年呼吸系统疾病住院趋势？',
  '哪个县医疗费用最高？',
  '医保支付占比是多少？'
])

const scrollToBottom = () => {
  nextTick(() => {
    const el = chatBoxRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
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
    if (mode.value === 'general') {
      // ====== 通用模式：调 DeepSeek ======
      const history = messages.value.slice(-6).map(m => ({
        role: m.role,
        content: m.content
      }))

      const response = await fetch('https://api.deepseek.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${API_KEY}`
        },
        body: JSON.stringify({
          model: 'deepseek-chat',
          messages: [
            { role: 'system', content: '你是医疗数据分析助手，基于纽约州SPARCS住院数据回答问题。中文回答，简洁专业。' },
            ...history
          ],
          stream: true,
          max_tokens: 2048,
          temperature: 0.7
        })
      })

      if (!response.ok) {
        const err = await response.text()
        throw new Error(`API错误(${response.status}): ${err}`)
      }

      // 处理流式响应
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let reply = ''
      messages.value.push({ role: 'assistant', content: '' })
      const lastIdx = messages.value.length - 1

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n').filter(line => line.startsWith('data: '))

        for (const line of lines) {
          const payload = line.replace('data: ', '').trim()
          if (payload === '[DONE]') continue
          try {
            const json = JSON.parse(payload)
            const content = json.choices[0]?.delta?.content
            if (content) {
              reply += content
              messages.value[lastIdx].content = reply
              scrollToBottom()
            }
          } catch (_) {}
        }
      }

    } else {
      // ====== 数据模式：调 P4 ======
      const response = await fetch('http://192.168.247.128:5001/api/chat', {
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
        messages.value.push({ role: 'assistant', content: result.answer })
        // 如果有图表数据，打印到控制台供调试
        if (result.chart) {
          console.log('📊 图表配置:', result.chart)
        }
      } else {
        messages.value.push({ role: 'assistant', content: `❌ 数据服务异常：${result.message || '请确认 P4 服务已启动'}` })
      }
    }

  } catch (err) {
    messages.value.push({
      role: 'assistant',
      content: `❌ 请求失败：${err.message}。${mode.value === 'general' ? '请检查 API Key 是否正确。' : '请确认 P4 服务已启动（http://192.168.247.128:5001）。'}`
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

const quickAsk = (q) => {
  inputText.value = q
  sendMessage()
}

onMounted(scrollToBottom)
</script>

<style scoped>
/* ====== 整体布局 ====== */
.ai-page {
  padding: 24px 32px 20px;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: radial-gradient(ellipse at center, #0a2a5e 0%, #051633 50%, #020e2a 100%);
  color: #e3f2fd;
  font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
  position: relative;
}
.ai-page::before {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    radial-gradient(1px 1px at 10% 20%, #4fc3f7 50%, transparent),
    radial-gradient(1px 1px at 30% 80%, #4dd0e1 50%, transparent),
    radial-gradient(1px 1px at 60% 40%, #81d4fa 50%, transparent),
    radial-gradient(2px 2px at 80% 70%, #29b6f6 50%, transparent),
    radial-gradient(1px 1px at 45% 55%, #4fc3f7 50%, transparent);
  background-size: 600px 600px;
  opacity: 0.4;
}

/* ====== 顶部导航 ====== */
.page-header {
  position: relative; z-index: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 900px;
  width: 100%;
  margin: 0 auto 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(64,196,255,0.2);
}
.page-header h2 {
  font-size: 24px; font-weight: bold;
  background: linear-gradient(180deg, #ffffff 0%, #4fc3f7 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: 3px;
  text-shadow: 0 0 20px rgba(64,196,255,0.4);
}
.back-btn {
  background: rgba(0,229,255,0.12);
  border: 1px solid rgba(0,229,255,0.5);
  color: #00e5ff;
  padding: 8px 18px; border-radius: 4px;
  cursor: pointer; font-size: 13px;
  letter-spacing: 1px;
  transition: all 0.3s;
}
.back-btn:hover {
  background: rgba(0,229,255,0.25);
  box-shadow: 0 0 16px rgba(0,229,255,0.5);
}

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
  background: rgba(0,229,255,0.05);
  padding: 4px 10px 4px 14px;
  border-radius: 24px;
  border: 1px solid rgba(64,196,255,0.2);
}
.mode-label {
  font-size: 13px;
  color: #7da3d4;
  cursor: pointer;
  transition: color 0.3s;
  user-select: none;
}
.mode-label.active {
  color: #00e5ff;
  font-weight: bold;
  text-shadow: 0 0 8px rgba(0,229,255,0.6);
}
.switch-track {
  width: 36px;
  height: 20px;
  background: rgba(64,196,255,0.2);
  border-radius: 10px;
  cursor: pointer;
  position: relative;
  transition: background 0.3s;
  flex-shrink: 0;
}
.switch-thumb {
  width: 14px;
  height: 14px;
  background: #4fc3f7;
  border-radius: 50%;
  position: absolute;
  top: 3px;
  left: 3px;
  transition: transform 0.3s, background 0.3s, box-shadow 0.3s;
}
.switch-thumb.data-mode {
  transform: translateX(16px);
  background: #00e5ff;
  box-shadow: 0 0 10px rgba(0,229,255,0.8);
}

/* ====== 状态标签 ====== */
.status {
  font-size: 12px;
  padding: 3px 14px;
  border-radius: 20px;
  letter-spacing: 1px;
  border: 1px solid;
}
.status.ready   { color: #69f0ae; background: rgba(105,240,174,0.1); border-color: rgba(105,240,174,0.4); }
.status.loading { color: #ffd740; background: rgba(255,215,64,0.1); border-color: rgba(255,215,64,0.4); }

/* ====== 聊天框 ====== */
.chat-box {
  flex: 1;
  position: relative; z-index: 1;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
  background: rgba(8, 24, 56, 0.55);
  border: 1px solid rgba(64,196,255,0.25);
  border-radius: 4px;
  padding: 20px 24px;
  box-shadow: inset 0 0 30px rgba(0,150,255,0.08);
  overflow-y: auto;
  max-height: 55vh;
  min-height: 300px;
}
.chat-box::before, .chat-box::after {
  content: ""; position: absolute; width: 14px; height: 14px;
  border-color: #00e5ff; border-style: solid; border-width: 0;
}
.chat-box::before { top: 0; left: 0; border-top-width: 2px; border-left-width: 2px; }
.chat-box::after  { bottom: 0; right: 0; border-bottom-width: 2px; border-right-width: 2px; }
.chat-box::-webkit-scrollbar { width: 6px; }
.chat-box::-webkit-scrollbar-thumb { background: rgba(0,229,255,0.3); border-radius: 3px; }
.chat-box::-webkit-scrollbar-track { background: transparent; }

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.message .avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(0,229,255,0.15);
  border: 1px solid rgba(0,229,255,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.message .content {
  background: rgba(64,196,255,0.08);
  border: 1px solid rgba(64,196,255,0.15);
  padding: 10px 16px;
  border-radius: 4px;
  max-width: 80%;
  line-height: 1.7;
  font-size: 14px;
  color: #e3f2fd;
}
.message.user { flex-direction: row-reverse; }
.message.user .content {
  background: rgba(0,229,255,0.2);
  border-color: rgba(0,229,255,0.5);
  color: #ffffff;
  box-shadow: 0 0 12px rgba(0,229,255,0.2);
}
.message.assistant .content { background: rgba(8, 24, 56, 0.6); }

/* ====== 输入区 ====== */
.input-area {
  position: relative; z-index: 1;
  max-width: 900px;
  width: 100%;
  margin: 14px auto 0;
  display: flex;
  gap: 10px;
}
.input-area input {
  flex: 1;
  padding: 10px 16px;
  background: rgba(8, 24, 56, 0.6);
  border: 1px solid rgba(64,196,255,0.3);
  border-radius: 4px;
  font-size: 14px;
  color: #e3f2fd;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-area input::placeholder { color: #5d7ba8; }
.input-area input:focus {
  border-color: #00e5ff;
  box-shadow: 0 0 12px rgba(0,229,255,0.3);
}
.input-area button {
  padding: 10px 28px;
  background: rgba(0,229,255,0.15);
  color: #00e5ff;
  border: 1px solid rgba(0,229,255,0.6);
  border-radius: 4px;
  font-size: 14px;
  font-weight: bold;
  letter-spacing: 2px;
  cursor: pointer;
  transition: all 0.3s;
}
.input-area button:hover:not(:disabled) {
  background: rgba(0,229,255,0.3);
  box-shadow: 0 0 20px rgba(0,229,255,0.6);
}
.input-area button:disabled { opacity: 0.4; cursor: not-allowed; }

/* ====== 快捷问题 ====== */
.suggestions {
  position: relative; z-index: 1;
  max-width: 900px;
  width: 100%;
  margin: 12px auto 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.suggestion {
  background: rgba(64,196,255,0.08);
  border: 1px solid rgba(64,196,255,0.25);
  padding: 5px 14px;
  border-radius: 20px;
  font-size: 12px;
  color: #7da3d4;
  cursor: pointer;
  transition: all 0.2s;
}
.suggestion:hover {
  background: rgba(0,229,255,0.2);
  border-color: rgba(0,229,255,0.6);
  color: #00e5ff;
  box-shadow: 0 0 12px rgba(0,229,255,0.3);
}
</style>