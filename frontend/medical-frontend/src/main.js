import { createApp } from 'vue'
import * as echarts from 'echarts'
import App from './App.vue'
import router from './router'

// 统一图表字体（中文优先，跨平台回退），所有图表 init 时用 'medical' 主题
echarts.registerTheme('medical', {
  textStyle: {
    fontFamily:
      '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "微软雅黑", ' +
      '"Noto Sans CJK SC", "WenQuanYi Micro Hei", "Source Han Sans CN", sans-serif',
  },
})

createApp(App).use(router).mount('#app')
