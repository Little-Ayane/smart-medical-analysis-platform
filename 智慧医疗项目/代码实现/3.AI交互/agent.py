# -*- coding: utf-8 -*-
"""
P4 · AI 智能交互模块
功能：LangChain AI Agent —— 意图识别 -> 智能工具调用 -> 文本生成
技术：LangChain / LLM / Flask（HTTP服务封装）
说明：LLM 可切换云端模型或本地开源模型（Qwen/BaiChuan）
      一期：Flask HTTP 服务 + 规则意图解析 + 模板摘要兜底
      二期：接入 LangChain Agent + LLM 生成中文摘要 + 多轮对话
运行：
    1. 先启动 P3（端口 5000）
    2. 再启动 P4：python agent.py   →  http://127.0.0.1:5001
    3. P5 前端 POST →  http://127.0.0.1:5001/api/chat
"""
import json
import os
import time
import uuid

# ------------------------------------------------------------
# 0. 加载 .env 文件（python-dotenv 可选）
#    优先级（从高到低）：
#      1) 系统环境变量 $DOTENV_PATH 指向的文件
#      2) 当前 P4_AI交互 目录下的 .env
#      3) 项目根目录下的 .env（向上两级，通常和智慧医疗项目/代码实现同级）
#      4) 已经设置的系统环境变量（永远最高优先级）
#    若未安装 python-dotenv → 静默降级（不会报错，用户通过环境变量手动注入即可）
# ------------------------------------------------------------
_DOTENV_LOADED_FROM = None  # 给健康检查/启动日志用，告诉用户实际从哪加载的
try:
    from dotenv import load_dotenv, find_dotenv  # python-dotenv 可选依赖

    # 1) 显式 DOTENV_PATH
    explicit_path = os.environ.get("DOTENV_PATH") or os.environ.get("ENV_FILE")
    if explicit_path and os.path.isfile(explicit_path):
        load_dotenv(explicit_path, override=False)  # override=False：不覆盖已经存在的系统环境变量（生产安全）
        _DOTENV_LOADED_FROM = explicit_path
    else:
        # 2) 当前目录 .env
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, ".env"),
            os.path.join(here, ".env.local"),
            os.path.join(here, ".env.production"),
            # 向上找两级：智慧医疗项目/代码实现 → 智慧医疗项目 → 项目根
            os.path.join(os.path.dirname(here), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(here)), ".env"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                load_dotenv(p, override=False)
                _DOTENV_LOADED_FROM = p
                break
except ImportError:
    # python-dotenv 未安装，不抛异常，只是告诉用户可以 pip install
    _DOTENV_LOADED_FROM = None
    _DOTENV_HINT = (
        "[dotenv] 提示：未安装 python-dotenv，不会自动读取 .env 文件。"
        "如需本地加载 .env 配置，请执行 pip install python-dotenv；"
        "生产环境推荐直接通过系统环境变量 / Kubernetes Secret 注入，无需此包。"
    )
    # 导入阶段不能用 logger，静默记在变量里，agent 启动时打印
except Exception as _e:
    _DOTENV_LOADED_FROM = None
    _DOTENV_HINT = f"[dotenv] 加载 .env 失败（不阻塞主流程）：{type(_e).__name__}: {str(_e)[:200]}"
else:
    # 没异常情况下，如果用户没装包，try 已经落到 except，这里不再触发
    _DOTENV_HINT = ""


import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# ------------------------------------------------------------
# 1. 工具定义：调用 P3 分析服务 API
# ------------------------------------------------------------
ANALYSIS_API = os.getenv("ANALYSIS_API", "http://127.0.0.1:5000/api/v1")

# ------------------------------------------------------------
# 1.5 LLM 统一配置（兼容 OpenAI 格式，默认接入「硅基流动 SiliconFlow」）
# ------------------------------------------------------------
# ⚠️  安全提醒：API Key 绝对不要硬编码在代码里！
#     通过以下任一方式注入（优先级从上到下）：
#       a) 项目根目录放 .env 文件（需 pip install python-dotenv）
#       b) 系统环境变量：PowerShell 里 $env:LLM_API_KEY="sk-..."
#       c) IDE 运行配置里设置 Environment Variables
#
# —— 通用安全/调试配置（生产环境默认收紧）——
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true", "yes", "on")  # 生产默认 False
# CORS 白名单：逗号分隔多个域，默认仅本地前端（端口 3000 是 React/Vite 常见）
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()
]
# 会话存储后端：memory（默认，单节点） / redis（生产推荐，支持横向扩展）
SESSION_BACKEND = os.getenv("SESSION_BACKEND", "memory").lower()  # "memory" or "redis"
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")  # redis://[password@]host:port/db
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(2 * 60 * 60)))  # 默认 2 小时过期

# —— 模型分档配置（简单任务用小模型省时间 + 省钱，复杂任务用大模型保质量）——
# 默认统一走大模型，如果设置了 LLM_MODEL_ID_SMALL，意图解析等简单任务会用它
LLM_MODEL_ID_SMALL = os.getenv("LLM_MODEL_ID_SMALL", "")  # 例如：Qwen/Qwen2.5-7B-Instruct

LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "Qwen/Qwen2.5-72B-Instruct")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# 给日志/健康检查用的标记
LLM_ENABLED = bool(LLM_API_KEY)
# 是否启用了小模型（用于意图解析等简单任务）
LLM_SMALL_ENABLED = LLM_ENABLED and bool(LLM_MODEL_ID_SMALL)

# —— 缓存配置 ——
# 意图解析缓存：避免完全相同的问题 + 相同上下文重复打 LLM
INTENT_CACHE_ENABLED = os.getenv("INTENT_CACHE_ENABLED", "1").lower() in ("1", "true", "yes", "on")
INTENT_CACHE_TTL_SECONDS = int(os.getenv("INTENT_CACHE_TTL_SECONDS", str(10 * 60)))  # 默认 10 分钟
# 缓存版本号：升级路由表/字段后递增（如 v2_charts），强制旧 hash key 失效，避免脏缓存
INTENT_CACHE_VERSION = os.getenv("INTENT_CACHE_VERSION", "v2_charts")

# 推荐模型（硅基流动）：
#   - 大模型（推荐，质量高）：Qwen/Qwen2.5-72B-Instruct / deepseek-ai/DeepSeek-V2-Chat
#   - 小模型（速度快，但易重复/幻觉）：Qwen/Qwen2.5-7B-Instruct


def _build_llm_messages(question: str, intent: dict, data: list, meta: dict,
                        dim_zh: str, metric_zh: str, total: int) -> list[dict]:
    """给 LLM 构造标准 ChatML 消息列表（system + user），让输出更可控。"""
    system_prompt = (
        "你是智慧医疗大数据分析平台的「医疗数据解读专家」。\n"
        "你的任务是把结构化的住院患者数据分析结果，转化为通俗易懂、业务友好的中文摘要，"
        "给医院管理者/医保人员/临床科室看。\n"
        "\n"
        "⚠️ 严格写作要求（违反任意一条都算失败）：\n"
        "1. 数据必须严格忠于输入数据，禁止编造或修改任何数字！例如输入是7.2天，输出绝不能是34天。\n"
        "2. 禁止重复字符（如「22年年年」「比比比比」），每个字只写一遍。\n"
        "3. 禁止使用 markdown 转义符 \\; 或反斜杠，只用普通中文标点（。，、；）。\n"
        "4. 开头直接点题，不要说「好的我来分析」这类废话。\n"
        "5. 用专业但不晦涩的语言。\n"
        "6. 突出核心数字：总样本量、Top1/Top2/Top3 的数值和对比（倍数/差值）。\n"
        "7. 如果有趋势/占比，要指出「上升/下降」「集中/分散」。\n"
        "8. 结尾给出 1-2 条业务层面的观察或建议（结合数据说，不要太泛）。\n"
        "9. 最多使用 2 个 emoji（📊 📈 💡 🏥），不要滥用。\n"
        "10. 控制在 150-300 字之间，分 2-3 段，每段一句话一个意思。\n"
        "\n"
        "✅ 输出格式示例（参考，不要照抄数字）：\n"
        "📊 针对您的问题，共分析了50万条住院记录。\n"
        "排名第一的是肺炎，平均住院7.2天，比第二名新冠（9.5天）少2.3天。\n"
        "建议医院关注肺炎患者的早期干预，以缩短平均住院时间。\n"
    )

    # 只取 Top 10 让 LLM 不乱花 token（足够写摘要了）
    compact_data = []
    for item in data[:10]:
        compact = {}
        for k, v in item.items():
            if v is not None:
                compact[k] = v
        compact_data.append(compact)

    user_prompt = (
        f"【用户原始问题】\n{question}\n\n"
        f"【系统解析出的查询维度】\n"
        f"- 维度：{dim_zh}（代码: {intent.get('dimension')}）\n"
        f"- 指标：{metric_zh}（代码: {meta.get('metric')}）\n"
        f"- 过滤条件：{intent.get('filters') or '无'}\n"
        f"- 返回 Top N：{intent.get('top', '默认')}\n"
        f"- 参与计算的总记录数：{total:,} 条\n"
        f"- P3 后端查询耗时：{meta.get('query_ms', 0)} ms\n\n"
        f"【P3 返回的结构化结果（Top {len(compact_data)}）】\n"
        f"{json.dumps(compact_data, ensure_ascii=False, indent=2)}\n\n"
        "请按系统要求，输出一段流畅的中文解读摘要。"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _detect_llm_garbage(text: str) -> bool:
    """检测 LLM 输出是否是乱码/重复/幻觉。
    返回 True 表示有问题，应该降级到模板兜底。

    优化：JSON/代码 类输出天然有大量 `" { } : ,` 等重复字符，
    这部分不能按「字符重复率」判断，否则短 JSON 极易被误杀。
    """
    if not text or len(text) < 20:
        return True

    # 0. 如果「看起来像 JSON」（首字符是 {/[ 且末字符是 }/]），只做最小检查
    stripped = text.strip()
    looks_like_json = (
       stripped.startswith("{") and stripped.endswith("}") or
      stripped.startswith("[") and stripped.endswith("]")
    )
    # 如果像 JSON，仅做长度检查，不触发重复率检测
    if looks_like_json:
      return False

    # 1. 检测连续重复字符（如「年年年」「比比比比」）
    repeat_count = 0
    for i in range(2, len(text)):
        if text[i] == text[i-1] == text[i-2]:
            repeat_count += 1
    # JSON 里 "     " 多个空格也可能触发，这里提高阈值
    if repeat_count >= 5:
        return True

    # 2. 检测 markdown 转义符（如 \\;）
    if "\\;" in text or "\\\\" in text:
        return True

    # 3. 字符重复率检测：仅针对「不像 JSON」的自然语言文本启用
    #    且阈值提高到 30%（避免中文长句里「的」「是」重复触发）
    if not looks_like_json:
        char_count = {}
        for c in text:
            if c.strip():
                char_count[c] = char_count.get(c, 0) + 1
        if char_count:
            max_repeat = max(char_count.values())
            if max_repeat > len(text) * 0.30:
                return True

    return False


def _call_llm_safely(messages: list[dict], use_small_model: bool = False) -> tuple[bool, str]:
    """安全地调用 LLM：成功返回 (True, 文本)；失败返回 (False, 失败原因)。
    失败永远不会抛异常，方便调用方降级到模板兜底。
    内置乱码检测：如果 LLM 返回的是重复/乱码文本，也返回失败。

    - use_small_model=True：意图解析等简单任务 → 走 LLM_MODEL_ID_SMALL（小模型省 token 更快）
      若未配置小模型 → 自动回落大模型
    """
    if not LLM_ENABLED:
        return False, "LLM 未启用（未设置 LLM_API_KEY 环境变量）"
    # 模型选择：use_small_model + 已配置小模型 → 用小模型
    use_small = bool(use_small_model and LLM_SMALL_ENABLED)
    model_id = LLM_MODEL_ID_SMALL if use_small else LLM_MODEL_ID
    # 意图解析（小模型场景）需要预留 reasoning 字段空间，避免 JSON 被截断导致乱码误判
    # （曾因 max_tokens=400 截断，导致 looks_like_json=False 走重复率检测误判降级）
    max_tokens = 800 if use_small else 1200
    try:
        url = f"{LLM_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model_id,
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": max_tokens,
            "stream": False,
        }
        resp = requests.post(url, headers=headers, json=body, timeout=LLM_TIMEOUT)
        if resp.status_code != 200:
            return False, f"LLM HTTP {resp.status_code}: {resp.text[:300]}"
        payload = resp.json()
        choices = payload.get("choices") or []
        if not choices:
            return False, f"LLM 返回空 choices：{payload}"
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return False, "LLM 返回空 content"
        content = content.strip()

        # 乱码检测：如果 LLM 返回的是垃圾文本，也返回失败，让上层降级到模板
        if _detect_llm_garbage(content):
            return False, f"LLM 输出质量不合格（检测到重复字符或乱码），自动降级到模板。前80字预览：{content[:80]}"

        return True, content
    except requests.exceptions.Timeout:
        return False, f"LLM 调用超时（>{LLM_TIMEOUT}s）"
    except requests.exceptions.RequestException as e:
        return False, f"LLM 网络异常：{type(e).__name__}: {str(e)[:200]}"
    except Exception as e:
        return False, f"LLM 未知异常：{type(e).__name__}: {str(e)[:200]}"

# 意图 -> 分析接口 的映射表（供工具调用时匹配）
INTENT_TO_API = {
    ("*", "count"):              "/analysis/aggregate",
    ("*", "avg_length_of_stay"): "/analysis/aggregate",
    ("*", "total_charges"):      "/analysis/aggregate",
    ("*", "avg_charges"):        "/analysis/aggregate",
    ("*", "payment_mix"):        "/analysis/payment-mix",
    ("*", "trend"):              "/analysis/trend",
}

DIMENSION_KEYWORDS = {
    "年龄": "age_group", "年龄段": "age_group",
    "老人": "age_group", "老年人": "age_group", "岁以上": "age_group",  # "70岁以上老人" 这种说法
    "性别": "gender", "男女": "gender",
    "年份": "discharge_year", "年": "discharge_year", "历年": "discharge_year", "近年": "discharge_year",
    "疾病": "ccsr_diagnosis", "诊断": "ccsr_diagnosis", "病种": "ccsr_diagnosis",
    "手术": "procedure", "术式": "procedure", "手术方式": "procedure", "手术类型": "procedure",
    "医院": "facility", "机构": "facility", "医疗机构": "facility",
    "支付": "payment_typology", "支付方式": "payment_typology", "医保": "payment_typology",
    "严重程度": "severity", "病情": "severity",
}

METRIC_KEYWORDS = {
    "平均住院时长": "avg_length_of_stay", "住院时长": "avg_length_of_stay",
    "住院天数": "avg_length_of_stay", "平均住院": "avg_length_of_stay",
    "总费用": "total_charges", "费用": "total_charges", "花费": "total_charges", "总花费": "total_charges",
    "平均费用": "avg_charges", "人均费用": "avg_charges", "平均花费": "avg_charges",
    "总成本": "total_costs", "成本": "total_costs",
    "平均成本": "avg_costs",
    "人数": "count", "数量": "count", "多少": "count", "几个人": "count",
    "占比": "payment_mix", "支付方式": "payment_mix", "分布": "payment_mix",
    "趋势": "trend", "变化": "trend", "走势": "trend",
}

# P3 新版接口图表类型关键词（命中后设 intent["chart_hint"]，走新版 14 接口路由）
# 只收"明确暗示新图表"的词，不收"占比""趋势"等通用词（避免与旧 payment_mix/trend 冲突）
CHART_HINT_KEYWORDS = {
    # —— 病重趋势 / 堆叠柱 ——
    "病重趋势": "severity_profile", "严重程度构成": "severity_profile",
    "病重分布": "severity_profile", "堆叠图": "severity_profile",
    "严重程度": "severity_profile",
    # —— 人群差异 / 分组柱 ——
    "人群差异": "population_diff", "性别差异": "population_diff",
    "年龄差异": "population_diff", "种族差异": "population_diff",
    # —— 人口金字塔 ——
    "人口金字塔": "pyramid", "金字塔": "pyramid",
    "性别年龄": "pyramid",
    # —— 热力图 / 通用二维交叉（支付交叉走 payment_cross，不在这里）——
    "热力图": "heatmap", "热图": "heatmap", "交叉表": "heatmap",
    # —— 支付构成（新接口；与旧 payment_mix 区分）——
    "支付构成": "payment_composition", "三层支付": "payment_composition",
    "一级支付": "payment_composition", "二级支付": "payment_composition",
    "三级支付": "payment_composition", "支付层级": "payment_composition",
    # —— 桑葚图 ——
    "桑葚图": "sankey", "桑基图": "sankey", "流向图": "sankey",
    "资金流向": "sankey", "支付流向": "sankey", "支付链路": "sankey",
    # —— 费用关系 / 散点图 ——
    "费用关系": "cost_relation", "成本对比": "cost_relation",
    "费用散点": "cost_relation", "散点图": "cost_relation", "成本费用": "cost_relation",
    # —— 地区差异 / 区域分布 ——
    "地区差异": "region_diff", "区域差异": "region_diff", "地区分布": "region_diff",
    "区域分布": "region_diff", "医院分布": "region_diff", "地理分布": "region_diff",
    "服务区": "region_diff", "服务区域": "region_diff", "各县": "region_diff",
    # —— 支付交叉（含"支付"+"交叉"的复合表达）——
    "支付交叉": "payment_cross", "支付×年龄": "payment_cross",
    "支付与年龄": "payment_cross", "支付与病种": "payment_cross",
    "支付与严重": "payment_cross", "支付与病情": "payment_cross",
    "支付×病种": "payment_cross", "支付×严重": "payment_cross",
    "支付方式交叉": "payment_cross", "支付交叉分析": "payment_cross",
    # —— 自付负担 ——
    "自付": "oop_burden", "自费": "oop_burden", "自付负担": "oop_burden",
    "自费负担": "oop_burden", "out of pocket": "oop_burden", "out-of-pocket": "oop_burden",
    # —— KPI 总览 ——
    "总览": "payment_summary", "大屏": "payment_summary", "概览": "payment_summary",
    "kpi": "payment_summary", "KPI": "payment_summary", "全量统计": "payment_summary",
    "总体情况": "payment_summary", "整体情况": "payment_summary",
    # —— 诊断排行 / 手术排行（替代旧 /analysis/aggregate，返回 code+name）——
    "诊断排行": "top_diagnoses", "疾病排行": "top_diagnoses", "诊断top": "top_diagnoses",
    "疾病top": "top_diagnoses", "常见疾病": "top_diagnoses", "高发疾病": "top_diagnoses",
    "手术排行": "top_procedures", "手术top": "top_procedures",
    "常见手术": "top_procedures", "高频手术": "top_procedures", "手术谱": "top_procedures",
}

# P4 metric → P3 新接口 metric 翻译表（解决命名差异：P4 用 avg_length_of_stay，P3 新接口用 avg_los）
# None 表示该指标新接口不支持，降级为 count
METRIC_TO_P3 = {
    "count": "count",
    "avg_length_of_stay": "avg_los",
    "total_charges": "total_charges",
    "avg_charges": "avg_charges",
    "total_costs": None,
    "avg_costs": None,
    "payment_mix": "count",
    "trend": "count",
}

# P4 dimension → P3 新接口 by/dim1/dim2 翻译表
DIM_TO_P3_DIM = {
    "age_group": "age_group",
    "gender": "gender",
    "ccsr_diagnosis": "diagnosis",
    "payment_typology": "payment",
    "facility": "service_area",
    "severity": "severity",
}

# 合法 chart_type 集合（与前端 P5 约定：未知类型一律按 bar 渲染）
ALLOWED_CHART_TYPES = {
    "bar", "pie", "line",                      # 旧
    "stacked_bar", "grouped_bar", "pyramid",   # 新（bar 变体）
    "heatmap", "sankey", "scatter",             # 新
}


# ------------------------------------------------------------
# 2. 意图解析（LLM 驱动 + 规则兜底，支持多轮上下文）
# ------------------------------------------------------------
# 2.0 会话管理：按 conversation_id 缓存最近 N 轮的 {question, intent}
#     提供两种后端：
#       - MemoryConversationMemory（默认，单节点快速）
#       - RedisConversationMemory（生产推荐，支持横向扩展、TTL 过期、服务重启不丢）
#     通过 SESSION_BACKEND=memory|redis 环境变量切换
import threading


class MemoryConversationMemory:
    """线程安全的**内存**会话记忆存储（单节点、重启丢失）。
    每个会话保存最近 MAX_HISTORY 轮的 (question, intent) 对。
    """
    MAX_HISTORY = 5  # 每个会话最多记 5 轮，防止内存无限增长
    backend = "memory"

    def __init__(self, ttl_seconds: int = 0):
        self._store: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        # memory 后端 TTL 仅供参考：无法自动删除，除非 clear / 进程重启
        self._ttl = ttl_seconds

    def get_history(self, conversation_id: str | None) -> list[dict]:
        if not conversation_id:
            return []
        with self._lock:
            return list(self._store.get(conversation_id, []))

    def add_turn(self, conversation_id: str, question: str, intent: dict,
                 answer: str | None = None, chart: dict | None = None):
        if not conversation_id:
            return
        with self._lock:
            history = self._store.setdefault(conversation_id, [])
            # 扩展 turn 结构：存 answer + chart 方便历史详情回看，ts 用于会话列表排序
            history.append({
                "question": question,
                "intent": intent,
                "answer": answer,
                "chart": chart,
                "ts": int(time.time()),
            })
            if len(history) > self.MAX_HISTORY:
                history.pop(0)

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """列出所有会话，按最后更新时间倒序。供前端左侧"会话列表"使用。"""
        with self._lock:
            items = []
            for cid, turns in self._store.items():
                if not turns:
                    continue
                last = turns[-1]
                items.append({
                    "conversation_id": cid,
                    "last_updated": last.get("ts", 0),
                    "turn_count": len(turns),
                    "last_question": last.get("question", ""),
                    "last_metric": (last.get("intent") or {}).get("metric", ""),
                })
            items.sort(key=lambda x: x["last_updated"], reverse=True)
            return items[:limit]

    def clear(self, conversation_id: str):
        with self._lock:
            self._store.pop(conversation_id, None)

    def stats(self) -> dict:
        with self._lock:
            return {
                "active_conversations": len(self._store),
                "total_turns": sum(len(v) for v in self._store.values()),
            }


class RedisConversationMemory:
    """基于 Redis 的**持久化**会话记忆存储（横向扩展、TTL 过期、重启不丢）。

    依赖：`pip install redis`（可选；未安装时会自动降级到 memory）
    配置：
      - SESSION_BACKEND=redis
      - REDIS_URL=redis://[:password@]host:port/db
      - SESSION_TTL_SECONDS=7200（默认 2 小时）
    """
    backend = "redis"
    MAX_HISTORY = 5
    REDIS_KEY_PREFIX = "p4:conversation:"
    # D3 修复：重试冷却时间（秒）—— 连接失败后，N 秒内不再尝试重连，
    # 直接返回 None 走 memory 兜底，避免每次操作都打 3s 超时拖慢用户
    RETRY_COOLDOWN_SECONDS = float(os.getenv("REDIS_RETRY_COOLDOWN", "5"))
    # D3 修复：socket 超时进一步收紧（默认 2s / 连接 2s），Redis 近就在内网，2s 没回就一定挂了
    REDIS_CONNECT_TIMEOUT = float(os.getenv("REDIS_CONNECT_TIMEOUT", "2"))
    REDIS_SOCKET_TIMEOUT = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))

    def __init__(self, redis_url: str, ttl_seconds: int = 7200):
        self._ttl = ttl_seconds
        self._redis_url = redis_url
        # 延迟初始化：第一次读写再连接，避免模块导入阶段 Redis 未就绪就报错
        self._client = None
        self._lock = threading.Lock()
        self._connected = False
        self._last_err = ""
        # D3：冷却状态
        self._last_fail_ts: float = 0.0  # 最近一次连接失败的时间戳（time.time()）

    # ---------- 内部：Redis 客户端连接（懒加载，失败时返回 memory）----------
    def _get_client(self):
        now = time.time()
        if self._connected:
            return self._client
        # D3：冷却期内直接跳过，不做任何连接重试
        cd = max(0.5, float(self.RETRY_COOLDOWN_SECONDS))
        if self._last_fail_ts > 0 and (now - self._last_fail_ts) < cd:
            return None
        with self._lock:
            if self._connected:  # 二次检查
                return self._client
            # 再检查一次（可能另一个线程在持锁期间更新了 _last_fail_ts）
            if self._last_fail_ts > 0 and (time.time() - self._last_fail_ts) < cd:
                return None
            try:
                import redis  # 延迟导入，允许不装 redis 包
            except ImportError as e:
                self._last_err = f"未安装 redis 包：{e}. 请 pip install redis"
                self._last_fail_ts = time.time()  # 记失败时间，冷却期内不再重试
                return None
            try:
                # Redis 3.x 不支持 HELLO（Redis 6+），显式关掉 HEALTH_CHECK
                # 并指定 RESP2，兼容 Windows 版老 Redis（3.0.504）
                conn_tm = self.REDIS_CONNECT_TIMEOUT
                sock_tm = self.REDIS_SOCKET_TIMEOUT
                try:
                    self._client = redis.Redis.from_url(
                        self._redis_url,
                        decode_responses=True,
                        socket_connect_timeout=conn_tm,
                        socket_timeout=sock_tm,
                        health_check_interval=0,  # 禁用健康检查（老 Redis 不兼容）
                        protocol=2,
                    )
                except TypeError:
                    # 老版本 redis-py 没有 health_check_interval，退而求其次
                    self._client = redis.Redis.from_url(
                        self._redis_url,
                        decode_responses=True,
                        socket_connect_timeout=conn_tm,
                        socket_timeout=sock_tm,
                    )
                # 真正执行一次 ping 验证
                self._client.ping()
                self._connected = True
                self._last_fail_ts = 0.0  # 连接成功：重置失败时间戳
                return self._client
            except Exception as e:
                self._last_err = f"Redis 连接失败：{type(e).__name__}: {str(e)[:200]}"
                self._client = None
                self._last_fail_ts = time.time()  # D3：记失败时间，进入冷却
                return None

    def _key(self, conversation_id: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}{conversation_id}"

    # ---------- 对外 API（语义和 MemoryConversationMemory 完全一致）----------
    def get_history(self, conversation_id: str | None) -> list[dict]:
        if not conversation_id:
            return []
        client = self._get_client()
        if client is None:
            return []
        try:
            raw = client.lrange(self._key(conversation_id), 0, -1)
            history = []
            for s in raw:
                try:
                    history.append(json.loads(s))
                except Exception:
                    continue
            return history
        except Exception as e:
            self._last_err = f"get_history 失败：{type(e).__name__}: {str(e)[:200]}"
            return []

    def add_turn(self, conversation_id: str, question: str, intent: dict,
                 answer: str | None = None, chart: dict | None = None):
        if not conversation_id:
            return
        client = self._get_client()
        if client is None:
            return
        # 扩展 turn 结构：存 answer + chart 方便历史详情回看，ts 用于会话列表排序
        payload = json.dumps({
            "question": question,
            "intent": intent,
            "answer": answer,
            "chart": chart,
            "ts": int(time.time()),
        }, ensure_ascii=False)
        try:
            key = self._key(conversation_id)
            # 右压入（最新在最右），然后 LTRIM 保留最后 MAX_HISTORY 条
            client.rpush(key, payload)
            start = -self.MAX_HISTORY
            client.ltrim(key, start, -1)
            if self._ttl > 0:
                client.expire(key, self._ttl)
        except Exception as e:
            self._last_err = f"add_turn 失败：{type(e).__name__}: {str(e)[:200]}"

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """扫描 Redis 中所有 p4:conversation:* 的 key，返回会话列表（按最后更新时间倒序）。
        为节省内存，每个 key 只取最后一条 turn 来确定 last_updated/last_question。
        """
        client = self._get_client()
        if client is None:
            return []
        items: list[dict] = []
        try:
            prefix_len = len(self.REDIS_KEY_PREFIX)
            for key in client.scan_iter(match=f"{self.REDIS_KEY_PREFIX}*", count=200):
                # Redis 返回的 key 可能是 str（decode_responses=True）或 bytes
                kname = key.decode() if isinstance(key, (bytes, bytearray)) else key
                cid = kname[prefix_len:]
                try:
                    turn_count = client.llen(key)
                    if turn_count == 0:
                        continue
                    # 只取最后一条 turn（最新）来确定 last_updated/last_question
                    raw_last = client.lrange(key, -1, -1)
                    if not raw_last:
                        continue
                    last = json.loads(raw_last[0])
                    items.append({
                        "conversation_id": cid,
                        "last_updated": last.get("ts", 0),
                        "turn_count": turn_count,
                        "last_question": last.get("question", ""),
                        "last_metric": (last.get("intent") or {}).get("metric", ""),
                    })
                except Exception:
                    # 单个会话解析失败不影响其他会话
                    continue
            items.sort(key=lambda x: x["last_updated"], reverse=True)
            return items[:limit]
        except Exception as e:
            self._last_err = f"list_conversations 失败：{type(e).__name__}: {str(e)[:200]}"
            return []

    def clear(self, conversation_id: str):
        client = self._get_client()
        if client is None:
            return
        try:
            client.delete(self._key(conversation_id))
        except Exception as e:
            self._last_err = f"clear 失败：{type(e).__name__}: {str(e)[:200]}"

    def stats(self) -> dict:
        client = self._get_client()
        info = {
            "active_conversations": 0,
            "total_turns": 0,
            "ttl_seconds": self._ttl,
            "redis_connected": self._connected,
        }
        if self._last_err:
            info["last_error"] = self._last_err
        if client is None:
            return info
        try:
            keys = list(client.scan_iter(match=f"{self.REDIS_KEY_PREFIX}*", count=100))
            info["active_conversations"] = len(keys)
            total = 0
            for k in keys:
                try:
                    total += client.llen(k)
                except Exception:
                    continue
            info["total_turns"] = total
        except Exception as e:
            info["last_error"] = f"stats 失败：{type(e).__name__}: {str(e)[:200]}"
        return info


def _create_memory_backend() -> MemoryConversationMemory:
    """根据 SESSION_BACKEND 配置选择会话后端；Redis 连不上时**自动降级**到 memory，
    并把失败原因写在 stats 里，绝不阻塞主流程。
    """
    if SESSION_BACKEND == "redis":
        rm = RedisConversationMemory(REDIS_URL, ttl_seconds=SESSION_TTL_SECONDS)
        # 尝试一次连接（不强制：失败不抛异常，后续操作都会自动返回空 + 记错误）
        client = rm._get_client()
        if client is not None:
            print(f"[会话存储] ✅ 使用 Redis：{REDIS_URL}，TTL={SESSION_TTL_SECONDS}s")
            return rm  # type: ignore[return-value]
        # Redis 连不上 → 降级，打印提示
        print(f"[会话存储] ⚠️  Redis 配置了但不可用（{rm._last_err or '未知原因'}），自动降级为 memory 后端")
        return MemoryConversationMemory(ttl_seconds=SESSION_TTL_SECONDS)
    # 默认 memory
    mm = MemoryConversationMemory(ttl_seconds=SESSION_TTL_SECONDS)
    print(f"[会话存储] 使用 memory（单节点模式，重启会丢会话）。设置 SESSION_BACKEND=redis 可启用持久化存储。")
    return mm


# 全局唯一的会话记忆实例
MEMORY = _create_memory_backend()


# ------------------------------------------------------------
# 2.0.1 意图解析缓存（减少 LLM 往返 + 省钱）
# Key：<question_hash> | <history_key>（如果有会话）
# Strategy：
#   - 无会话：只看问题字符串（完全相同问题命中缓存）
#   - 有会话：conversation_id + 最近一轮的 question/intent 指纹组合，避免误命中
# ------------------------------------------------------------
import hashlib
from collections import OrderedDict


class IntentCache:
    """线程安全的意图解析缓存。

    后端：
      - 内存：OrderedDict（LRU，默认最大 1000）
      - Redis：如果当前会话后端已经连好 Redis，就共享同一个 Redis（不需要再连一次）
    """
    REDIS_KEY_PREFIX = "p4:intent_cache:"

    def __init__(self, enabled: bool, ttl_seconds: int = 600,
                 max_memory_items: int = 1000):
        self._enabled = bool(enabled)
        self._ttl = max(0, int(ttl_seconds))
        self._max = max(1, int(max_memory_items))
        self._store: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()
        # 统计（给健康检查/调试用）
        self._hits = 0
        self._misses = 0

    # ---------- Key 生成：对"问题 + 上下文指纹 + 当前会话轮数"做哈希，保持稳定
    #
    # D4 修复：引入「会话当前轮数 len(history)」这个维度到 key，
    # 彻底防止「同一会话里，用户重复问完全相同的问题」却命中上一轮缓存的情况：
    #   - 第 1 轮问 "肺炎费用？" → history.len=0 → keyA
    #   - 回答完并写入 history 后，第 2 轮再问 "肺炎费用？" → history.len=1 → keyB
    # 这两个 key 不一样，不会命中；如果用户问的是不同的问题，自然 key 也不同。
    # 同时保留了「最近一轮 question + dimension + metric」的指纹，
    # 即使轮数相同（理论上不可能，因为轮数就是 len(history)），上下文变化也不会误命中。
    # ----------
    @staticmethod
    def _make_cache_key(question: str, conversation_id: str | None,
                        history: list[dict]) -> str:
        ctx_parts = []
        if conversation_id:
            ctx_parts.append(f"conv:{conversation_id}")
        # D4：当前会话轮数（= len(history)，因为 add_turn 在 parse_intent 之后才执行）
        # 这是最关键的「反重复」字段——轮数一变，key 一定不同
        turn_number = len(history) if history else 0
        ctx_parts.append(f"turn:{turn_number}")
        if history:
            last = history[-1]
            q = last.get("question", "")
            dim = last.get("intent", {}).get("dimension", "")
            met = last.get("intent", {}).get("metric", "")
            chart_hint = last.get("intent", {}).get("chart_hint") or ""
            # chart_hint 也纳入指纹：上一轮的 chart_hint 会影响下一轮的意图继承
            ctx_parts.append(f"last:{q}|{dim}|{met}|hint={chart_hint}")
        # 缓存版本号纳入 hash：路由表/字段升级后旧 key 自动失效
        raw = f"v={INTENT_CACHE_VERSION}||q=" + question.strip() + "||ctx=" + ";".join(ctx_parts)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    # ---------- 共享 Redis 客户端（优先复用会话存储，避免再新建连接池）----------
    def _get_redis_client_if_available(self):
        if isinstance(MEMORY, RedisConversationMemory):
            return MEMORY._get_client()
        return None

    # ---------- 对外 API ----------
    def get(self, question: str, conversation_id: str | None,
            history: list[dict]) -> dict | None:
        """命中：返回之前缓存好的 intent dict；miss：返回 None"""
        if not self._enabled:
            return None
        key = self._make_cache_key(question, conversation_id, history)

        # 1) 先查内存
        with self._lock:
            cached = self._store.get(key)
            if cached is not None:
                self._store.move_to_end(key)
                self._hits += 1
                # 复制一份避免外部修改缓存
                return dict(cached["intent"])

        # 2) 内存 miss → 查 Redis（如果可用）
        redis_client = self._get_redis_client_if_available()
        if redis_client is not None:
            try:
                raw = redis_client.get(f"{self.REDIS_KEY_PREFIX}{key}")
                if raw:
                    item = json.loads(raw)
                    intent = dict(item["intent"])
                    # 回写内存，提升下次访问速度
                    with self._lock:
                        self._store[key] = {"intent": intent}
                        self._evict_locked()
                        self._store.move_to_end(key)
                    self._hits += 1
                    return intent
            except Exception:
                pass  # Redis 读失败完全不影响，就当 miss

        with self._lock:
            self._misses += 1
        return None

    def set(self, question: str, conversation_id: str | None,
            history: list[dict], intent: dict) -> None:
        """写入缓存（不管 enabled，只要没启用就 no-op）"""
        if not self._enabled:
            return
        key = self._make_cache_key(question, conversation_id, history)
        # 只缓存 LLM 或规则解析出的真实意图（不含 _source、_reasoning，
        # 因为下次命中需要根据调用方重新打 source 标记；不过我们存完整 dict 也行，无所谓）
        intent_copy = dict(intent)

        # 1) 写内存（LRU）
        with self._lock:
            self._store[key] = {"intent": intent_copy}
            self._evict_locked()
            self._store.move_to_end(key)

        # 2) 写 Redis（TTL）——如果可用
        if self._ttl > 0:
            redis_client = self._get_redis_client_if_available()
            if redis_client is not None:
                try:
                    payload = json.dumps({"intent": intent_copy}, ensure_ascii=False)
                    redis_client.setex(
                        f"{self.REDIS_KEY_PREFIX}{key}",
                        self._ttl,
                        payload,
                    )
                except Exception:
                    pass  # 写缓存失败不阻塞主链路

    def _evict_locked(self):
        """持有锁状态下，把超过容量的最旧条目剔除"""
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total > 0 else 0.0
            return {
                "enabled": self._enabled,
                "ttl_seconds": self._ttl,
                "items": len(self._store),
                "max_items": self._max,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
            }


# 全局唯一的意图缓存实例
INTENT_CACHE = IntentCache(
    enabled=INTENT_CACHE_ENABLED,
    ttl_seconds=INTENT_CACHE_TTL_SECONDS,
)


# 在 parse_intent 里插入：先查缓存，再解析，解析完回写缓存
# （保持函数签名不变，只在内部调用缓存层，调用方无感）
_ORIGINAL_PARSE_INTENT = None


def _parse_intent_cached(question: str, conversation_id: str | None = None,
                         use_llm: bool = True) -> dict:
    """parse_intent 的包装版：先查 INTENT_CACHE，命中则直接返回（且标记 _from_cache=True）。
    miss 就调用原始 parse_intent，然后把结果写入缓存。
    """
    # 先查一遍缓存（只有用 LLM 才值得缓存，规则本身就 ms 级）
    history = MEMORY.get_history(conversation_id)
    cached_intent = None
    if use_llm and INTENT_CACHE_ENABLED:
        cached_intent = INTENT_CACHE.get(question, conversation_id, history)
    if cached_intent is not None:
        # 命中：保留 _source / _reasoning（原样），再打一个缓存标记
        cached_intent["_source"] = cached_intent.get("_source") or "llm"
        cached_intent["_from_cache"] = True
        return cached_intent

    # Miss → 走真正的解析逻辑（直接调用底层函数，避免递归套自己）
    intent = _parse_intent_impl(question, conversation_id=conversation_id, use_llm=use_llm)

    # 回写缓存（只缓存 LLM 产出的结果，规则解析不需要缓存）
    if use_llm and intent.get("_source") in ("llm",) and INTENT_CACHE_ENABLED:
        INTENT_CACHE.set(question, conversation_id, history, intent)
    return intent


def _parse_intent_impl(question: str, conversation_id: str | None = None,
                       use_llm: bool = True) -> dict:
    """从自然语言问题中解析出 维度 / 指标 / 过滤条件 / Top N。

    优先用 LLM 解析（支持多轮上下文理解），失败时用规则引擎兜底。
    conversation_id 不为空时，会读取/写入会话历史实现多轮对话。
    """
    history = MEMORY.get_history(conversation_id)

    intent_source = "rules"  # 记录意图来源，方便调试
    reasoning = ""

    # 优先用 LLM 解析（带上下文）
    if use_llm and LLM_ENABLED and history is not None:
        ok, llm_intent, reason = _parse_intent_by_llm(question, history)
        if ok:
            intent = llm_intent
            intent_source = "llm"
            reasoning = reason
        else:
            # LLM 失败，规则兜底
            intent = _parse_intent_by_rules(question, history)
            intent_source = "rules_fallback"
            reasoning = f"LLM 降级: {reason[:100]}"
    else:
        # 没启用 LLM 或没历史，直接规则
        intent = _parse_intent_by_rules(question, history)
        intent_source = "rules"
        reasoning = "规则引擎解析"

    # 打上来源标记（方便前端展示和调试，不参与业务逻辑）
    intent["_source"] = intent_source
    intent["_reasoning"] = reasoning
    return intent


# 对外暴露 parse_intent = 缓存版本（调用方无需改代码）
parse_intent = _parse_intent_cached


# 2.1 LLM 驱动的意图解析（支持多轮上下文）
# 把"理解上下文 + 抽取意图"两件事一次性交给 LLM，输出严格 JSON
_INTENT_SYSTEM_PROMPT = """你是智慧医疗大数据平台的意图解析器。你的任务：理解用户的自然语言问题，结合对话历史，输出一个严格的 JSON 意图对象。

可用的维度（dimension）代码及对应的典型问法：
- age_group（年龄段）  → "各年龄段"、"年龄分布"、"老年人"、"儿童"、"70岁以上"、"0-17岁"
- gender（性别）       → "男性"、"女性"、"男女"
- discharge_year（年份）→ "2021年"、"历年"、"近年"
- ccsr_diagnosis（疾病）→ "疾病"、"诊断"、"病种"、"什么病"（默认）
- facility（医院）     → "医院"、"机构"
- payment_typology（支付方式）→ "支付方式"、"医保"、"自费"、"占比"
- severity（严重程度） → "严重程度"、"危重"

可用的指标（metric）代码及对应的典型问法：
- count（人数）        → "多少人"、"数量"、"住院人数"
- avg_length_of_stay（平均住院时长）→ "住多久"、"平均住院天数"
- total_charges（总费用）→ "总费用"、"花费"
- avg_charges（平均费用）→ "人均费用"
- total_costs（总成本）→ "总成本"
- avg_costs（人均成本）→ "人均成本"
- payment_mix（占比）  → "占比"、"分布"、"比例"
- trend（趋势）        → "趋势"、"变化"、"逐年"

=== 强制映射规则（必须遵守） ===
1. 问题中出现“各年龄段”、“年龄分布”、“老年人”、“儿童”等 → dimension = "age_group"
2. 问题中出现“支付方式”、“医保”、“自费”、“占比” → dimension = "payment_typology"，metric = "payment_mix"
3. 问题中出现“男性”、“女性” → dimension = "gender"
4. 问题中出现“2021”、“年份” → filters.year = 2021
5. 问题中出现“平均住院时长”、“住多久” → metric = "avg_length_of_stay"
6. 问题中出现“住院人数”、“多少人” → metric = "count"
7. 如果用户没有明确维度，默认使用 "ccsr_diagnosis"
8. 多轮对话中，如果用户说“它”或“该疾病”，必须继承上一轮的 dimension 和 filters，但 metric 会根据当前问题切换。

=== Few-shot 示例（参考） ===
用户问："各年龄段住院人数分布是怎样的？"
→ {"dimension":"age_group", "metric":"count", "filters":{}, "top":10}

用户问："不同支付方式的费用占比如何？"
→ {"dimension":"payment_typology", "metric":"payment_mix", "filters":{}, "top":10}

用户问："2021年哪类疾病平均住院时长最长？"
→ {"dimension":"ccsr_diagnosis", "metric":"avg_length_of_stay", "filters":{"year":2021}, "top":10}

输出格式（必须严格 JSON，不要加 markdown 代码块）：
{
  "dimension": "维度代码",
  "metric": "指标代码",
  "filters": {"year": 2021, "gender": "M", "age_group": "70 or Older"},
  "top": 10,
  "reasoning": "简要说明解析思路"
}

多轮对话规则：
- 如果用户在追问（如"那费用呢""它的住院天数呢""换个性别看""按年龄段看"），必须从历史中继承未明确改变的维度/指标/过滤条件。
- 如果用户明确说了新维度/新指标/新过滤条件，覆盖历史的对应字段。
- 如果用户说"男性"或"女性"，filters 里填 gender="M"或"F"。
- 如果用户说"70岁以上"或"老年人"，filters 里填 age_group="70 or Older"；"0到17岁"→"0 to 17"；"青年"→"18 to 29"；"中年"→"30 to 49"。
- 如果没有历史或用户问的是全新问题，按当前问题独立解析。
- top 默认 10，用户说"前5名"就是 5，"前三名"就是 3。
- filters 可为空对象 {}。
- 如果用户要"对比"或"比较"，top 自动调到至少 3。
"""


def _parse_intent_by_llm(question: str, history: list[dict]) -> tuple[bool, dict, str]:
    """用 LLM 解析意图（带上下文）。
    返回 (成功?, 意图dict, LLM的reasoning或失败原因)。
    """
    if not LLM_ENABLED:
        return False, {}, "LLM 未启用"

    # 构造对话历史摘要给 LLM
    history_text = "（无历史，这是第一轮对话）"
    if history:
        lines = []
        for i, turn in enumerate(history[-3:], 1):  # 只给最近3轮，省 token
            q = turn["question"]
            it = turn["intent"]
            lines.append(
                f"第{i}轮 - 用户问: {q}\n"
                f"        解析: dimension={it.get('dimension')}, metric={it.get('metric')}, "
                f"filters={it.get('filters')}, top={it.get('top')}"
            )
        history_text = "\n".join(lines)

    user_prompt = (
        f"【对话历史】\n{history_text}\n\n"
        f"【当前用户问题】\n{question}\n\n"
        f"请输出意图 JSON（记住：只输出 JSON，不要任何其他文字）："
    )

    messages = [
        {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    # 意图解析是简单任务 → 优先用小模型（快 + 省 token）；没配就自动回大模型
    ok, content = _call_llm_safely(messages, use_small_model=True)
    if not ok:
        return False, {}, content

    # 解析 LLM 返回的 JSON（容错：去掉可能的 markdown 代码块标记）
    import re as _re
    cleaned = content.strip()
    # 剥去 ```json / ``` 包裹（容错：多层嵌套、多换行）
    for _ in range(3):
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
            cleaned = _re.sub(r"^[a-zA-Z]*\s*", "", cleaned, count=1)
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    # 尝试提取第一个 {...} 块
    match = _re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, _re.DOTALL)
    if match:
        cleaned = match.group(0)

    try:
        intent_raw = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return False, {}, f"LLM 返回的不是合法 JSON: {e}，原文: {content[:200]}"

    # 字段校验 + 兜底
    valid_dims = {"age_group", "gender", "discharge_year", "ccsr_diagnosis",
                  "facility", "payment_typology", "severity"}
    valid_metrics = {"count", "avg_length_of_stay", "total_charges", "avg_charges",
                     "total_costs", "avg_costs", "payment_mix", "trend"}
    valid_genders = {"M", "F"}
    valid_age_groups = {"0 to 17", "18 to 29", "30 to 49", "50 to 69", "70 or Older"}
    # 新版 chart_hint 白名单 + 子参数白名单（与 P3 common.py 对齐）
    valid_chart_hints = {"severity_profile", "population_diff", "pyramid",
                         "heatmap", "payment_composition", "sankey", "cost_relation"}
    valid_by = {"age_group", "medical_surgical", "payment", "diagnosis"}
    valid_heatmap_dims = {"diagnosis", "procedure", "age_group", "severity",
                          "gender", "payment", "service_area"}
    valid_group = {"payment1", "payment2", "payment3"}
    valid_levels = {"payment,payment2", "payment,payment2,payment3",
                    "payment,age_group", "payment,age_group,disease",
                    "payment,disease", "payment,severity"}

    dimension = intent_raw.get("dimension", "")
    metric = intent_raw.get("metric", "")
    if dimension not in valid_dims:
        dimension = "ccsr_diagnosis"
    if metric not in valid_metrics:
        metric = "count"

    # chart_hint 校验（LLM 可选返回，非法值设 None 走规则兜底）
    chart_hint = intent_raw.get("chart_hint")
    if chart_hint and chart_hint not in valid_chart_hints:
        chart_hint = None
    by = intent_raw.get("by")
    if by and by not in valid_by:
        by = None
    dim1 = intent_raw.get("dim1")
    if dim1 and dim1 not in valid_heatmap_dims:
        dim1 = None
    dim2 = intent_raw.get("dim2")
    if dim2 and dim2 not in valid_heatmap_dims:
        dim2 = None
    group = intent_raw.get("group")
    if group and group not in valid_group:
        group = None
    levels = intent_raw.get("levels")
    if levels and levels not in valid_levels:
        levels = None

    filters = intent_raw.get("filters", {}) or {}
    if not isinstance(filters, dict):
        filters = {}

    # 年份必须是整数
    if "year" in filters:
        try:
            filters["year"] = int(filters["year"])
        except (ValueError, TypeError):
            filters.pop("year", None)
    # gender 必须是 M/F
    if "gender" in filters:
        g = str(filters["gender"]).upper()
        if g in valid_genders:
            filters["gender"] = g
        else:
            filters.pop("gender", None)
    # age_group 必须合法
    if "age_group" in filters:
        ag = str(filters["age_group"]).strip()
        if ag in valid_age_groups:
            filters["age_group"] = ag
        else:
            filters.pop("age_group", None)

    try:
        top = int(intent_raw.get("top", 10))
        top = max(1, min(top, 100))  # 限制 1-100
    except (ValueError, TypeError):
        top = 10

    reasoning = intent_raw.get("reasoning", "")

    return True, {
        "dimension": dimension,
        "metric": metric,
        "filters": filters,
        "top": top,
        # 新版扩展字段（LLM 没返回时为 None，规则兜底会补）
        "chart_hint": chart_hint,
        "by": by,
        "dim1": dim1,
        "dim2": dim2,
        "group": group,
        "levels": levels,
    }, reasoning


# 2.2 规则引擎兜底（带简单的上下文继承 + 性别/年龄段过滤）
def _infer_chart_hint_params(intent: dict, question: str = "") -> None:
    """命中 chart_hint 后，补 by/dim1/dim2/group/levels/level/mode/dimension 默认值。
    就地修改 intent，不返回新对象。只在 intent["chart_hint"] 不为 None 时生效。
    question 可选：传入问句后，能从自然语言里抽 dim1/dim2/group/level 等细节。
    """
    hint = intent.get("chart_hint")
    if not hint:
        return

    q = question or ""
    # dimension → by/dim1 推断
    dim = intent.get("dimension")
    p3_dim = DIM_TO_P3_DIM.get(dim) if dim else None

    # 通用：从问句里扫描提到的 P3 维度（用于 heatmap/cross 等）
    mentioned_dims = []
    for kw, dv in (
        ("诊断", "diagnosis"), ("病种", "diagnosis"), ("疾病", "diagnosis"),
        ("手术", "procedure"), ("术式", "procedure"),
        ("年龄", "age_group"), ("年龄段", "age_group"),
        ("性别", "gender"),
        ("种族", "race"),
        ("严重", "severity"), ("病情", "severity"),
        ("支付", "payment"),
        ("服务区", "service_area"), ("医院", "service_area"),
        ("县", "county"),
    ):
        if kw in q and dv not in mentioned_dims:
            mentioned_dims.append(dv)

    if hint == "severity_profile":
        # by: age_group / medical_surgical / payment —— 优先看问句明确提到的视角
        new_by = None
        if "支付" in q or "医保" in q:
            new_by = "payment"
        elif "年龄" in q or "年龄段" in q:
            new_by = "age_group"
        elif "医疗" in q or "手术" in q or "内科外科" in q:
            new_by = "medical_surgical"
        if new_by:
            intent["by"] = new_by
        elif not intent.get("by"):
            intent["by"] = p3_dim if p3_dim in ("age_group", "payment") else "age_group"
    elif hint == "population_diff":
        # dimension: gender / race / medical_surgical（P3 POP_DIMS 白名单）
        # P4 的 DIMENSION_KEYWORDS 不识别 race/medical_surgical，必须从问句关键词抽
        if not intent.get("by"):  # 复用 by 字段存 population_diff 的 dimension
            if "种族" in q or "race" in q.lower():
                intent["by"] = "race"
            elif "医疗" in q or "内科外科" in q or "内外科" in q:
                intent["by"] = "medical_surgical"
            elif "性别" in q:
                intent["by"] = "gender"
            else:
                intent["by"] = p3_dim if p3_dim in ("gender", "race", "medical_surgical") else "gender"
    elif hint == "heatmap":
        # dim1/dim2：优先用问句里提到的两个维度，回退到 dimension + 默认
        valid = {"diagnosis", "procedure", "age_group", "severity", "gender", "payment", "service_area"}
        dims_from_q = [d for d in mentioned_dims if d in valid]
        if not intent.get("dim1"):
            if dims_from_q:
                intent["dim1"] = dims_from_q[0]
            else:
                intent["dim1"] = p3_dim if p3_dim else "diagnosis"
        if not intent.get("dim2"):
            if len(dims_from_q) >= 2 and dims_from_q[1] != intent["dim1"]:
                intent["dim2"] = dims_from_q[1]
            else:
                intent["dim2"] = "age_group" if intent["dim1"] != "age_group" else "gender"
        # 防止 dim1 == dim2（P3 会 400）
        if intent["dim1"] == intent["dim2"]:
            intent["dim2"] = "age_group" if intent["dim1"] != "age_group" else "gender"
    elif hint == "payment_composition":
        # group: payment1/2/3 —— 从问句识别"一级/二级/三级"
        if not intent.get("group"):
            if "一级" in q or "1级" in q or "第一" in q:
                intent["group"] = "payment1"
            elif "二级" in q or "2级" in q or "第二" in q:
                intent["group"] = "payment2"
            elif "三级" in q or "3级" in q or "第三" in q:
                intent["group"] = "payment3"
            else:
                intent["group"] = "payment1"
    elif hint == "sankey":
        # levels 白名单默认 payment,payment2
        if not intent.get("levels"):
            intent["levels"] = "payment,payment2"
    elif hint == "cost_relation":
        # by: payment / age_group / diagnosis
        if not intent.get("by"):
            intent["by"] = p3_dim if p3_dim in ("payment", "age_group", "diagnosis") else "payment"
    elif hint == "region_diff":
        # level: service_area / county / facility —— 从问句识别
        if not intent.get("level"):
            if "县" in q or "医院所在县" in q:
                intent["level"] = "county"
            elif "医院" in q or "医疗机构" in q or "机构" in q:
                intent["level"] = "facility"
            else:
                intent["level"] = "service_area"
        # top 默认：facility 15，其余 20（P3 self_test 默认值）
        if not intent.get("top"):
            intent["top"] = 15 if intent["level"] == "facility" else 20
    elif hint == "payment_cross":
        # dim2: age_group / diagnosis / severity —— 从问句识别
        if not intent.get("dim2"):
            if "诊断" in q or "病种" in q or "疾病" in q:
                intent["dim2"] = "diagnosis"
            elif "严重" in q or "病情" in q:
                intent["dim2"] = "severity"
            else:
                intent["dim2"] = p3_dim if p3_dim in ("age_group", "diagnosis", "severity") else "age_group"
    elif hint == "oop_burden":
        # dimension: disease / age_group / county —— 从问句识别
        if not intent.get("dimension"):
            if "年龄" in q or "年龄段" in q:
                intent["dimension"] = "age_group"
            elif "县" in q:
                intent["dimension"] = "county"
            elif "诊断" in q or "病种" in q or "疾病" in q:
                intent["dimension"] = "disease"
            else:
                intent["dimension"] = "disease"
        # mode 默认 selfpay1（有真实金额，更有信息量）
        if not intent.get("mode"):
            intent["mode"] = "selfpay1"
    elif hint == "payment_summary":
        pass  # summary 无业务参数，只接受 filters
    elif hint == "top_diagnoses":
        # 默认 top 20（P3 文档默认值）
        if not intent.get("top"):
            intent["top"] = 20
    elif hint == "top_procedures":
        if not intent.get("top"):
            intent["top"] = 20


def _parse_intent_by_rules(question: str, history: list[dict]) -> dict:
    """规则引擎解析意图，支持简单的上下文继承。"""
    intent = {
        "dimension": None, "metric": None, "filters": {}, "top": 10,
        # 新版扩展字段（chart_hint 命中时才用，None 时走旧逻辑）
        "chart_hint": None, "by": None, "dim1": None, "dim2": None,
        "group": None, "levels": None,
        # 新增 5 个端点专用字段
        "level": None,      # region_diff: service_area / county / facility
        "mode": None,       # oop_burden: selfpay1 / any_layer
    }

    # —— 新增：先扫 CHART_HINT_KEYWORDS，命中则设 chart_hint ——
    for kw in sorted(CHART_HINT_KEYWORDS, key=len, reverse=True):
        if kw in question:
            intent["chart_hint"] = CHART_HINT_KEYWORDS[kw]
            break

    # 指标匹配（优先匹配更长关键词）
    for kw in sorted(METRIC_KEYWORDS, key=len, reverse=True):
        if kw in question:
            intent["metric"] = METRIC_KEYWORDS[kw]
            break
    # 维度匹配
    for kw in sorted(DIMENSION_KEYWORDS, key=len, reverse=True):
        if kw in question:
            intent["dimension"] = DIMENSION_KEYWORDS[kw]
            break

    import re

    # 年份过滤（正则抽取 4 位年份）
    years = re.findall(r"(?:19|20)\d{2}", question)
    if years:
        intent["filters"]["year"] = int(years[0])

    # 性别过滤
    if "男性" in question or "男人" in question or "男" in question:
        # 精确匹配：避免"男女"匹配成男性
        if not ("女性" in question or "女人" in question or "女" in question):
            intent["filters"]["gender"] = "M"
        # 若用户说"男女" → 不要设 gender（都要）
    elif "女性" in question or "女人" in question or "女患者" in question:
        intent["filters"]["gender"] = "F"

    # 年龄段过滤
    if "70岁以上" in question or "70岁及以上" in question or "老年人" in question or "高龄" in question:
        intent["filters"]["age_group"] = "70 or Older"
    elif "0到17岁" in question or "儿童" in question or "小孩" in question or "未成年人" in question:
        intent["filters"]["age_group"] = "0 to 17"
    elif "18到29岁" in question or "青年" in question or "年轻人" in question:
        intent["filters"]["age_group"] = "18 to 29"
    elif "30到49岁" in question or "中年" in question:
        intent["filters"]["age_group"] = "30 to 49"
    elif "50到69岁" in question or "中老年" in question:
        intent["filters"]["age_group"] = "50 to 69"

    # Top N：支持「前N名」「前三名」「前 10」等
    top = re.findall(r"前\s*(\d+)", question)
    if top:
        intent["top"] = int(top[0])
    if "前三名" in question or "前三" in question:
        intent["top"] = 3
    if "前五" in question or "前五名" in question:
        intent["top"] = 5
    if "对比" in question or "比较" in question or "排名" in question:
        # 对比至少看 3 条数据
        intent["top"] = max(intent["top"], 3)

    # 上下文继承：如果当前问题没提到某字段，且历史里有，就继承
    if history:
        last_intent = history[-1].get("intent", {})
        if not intent["dimension"]:
            intent["dimension"] = last_intent.get("dimension")
        if not intent["metric"]:
            intent["metric"] = last_intent.get("metric")
        # 年份继承（只有当前没指定才继承）
        if "year" not in intent["filters"] and last_intent.get("filters", {}).get("year"):
            intent["filters"]["year"] = last_intent["filters"]["year"]
        # gender 继承
        if "gender" not in intent["filters"] and last_intent.get("filters", {}).get("gender"):
            intent["filters"]["gender"] = last_intent["filters"]["gender"]
        # age_group 继承
        if "age_group" not in intent["filters"] and last_intent.get("filters", {}).get("age_group"):
            intent["filters"]["age_group"] = last_intent["filters"]["age_group"]
        # 新增：chart_hint 及其子参数继承（用户第 2 轮"换成年龄段视角"时自动继承第 1 轮的 chart_hint）
        if not intent["chart_hint"] and last_intent.get("chart_hint"):
            intent["chart_hint"] = last_intent["chart_hint"]
        for f in ("by", "dim1", "dim2", "group", "levels", "level", "mode", "dimension"):
            if not intent.get(f) and last_intent.get(f):
                intent[f] = last_intent[f]

    # —— 命中 chart_hint 时，补 by/dim1/dim2/group/levels 默认值 ——
    if intent["chart_hint"]:
        _infer_chart_hint_params(intent, question)
    else:
        # 智能推断 1：top-N 自然句式 —— "住院人数最多的前3种疾病"
        # 没命中显式关键词，但 dimension 已识别为 diagnosis/procedure 且问句含 top-N 意图时，
        # 自动升级到新接口（新接口能返回 code+name，旧 /analysis/aggregate 只返回 key）
        dim = intent.get("dimension")
        top_intent = any(w in question for w in ("最多", "前几", "排行", "top", "Top", "TOP",
                                                  "前 1", "前 2", "前 3", "前 4", "前 5",
                                                  "前 6", "前 7", "前 8", "前 9",
                                                  "前1", "前2", "前3", "前4", "前5",
                                                  "前6", "前7", "前8", "前9"))
        if top_intent and dim == "ccsr_diagnosis":
            intent["chart_hint"] = "top_diagnoses"
        elif top_intent and dim == "procedure":
            intent["chart_hint"] = "top_procedures"

        # 智能推断 2：支付交叉自然句式 —— "支付方式与年龄段的交叉分析"
        # "支付"和"交叉"任意位置组合，且不含"热力图/热图"关键词（否则走 heatmap）
        if not intent["chart_hint"]:
            if ("支付" in question and "交叉" in question
                    and "热力图" not in question and "热图" not in question):
                intent["chart_hint"] = "payment_cross"

        if intent["chart_hint"]:
            _infer_chart_hint_params(intent, question)

    # 兜底默认值（chart_hint 命中时不强制设 dimension/metric，避免干扰新接口）
    if not intent["chart_hint"]:
        if not intent["dimension"]:
            intent["dimension"] = "ccsr_diagnosis"
        if not intent["metric"]:
            intent["metric"] = "count"
    else:
        # chart_hint 命中但 metric/dimension 没匹配到时，给个合理默认
        if not intent["metric"]:
            intent["metric"] = "count"
        if not intent["dimension"]:
            intent["dimension"] = "ccsr_diagnosis"
    return intent


# （注意：旧的 def parse_intent() 已经升级为支持缓存的版本，
#  定义在前面的 _parse_intent_cached 里，通过 parse_intent = _parse_intent_cached 暴露）

# ------------------------------------------------------------
# 3. 智能工具调用（调用 P3 的 API）
# 架构：规则引擎决定路由（核心，稳定），LLM 只做参数合理性检查/建议（可选，不影响路由）
# ------------------------------------------------------------
def _validate_intent_by_llm(intent: dict, question: str) -> dict:
    """让 LLM 做「意图合理性检查 + 优化建议」，返回检查报告 dict。
    永远不会抛异常，任何失败返回空 dict（不阻塞主链路）。
    """
    if not LLM_ENABLED:
        return {}
    system_prompt = (
        "你是医疗数据分析 QA 审查员。审查用户的问题和解析出的意图是否合理。\n"
        "严格 JSON 输出：\n"
        "{\"is_valid\": true, \"issues\": [\"问题1\"], \"suggestions\": [\"建议1\"], \"warnings\": [\"提醒1\"]}\n"
        "只输出 JSON，不要其他文字或代码块。\n"
        "检查要点：\n"
        "- dimension 和 metric 是否匹配（例如 payment_mix 必须配 payment_typology 才最合理）\n"
        "- filters 是否合理（2099 年太远、70岁以上同时要求儿童等矛盾）\n"
        "- top 是否合理（要趋势的话 top 不应该小于3；要占比 top 必须至少4种支付方式）\n"
        "- 指标与业务是否相符（问「多少钱」用 total_charges 合理，不能用 avg_length_of_stay）"
    )
    user_prompt = (
        f"用户问题：{question}\n"
        f"解析出的意图：{json.dumps(intent, ensure_ascii=False)}\n"
        "请输出审查 JSON（只输出 JSON）："
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    # 意图审查是简单任务，用小模型更快
    ok, content = _call_llm_safely(messages, use_small_model=True)
    if not ok:
        return {}
    import re as _re
    cleaned = content.strip()
    for _ in range(3):
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
            cleaned = _re.sub(r"^[a-zA-Z]*\s*", "", cleaned, count=1)
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        check = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, _re.DOTALL)
        if not match:
            return {}
        try:
            check = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    # 标准化字段
    def _as_list(v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]

    return {
        "is_valid": bool(check.get("is_valid", True)),
        "issues": _as_list(check.get("issues")),
        "suggestions": _as_list(check.get("suggestions")),
        "warnings": _as_list(check.get("warnings")),
    }


# ------------------------------------------------------------
# 3.1 P3 新版接口路由表 + 参数构造（chart_hint → P3 新端点）
# ------------------------------------------------------------
def _map_metric(metric: str, allowed: set) -> str:
    """把 P4 metric 翻译为 P3 新接口 metric，并校验白名单。不支持时降级 count。"""
    p3_metric = METRIC_TO_P3.get(metric)
    if p3_metric is None or p3_metric not in allowed:
        return "count"
    return p3_metric


def _build_severity_profile_params(intent: dict) -> dict:
    by = intent.get("by") or "age_group"
    if by not in ("age_group", "medical_surgical", "payment"):
        by = "age_group"
    return {"by": by, "metric": _map_metric(intent.get("metric"), {"count", "avg_charges"})}


def _build_population_diff_params(intent: dict) -> dict:
    dim = intent.get("by") or "gender"
    if dim not in ("gender", "race", "medical_surgical"):
        dim = "gender"
    return {"dimension": dim, "metric": _map_metric(intent.get("metric"), {"count", "avg_charges", "avg_los"})}


def _build_pyramid_params(intent: dict) -> dict:
    return {}  # pyramid 只接受 filters，无业务参数


def _build_heatmap_params(intent: dict) -> dict:
    dim1 = intent.get("dim1") or "diagnosis"
    dim2 = intent.get("dim2") or "age_group"
    valid = {"diagnosis", "procedure", "age_group", "severity", "gender", "payment", "service_area"}
    if dim1 not in valid:
        dim1 = "diagnosis"
    if dim2 not in valid:
        dim2 = "age_group"
    if dim1 == dim2:
        dim2 = "age_group" if dim1 != "age_group" else "gender"
    return {"dim1": dim1, "dim2": dim2,
            "metric": _map_metric(intent.get("metric"), {"count", "avg_charges", "avg_los"}),
            "top": min(intent.get("top", 15), 50)}


def _build_payment_composition_params(intent: dict) -> dict:
    group = intent.get("group") or "payment1"
    if group not in ("payment1", "payment2", "payment3"):
        group = "payment1"
    return {"group": group, "metric": _map_metric(intent.get("metric"), {"count", "total_charges"})}


def _build_sankey_params(intent: dict) -> dict:
    levels = intent.get("levels") or "payment,payment2"
    if levels not in {"payment,payment2", "payment,payment2,payment3",
                      "payment,age_group", "payment,age_group,disease",
                      "payment,disease", "payment,severity"}:
        levels = "payment,payment2"
    return {"levels": levels, "top_disease": min(intent.get("top_disease", 8), 20)}


def _build_cost_relation_params(intent: dict) -> dict:
    by = intent.get("by") or "payment"
    if by not in ("payment", "age_group", "diagnosis"):
        by = "payment"
    return {"by": by, "top": min(intent.get("top", 30), 100)}


def _build_region_diff_params(intent: dict) -> dict:
    level = intent.get("level") or "service_area"
    if level not in ("service_area", "county", "facility"):
        level = "service_area"
    # top：facility 默认 15（医院名长），其余默认 20，上限 50（P3 文档约定）
    top_default = 15 if level == "facility" else 20
    return {
        "level": level,
        "metric": _map_metric(intent.get("metric"), {"count", "total_charges", "avg_charges"}),
        "top": min(intent.get("top", top_default), 50),
    }


def _build_payment_cross_params(intent: dict) -> dict:
    dim2 = intent.get("dim2") or "age_group"
    if dim2 not in ("age_group", "diagnosis", "severity"):
        dim2 = "age_group"
    return {
        "dim2": dim2,
        "metric": _map_metric(intent.get("metric"), {"count", "total_charges"}),
        "top": min(intent.get("top", 15), 50),
    }


def _build_oop_burden_params(intent: dict) -> dict:
    dimension = intent.get("dimension") or "disease"
    if dimension not in ("disease", "age_group", "county"):
        dimension = "disease"
    mode = intent.get("mode") or "selfpay1"
    if mode not in ("selfpay1", "any_layer"):
        mode = "selfpay1"
    return {
        "dimension": dimension,
        "mode": mode,
        "top": min(intent.get("top", 15), 50),
    }


def _build_payment_summary_params(intent: dict) -> dict:
    # summary 无业务参数，只接受 filters（由 call_analysis_api 透传）
    return {}


def _build_top_diagnoses_params(intent: dict) -> dict:
    return {
        "metric": _map_metric(intent.get("metric"),
                              {"count", "total_charges", "avg_charges", "avg_los"}),
        "top": min(intent.get("top", 20), 100),
    }


def _build_top_procedures_params(intent: dict) -> dict:
    return {
        "metric": _map_metric(intent.get("metric"),
                              {"count", "total_charges", "avg_charges"}),
        "top": min(intent.get("top", 20), 100),
    }


# 路由表：chart_hint → P3 新接口端点 + 参数构造函数 + 超时
ROUTE_TABLE = {
    # —— 模块一：病种与手术分析（7 个）——
    "top_diagnoses":       {"endpoint": "/disease/top-diagnoses",    "build": _build_top_diagnoses_params,       "timeout": 15},
    "top_procedures":      {"endpoint": "/disease/top-procedures",   "build": _build_top_procedures_params,      "timeout": 15},
    "severity_profile":    {"endpoint": "/disease/severity-profile", "build": _build_severity_profile_params,    "timeout": 15},
    "population_diff":     {"endpoint": "/disease/population-diff",  "build": _build_population_diff_params,     "timeout": 15},
    "pyramid":             {"endpoint": "/disease/pyramid",         "build": _build_pyramid_params,             "timeout": 15},
    "region_diff":         {"endpoint": "/disease/region-diff",      "build": _build_region_diff_params,         "timeout": 15},
    "heatmap":             {"endpoint": "/disease/heatmap",          "build": _build_heatmap_params,             "timeout": 15},
    # —— 模块二：支付分析（6 个）——
    "payment_composition": {"endpoint": "/payment/composition",      "build": _build_payment_composition_params, "timeout": 15},
    "payment_cross":       {"endpoint": "/payment/cross",            "build": _build_payment_cross_params,       "timeout": 15},
    "sankey":              {"endpoint": "/payment/sankey",           "build": _build_sankey_params,              "timeout": 20},
    "cost_relation":       {"endpoint": "/payment/cost-relation",    "build": _build_cost_relation_params,       "timeout": 15},
    "oop_burden":          {"endpoint": "/payment/oop-burden",       "build": _build_oop_burden_params,          "timeout": 15},
    "payment_summary":     {"endpoint": "/payment/summary",          "build": _build_payment_summary_params,    "timeout": 15},
}
# 注：/api/v1/meta/dimensions 不在路由表（由前端启动时直接调用，不经 P4）

# P3 新接口支持的 filters 白名单（12 种，比旧版 3 种多）
P3_FILTER_KEYS = ("year", "gender", "age_group", "payment", "payment2", "payment3",
                  "severity", "diagnosis", "procedure", "service_area", "county", "facility")


def call_analysis_api(intent: dict, question: str = "", use_llm_validate: bool = True) -> dict:
    """根据意图匹配并调用对应分析 API，返回结构化结果。

    - 路由规则（核心）：chart_hint 命中走 P3 新版接口，否则走旧版 if-elif（向后兼容）
    - LLM 审查（可选）：检查参数合法性，把 warnings/suggestions 写进返回 meta，不改变实际调用
    """
    # —— 第一步：LLM 做参数审查（不阻塞、不改变调用）——
    validation = {}
    if use_llm_validate and LLM_ENABLED:
        try:
            validation = _validate_intent_by_llm(intent, question)
        except Exception:
            validation = {}  # 永远不让审查影响主链路

    # —— 第二步：路由决策（chart_hint 优先，未命中走旧 if-elif）——
    chart_hint = intent.get("chart_hint")
    filters = intent.get("filters", {})

    if chart_hint and chart_hint in ROUTE_TABLE:
        # 走 P3 新版接口
        route = ROUTE_TABLE[chart_hint]
        url = f"{ANALYSIS_API}{route['endpoint']}"
        params = route["build"](intent)
        timeout = route["timeout"]
    else:
        # 走旧版接口（严格保留原逻辑，向后兼容）
        metric = intent["metric"]
        if metric == "payment_mix":
            url = f"{ANALYSIS_API}/analysis/payment-mix"
            params = {}
        elif metric == "trend":
            url = f"{ANALYSIS_API}/analysis/trend"
            params = {}
        else:
            url = f"{ANALYSIS_API}/analysis/aggregate"
            params = {"dimension": intent["dimension"], "metric": metric, "top": intent["top"]}
        timeout = 10

    # filters 透传：新接口支持全部 12 种，旧接口只认 year/gender/age_group（多余的被 P3 忽略）
    for fkey in P3_FILTER_KEYS:
        if fkey in filters:
            params[fkey] = filters[fkey]

    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()

    # 把 LLM 审查结果写入 meta（前端可以展示"系统建议"）
    if validation:
        result.setdefault("meta", {})
        result["meta"]["intent_validation"] = validation
        result["meta"]["intent_validation_used"] = "llm"
    else:
        result.setdefault("meta", {})
        result["meta"]["intent_validation_used"] = "rules_only"

    # 新增：把 P4 决策的 chart_hint 写入 meta（便于报告生成 + 前端调试）
    result["meta"]["chart_hint"] = chart_hint

    return result


# 指标英文名 → 中文解释（给模板摘要用）
METRIC_ZH = {
    "count": "住院人数",
    "avg_length_of_stay": "平均住院时长（天）",
    "total_charges": "总费用（元）",
    "avg_charges": "平均费用（元）",
    "total_costs": "总成本（元）",
    "avg_costs": "平均成本（元）",
    "avg_los": "平均住院时长（天）",  # P3 新接口命名
    "payment_mix": "支付方式占比（百分比）",
    "trend": "历年变化趋势（人数）",
}

# 维度英文名 → 中文解释
DIMENSION_ZH = {
    "age_group": "年龄段", "gender": "性别",
    "discharge_year": "出院年份", "ccsr_diagnosis": "疾病诊断（CCSR）",
    "facility": "医疗机构", "payment_typology": "支付方式",
    "severity": "病情严重程度", "aprg_drg": "DRG 分组",
}

# P3 新接口用的维度/层级中文映射（P3 命名空间与 P4 不同，单列）
P3_DIM_ZH = {
    "diagnosis": "疾病诊断", "procedure": "手术术式",
    "age_group": "年龄段", "gender": "性别", "severity": "严重程度",
    "payment": "支付方式", "service_area": "服务区", "county": "区县",
    "facility": "医院",
    # severity_profile 的 by 取值
    "medical_surgical": "医疗/外科",
    # payment_composition 的 group 取值
    "payment1": "一级支付", "payment2": "二级支付", "payment3": "三级支付",
}

# 严重程度中文（severity_profile / payment_cross 的 series 名用）
SEVERITY_ORDER = ["Minor", "Moderate", "Major", "Extreme", "Unknown"]
SEVERITY_ZH = {"Minor": "轻度", "Moderate": "中度", "Major": "重度",
               "Extreme": "极重度", "Unknown": "未知"}

# ECharts 友好调色板（避免默认单调的颜色）
COLORS = ["#1e6fd9", "#ff6b6b", "#52c41a", "#faad14", "#722ed1",
          "#13c2c2", "#eb2f96", "#fa8c16", "#2f54eb", "#a0d911"]
# 桑葚图分层配色（6 层足够）
SANKEY_LAYER_COLORS = ["#1e6fd9", "#52c41a", "#faad14", "#722ed1",
                       "#13c2c2", "#eb2f96"]
# 严重程度专属配色（绿→黄→橙→红，越严重越深）
SEVERITY_COLORS = {"Minor": "#52c41a", "Moderate": "#faad14",
                   "Major": "#fa8c16", "Extreme": "#ff4d4f", "Unknown": "#bfbfbf"}


# ------------------------------------------------------------
# 4. 分析结果文本生成（LLM + 模板兜底，失败自动降级）
# ------------------------------------------------------------
def _summary_top_diagnoses(question, intent, api_result, dim_zh, metric_zh):
    """4.1 top-diagnoses 摘要：用 name（人类可读名）而不是 code。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录。",
             f"📊 按住院{metric_zh}排名，前 {len(data)} 种诊断如下："]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(data[:5]):
        name = r.get("name") or r.get("code") or r.get("key") or "-"
        code = r.get("code", "")
        v = r.get("value") or r.get("count") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        v_str = f"{v:,}" if isinstance(v, int) else f"{v:,.2f}"
        lines.append(f"  {medal} 「{name}」({code})：{v_str}")
    if len(data) >= 2:
        v1 = data[0].get("value") or data[0].get("count") or 0
        v2 = data[1].get("value") or data[1].get("count") or 0
        try:
            ratio = float(v1) / float(v2) if v2 else 1
            if ratio > 1:
                lines.append(f"💡 第一名是第二名的 **{ratio:.2f} 倍**，差距明显。")
        except (TypeError, ZeroDivisionError):
            pass
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_top_procedures(question, intent, api_result, dim_zh, metric_zh):
    """4.2 top-procedures 摘要：结构同 top-diagnoses。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条手术记录。",
             f"📊 按手术{metric_zh}排名，前 {len(data)} 种术式如下："]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(data[:5]):
        name = r.get("name") or r.get("code") or r.get("key") or "-"
        code = r.get("code", "")
        v = r.get("value") or r.get("count") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        v_str = f"{v:,}" if isinstance(v, int) else f"{v:,.2f}"
        lines.append(f"  {medal} 「{name}」({code})：{v_str}")
    if len(data) >= 2:
        v1 = data[0].get("value") or data[0].get("count") or 0
        v2 = data[1].get("value") or data[1].get("count") or 0
        try:
            ratio = float(v1) / float(v2) if v2 else 1
            if ratio > 1:
                lines.append(f"💡 第一名是第二名的 **{ratio:.2f} 倍**。")
        except (TypeError, ZeroDivisionError):
            pass
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_severity_profile(question, intent, api_result, dim_zh, metric_zh):
    """4.3 severity-profile 摘要：按 group 总结严重程度构成。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    by = intent.get("by", "age_group")
    by_zh = P3_DIM_ZH.get(by, by)
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录。",
             f"📊 按「{by_zh}」分组，严重程度构成如下："]
    # 重建 {group: {severity: value, total}}
    groups, seen = [], set()
    for r in data:
        g = r.get("group")
        if g and g not in seen:
            groups.append(g); seen.add(g)
    idx = {g: {} for g in groups}
    for r in data:
        g, s = r.get("group"), r.get("severity")
        if g in idx:
            idx[g][s] = r.get("value") or r.get("count") or 0
    for gi, g in enumerate(groups[:5]):
        gdict = idx[g]
        gtotal = sum(gdict.values())
        sev_str = " / ".join(f"{SEVERITY_ZH.get(s, s)}={gdict[s]:,}"
                             for s in SEVERITY_ORDER if s in gdict)
        lines.append(f"  {gi+1}. 「{g}」合计 {gtotal:,}：{sev_str}")
    # 找极重度占比最高的组
    extreme_max_g, extreme_max_v = None, 0
    for g in groups:
        ev = idx[g].get("Extreme", 0)
        gtotal = sum(idx[g].values())
        if gtotal and ev / gtotal > extreme_max_v:
            extreme_max_v = ev / gtotal
            extreme_max_g = g
    if extreme_max_g:
        lines.append(f"💡 「{extreme_max_g}」极重度占比最高（{extreme_max_v*100:.1f}%），需重点关注。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_population_diff(question, intent, api_result, dim_zh, metric_zh):
    """4.4 population-diff 摘要：按 key 总结分布占比。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    by = intent.get("by", "gender")
    by_zh = P3_DIM_ZH.get(by, by)
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录。",
             f"📊 按「{by_zh}」分组，分布占比："]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(data[:5]):
        key = r.get("key") or "-"
        v = r.get("value") or r.get("count") or 0
        pct = r.get("pct") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(f"  {medal} 「{key}」：{v:,}（{pct}%）")
    if len(data) >= 2:
        v1 = data[0].get("value") or data[0].get("count") or 0
        v2 = data[1].get("value") or data[1].get("count") or 0
        if v2:
            ratio = v1 / v2
            if ratio > 1:
                lines.append(f"💡 「{data[0].get('key','-')}」是「{data[1].get('key','-')}」的 **{ratio:.2f} 倍**。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_pyramid(question, intent, api_result, dim_zh, metric_zh):
    """4.5 pyramid 摘要：人口金字塔，男女对比。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录（已排除性别空值）。",
             "📊 按年龄段看男女分布："]
    male_total = sum(int(r.get("male") or 0) for r in data)
    female_total = sum(int(r.get("female") or 0) for r in data)
    lines.append(f"  👨 男性合计 {male_total:,} 人；👩 女性合计 {female_total:,} 人。")
    # 找老年段（70 or Older）
    elder = next((r for r in data if "70" in str(r.get("age_group", ""))), None)
    if elder:
        m, f = int(elder.get("male") or 0), int(elder.get("female") or 0)
        if m + f:
            lines.append(f"💡 老年段（{elder.get('age_group')}）男女比 {m/f:.2f}，"
                         + ("女性显著多于男性。" if f > m * 1.2 else "男性显著多于女性。" if m > f * 1.2 else "男女相当。"))
    # 找儿童段
    child = next((r for r in data if "0 to 17" in str(r.get("age_group", ""))), None)
    if child:
        lines.append(f"  👶 儿童段（0 to 17）合计 {int(child.get('total') or 0):,} 人。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_region_diff(question, intent, api_result, dim_zh, metric_zh):
    """4.6 region-diff 摘要：按 level 总结地区分布。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    level = intent.get("level", "service_area")
    level_zh = P3_DIM_ZH.get(level, level)
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录。",
             f"📊 按「{level_zh}」分组，住院分布："]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(data[:5]):
        key = r.get("key") or r.get("name") or "-"
        if len(key) > 30:
            key = key[:28] + "..."
        v = r.get("value") or r.get("count") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        pct = (v * 100.0 / total) if total else 0
        lines.append(f"  {medal} 「{key}」：{v:,}（占 {pct:.1f}%）")
    if len(data) >= 2:
        v1 = data[0].get("value") or data[0].get("count") or 0
        v2 = data[1].get("value") or data[1].get("count") or 0
        if v2:
            ratio = v1 / v2
            if ratio > 1:
                lines.append(f"💡 第一名「{str(data[0].get('key','-'))[:20]}」是第二名的 **{ratio:.2f} 倍**。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_heatmap(question, intent, api_result, dim_zh, metric_zh):
    """4.7 heatmap 摘要：找最热的格子（value 最大）。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    dim1 = intent.get("dim1", "diagnosis")
    dim2 = intent.get("dim2", "age_group")
    dim1_zh = P3_DIM_ZH.get(dim1, dim1)
    dim2_zh = P3_DIM_ZH.get(dim2, dim2)
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录。",
             f"📊 「{dim1_zh} × {dim2_zh}」热力图共 {len(data)} 个格子。"]
    if not data:
        lines.append("  ⚠️ 数据为空。")
        return "\n".join(lines)
    top = sorted(data, key=lambda r: r.get("value") or r.get("count") or 0, reverse=True)[:3]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(top):
        x = r.get("dim1_name") or r.get("dim1") or "-"
        y = r.get("dim2_name") or r.get("dim2") or "-"
        v = r.get("value") or r.get("count") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(f"  {medal} 「{x}」×「{y}」：{v:,}")
    # 计算稀疏度
    if total and len(data) > 5:
        avg = sum(r.get("value") or r.get("count") or 0 for r in data) / len(data)
        max_v = max(r.get("value") or r.get("count") or 0 for r in data)
        if max_v > avg * 3:
            lines.append(f"💡 最热格子值 {max_v:,} 是平均值的 {max_v/avg:.1f} 倍，分布极不均衡。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_payment_composition(question, intent, api_result, dim_zh, metric_zh):
    """5.1 payment-composition 摘要：主要支付方式 + null_excluded 提示。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    null_excluded = meta.get("null_excluded", 0) or 0
    group = intent.get("group", "payment1")
    group_zh = P3_DIM_ZH.get(group, group)
    lines = [f"📋 针对您的问题「{question}」，分析支付构成。",
             f"📊 「{group_zh}」构成（按 {metric_zh}）："]
    if null_excluded:
        kept_total = total + null_excluded
        kept_pct = total * 100.0 / kept_total if kept_total else 0
        lines.append(f"  ⚠️ 已排除 {null_excluded:,} 条无该层支付方式记录（保留 {kept_pct:.1f}%）。")
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(data[:5]):
        key = r.get("key") or "-"
        v = r.get("value") or r.get("count") or 0
        pct = r.get("pct") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(f"  {medal} 「{key}」：{v:,}（{pct}%）")
    if len(data) >= 2:
        p1 = data[0].get("pct") or 0
        p2 = data[1].get("pct") or 0
        if p1 > p2:
            lines.append(f"💡 「{data[0].get('key','-')}」占比 {p1}%，比第二名高 {p1-p2:.2f} 个百分点。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_payment_cross(question, intent, api_result, dim_zh, metric_zh):
    """5.2 payment-cross 摘要：主要支付 × 主要 dim2 + 主流组合。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    dim2 = intent.get("dim2", "age_group")
    dim2_zh = P3_DIM_ZH.get(dim2, dim2)
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条记录。",
             f"📊 支付方式 × {dim2_zh} 交叉分析："]
    # 找最大的组合（全局 max）
    if data:
        top_cell = max(data, key=lambda r: r.get("value") or r.get("count") or 0)
        k = top_cell.get("key", "-")
        s = top_cell.get("dim2_name") or top_cell.get("dim2", "-")
        v = top_cell.get("value") or top_cell.get("count") or 0
        lines.append(f"  🔝 最大组合：「{k}」×「{s}」：{v:,} 人。")
        # 按 key 汇总前 3 个支付方式
        key_sum, key_seen = {}, set()
        for r in data:
            k2 = r.get("key")
            if k2 and k2 not in key_seen:
                key_seen.add(k2)
            key_sum[k2] = key_sum.get(k2, 0) + (r.get("value") or r.get("count") or 0)
        top_keys = sorted(key_sum.items(), key=lambda x: x[1], reverse=True)[:3]
        medals = ["🥇", "🥈", "🥉"]
        for i, (k2, v2) in enumerate(top_keys):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            lines.append(f"  {medal} 「{k2}」合计 {v2:,} 人。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_sankey(question, intent, api_result, dim_zh, metric_zh):
    """5.3 sankey 摘要：链路 source→target + 流量。"""
    raw = api_result.get("data") or {}
    if isinstance(raw, list):
        raw = {"nodes": [], "links": []}
    nodes = raw.get("nodes", [])
    links = raw.get("links", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    null_excluded = meta.get("null_excluded", 0) or 0
    levels = meta.get("levels", "payment,payment2")
    lines = [f"📋 针对您的问题「{question}」，分析支付链路「{levels}」。",
             f"📊 链路共 {len(nodes)} 个节点、{len(links)} 条流向。"]
    if total:
        lines.append(f"  ✅ 走完全程 {total:,} 条记录。")
    if null_excluded:
        kept_pct = total * 100.0 / (total + null_excluded) if (total + null_excluded) else 0
        lines.append(f"  ⚠️ 因中间层为空而退出链路 {null_excluded:,} 条（保留 {kept_pct:.1f}%）。")
    # 找最大流
    if links:
        top_link = max(links, key=lambda l: l.get("value") or 0)
        src = top_link.get("source", "-")
        tgt = top_link.get("target", "-")
        v = top_link.get("value", 0)
        # 去掉 layer 前缀让展示更友好
        if "|" in src: src = src.split("|", 1)[1]
        if "|" in tgt: tgt = tgt.split("|", 1)[1]
        lines.append(f"💡 最大流：「{src}」→「{tgt}」{v:,} 人。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_cost_relation(question, intent, api_result, dim_zh, metric_zh):
    """5.4 cost-relation 摘要：费用/成本比最高/最低。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    by = intent.get("by", "payment")
    by_zh = P3_DIM_ZH.get(by, by)
    lines = [f"📋 针对您的问题「{question}」，按「{by_zh}」分组共 {len(data)} 条记录。",
             "📊 费用-成本关系（按费用/成本比排序）："]
    if not data:
        return "\n".join(lines) + "\n  ⚠️ 数据为空。"
    sorted_by_ratio = sorted(data, key=lambda r: r.get("charge_cost_ratio") or 0, reverse=True)
    # 比率最高
    top = sorted_by_ratio[0]
    bot = sorted_by_ratio[-1]
    lines.append(f"  🔼 费/本比最高：「{top.get('key','-')}」{top.get('charge_cost_ratio',0)} "
                 f"（次均费用 {top.get('avg_charges',0):,.0f} / 次均成本 {top.get('avg_costs',0):,.0f}）")
    lines.append(f"  🔽 费/本比最低：「{bot.get('key','-')}」{bot.get('charge_cost_ratio',0)} "
                 f"（次均费用 {bot.get('avg_charges',0):,.0f} / 次均成本 {bot.get('avg_costs',0):,.0f}）")
    # 平均比率
    ratios = [r.get("charge_cost_ratio") or 0 for r in data]
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0
    lines.append(f"💡 整体平均费/本比 {avg_ratio:.2f}；高于 3.0 的支付方式需关注定价合理性。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_oop_burden(question, intent, api_result, dim_zh, metric_zh):
    """5.5 oop-burden 摘要：自付负担最重的组。"""
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    dimension = intent.get("dimension", "disease")
    dim_zh = P3_DIM_ZH.get(dimension, dimension)
    mode = intent.get("mode", "selfpay1")
    lines = [f"📋 针对您的问题「{question}」，按「{dim_zh}」分组共 {len(data)} 条记录。",
             f"📊 自付负担分析（mode={mode}，按 self_pay_count 降序）："]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(data[:5]):
        key = r.get("key") or "-"
        if len(key) > 30:
            key = key[:28] + "..."
        pct = r.get("self_pay_pct") or 0
        sp_count = r.get("self_pay_count") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        line = f"  {medal} 「{key}」：自付 {sp_count:,} 人（{pct}%）"
        if mode == "selfpay1":
            avg_chg = r.get("self_pay_avg_charges") or 0
            line += f"，自付次均费用 {avg_chg:,.0f}"
        lines.append(line)
    if data:
        top = data[0]
        lines.append(f"💡 「{top.get('key','-')}」自付负担最重；建议关注该人群的医保覆盖与减免政策。")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def _summary_payment_summary(question, intent, api_result, dim_zh, metric_zh):
    """5.6 payment-summary KPI 摘要。"""
    raw = api_result.get("data") or {}
    if isinstance(raw, list):
        raw = {}
    meta = api_result.get("meta", {})
    lines = [f"📋 针对您的问题「{question}」，KPI 总览大屏。",
             "📊 关键指标如下："]
    lines.append(f"  📋 总记录 {raw.get('total_records', 0):,} 条")
    lines.append(f"  💰 总费用 {raw.get('total_charges', 0):,.0f} 元 / 总成本 {raw.get('total_costs', 0):,.0f} 元")
    lines.append(f"  💵 次均费用 {raw.get('avg_charges', 0):,.2f} 元 / 次均成本 {raw.get('avg_costs', 0):,.2f} 元")
    lines.append(f"  ⏰ 平均住院 {raw.get('avg_los', 0)} 天")
    lines.append(f"  👤 自付 {raw.get('self_pay_count', 0):,} 人（{raw.get('self_pay_pct', 0)}%）")
    tp = raw.get("top_payment") or {}
    if tp:
        lines.append(f"  🏆 主要支付方式：「{tp.get('key', '-')}」（{tp.get('pct', 0)}%）")
    sev = raw.get("severity_distribution") or {}
    sev_str = " / ".join(f"{SEVERITY_ZH.get(k,k)}={v:,}" for k, v in sev.items() if k in SEVERITY_ORDER)
    if sev_str:
        lines.append(f"  🩺 严重程度分布：{sev_str}")
    ed = raw.get("ed_count", 0)
    if ed:
        lines.append(f"  🚑 急诊就诊 {ed:,} 人次")
    lines.append(f"⏱️ 查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


# chart_hint → 模板摘要生成函数路由表（LLM 失败兜底用）
SUMMARY_BUILDERS = {
    "top_diagnoses":       _summary_top_diagnoses,
    "top_procedures":      _summary_top_procedures,
    "severity_profile":    _summary_severity_profile,
    "population_diff":     _summary_population_diff,
    "pyramid":             _summary_pyramid,
    "region_diff":         _summary_region_diff,
    "heatmap":             _summary_heatmap,
    "payment_composition": _summary_payment_composition,
    "payment_cross":       _summary_payment_cross,
    "sankey":              _summary_sankey,
    "cost_relation":       _summary_cost_relation,
    "oop_burden":          _summary_oop_burden,
    "payment_summary":     _summary_payment_summary,
}


def _fallback_template_summary(question: str, intent: dict, api_result: dict,
                               dim_zh: str, metric_zh: str) -> str:
    """抽取模板逻辑为独立函数，方便 LLM 失败时直接复用兜底。

    路由优先级：
      1) chart_hint 命中 SUMMARY_BUILDERS → 走专用 P3 摘要生成器（13 种）
      2) 未命中 → 走旧版通用 top-N 模板
    """
    chart_hint = intent.get("chart_hint")
    if chart_hint and chart_hint in SUMMARY_BUILDERS:
        try:
            return SUMMARY_BUILDERS[chart_hint](question, intent, api_result, dim_zh, metric_zh)
        except Exception as e:
            print(f"[SUMMARY BUILDER ERROR] {chart_hint}: {e}，降级到通用模板")
            # 失败时降级到下面的通用模板逻辑
    # 旧版通用 top-N 模板
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0

    lines = []
    lines.append(f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录。")
    lines.append(f"📊 按「{dim_zh}」维度，计算「{metric_zh}」指标，结果如下：")

    top_n = min(3, len(data))
    medals = ["🥇", "🥈", "🥉"]
    for i in range(top_n):
        item = data[i]
        key = item.get("key") or item.get("payment") or item.get("year") or "-"
        value = item.get("value") or item.get("pct") or item.get("avg_los") or item.get("count") or 0
        count = item.get("count") or 0
        medal = medals[i] if i < len(medals) else f"{i+1}."
        value_str = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
        extra = f"（涉及 {count:,} 条记录）" if count else ""
        lines.append(f"  {medal} 「{key}」：{value_str}{extra}")

    if len(data) >= 2:
        v1 = data[0].get("value") or data[0].get("pct") or data[0].get("count") or 0
        v2 = data[1].get("value") or data[1].get("pct") or data[1].get("count") or 0
        try:
            ratio = float(v1) / float(v2) if v2 else 1
            if ratio > 1:
                lines.append(f"💡 第一名是第二名的 **{ratio:.2f} 倍**，差距较为明显。")
        except (TypeError, ZeroDivisionError):
            pass

    lines.append(f"⏱️ 本次查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


def generate_text_summary(question, intent, api_result, history=None):
    """将结构化分析结果转化为通俗易懂的医疗摘要。

    优先级（生产环境稳定优先）：
    1) 若配置了 LLM_API_KEY → 先尝试调用 LLM 生成高质量摘要
    2) LLM 调用任何环节失败 → 立刻降级用规则模板兜底
    history 不为空时，告诉 LLM 这是多轮对话，让回答更连贯。
    """
    print(f"[DEBUG] LLM_ENABLED = {LLM_ENABLED}")
    chart_hint = intent.get("chart_hint")
    # payment_summary 的 data 是单个对象（KPI 大屏），不是 list —— 特殊处理
    if chart_hint == "payment_summary":
        raw = api_result.get("data") if api_result else None
        if not isinstance(raw, dict) or not raw:
            return "❌ 未查询到 KPI 总览数据。"
        # 走 SUMMARY_BUILDERS 里的 _summary_payment_summary
        return _fallback_template_summary(question, intent, api_result, "总览", "KPI")

    data = []
    if api_result and isinstance(api_result, dict):
        data = api_result.get("data", [])
        # sankey 的 data 是 dict（nodes/links），不是 list
        if isinstance(data, dict):
            data = data.get("nodes", []) or data.get("links", [])
    print(f"[DEBUG] data length = {len(data) if isinstance(data, list) else 'non-list'}")
    if not data:
        return "❌ 未查询到符合条件的分析结果，请调整查询条件后重试。"

    meta = api_result.get("meta", {}) if api_result else {}
    metric_zh = METRIC_ZH.get(meta.get("metric", ""), meta.get("metric", "指标"))
    dim_zh = DIMENSION_ZH.get(intent.get("dimension", ""), "维度")
    total = meta.get("total_records", 0) or 0

    # —— 路径1：LLM 生成（如果启用了）——
    if LLM_ENABLED:
        messages = _build_llm_messages(question, intent, data, meta, dim_zh, metric_zh, total)
        # 如果有多轮历史，告诉 LLM 上轮说过什么，避免重复
        if history:
            lines = []
            for i, t in enumerate(history[-2:], 1):
                lines.append(f"第{i}轮问题: 「{t['question']}」")
            history_context = "\n".join(lines)
            messages[1]["content"] += (
                f"\n\n【多轮对话上下文】\n{history_context}\n\n"
                "⚠️ 回答要求：当前问题可能是对上轮的追问，请：\n"
                "1) 用承接式开头（如「继续看费用数据：……」「改为按年龄段来看：……」）\n"
                "2) 不要重复上一轮已经说过的背景介绍，直接说本轮新增的核心结论\n"
                "3) 如果维度或指标换了，直接点出来"
            )
        ok, text_or_reason = _call_llm_safely(messages)
        if ok:
            return text_or_reason
        else:
            # 打印错误到控制台（便于调试）
            print(f"[LLM ERROR] {text_or_reason}")
            # 继续执行模板兜底
    # —— 路径2：模板兜底（LLM 没启用 / 调用失败都会走这）——
    return _fallback_template_summary(question, intent, api_result, dim_zh, metric_zh)


# ------------------------------------------------------------
# 5. 生成 ECharts 图表配置（供前端渲染，更美观）
# 策略：规则引擎生成稳定结构，LLM 辅助"图表类型建议 + 个性化标题 + 数据描述"
# ------------------------------------------------------------
def _suggest_chart_by_llm(intent: dict, dim_zh: str, metric_zh: str,
                           data_sample: list[dict]) -> dict:
    """让 LLM 建议：用什么图表类型、取什么好标题、一句话描述（JSON 输出）。
    返回建议 dict，任何环节失败都返回空 dict，调用方用规则默认值。
    """
    if not LLM_ENABLED:
        return {}
    system_prompt = (
        "你是可视化工程师。请根据医疗分析任务，推荐合适的 ECharts 图表配置。\n"
        "合法 chart_type：bar（柱状图，默认）、pie（饼图，仅限占比）、line（折线图，仅限时间趋势）。\n"
        "严格合法 JSON 输出：\n"
        "{\"chart_type\": \"bar|pie|line\", \"title\": \"好标题（10字以内，具体）\", \"subtitle\": \"15字内的副标题\"}\n"
        "不要加任何其他文字或代码块。"
    )
    user_prompt = (
        f"维度：{dim_zh}，指标：{metric_zh}\n"
        f"用户问题关联: dimension={intent.get('dimension')}, metric={intent.get('metric')}\n"
        f"数据样例（前3条）：{json.dumps(data_sample[:3], ensure_ascii=False)}\n"
        "请输出建议的 JSON（只输出 JSON）："
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    ok, content = _call_llm_safely(messages)
    if not ok:
        return {}
    import re as _re
    cleaned = content.strip()
    # 剥去 ```json / ``` 包裹（容错：可能多层嵌套、多换行）
    for _ in range(3):
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
            # 如果开头带语言标签如 json、python，去掉
            cleaned = _re.sub(r"^[a-zA-Z]*\s*", "", cleaned, count=1)
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        suggestion = json.loads(cleaned)
    except json.JSONDecodeError:
        # 再尝试提取 JSON 块（找最外层一对 {} 或 []）
        match = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
        if not match:
            return {}
        try:
            suggestion = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    # 字段校验 + 约束（保证 chart_type 只能是 3 选一）
    allowed = {"bar", "pie", "line"}
    ct = suggestion.get("chart_type")
    if ct not in allowed:
        ct = None
    return {
        "chart_type": ct,
        "title": str(suggestion.get("title", ""))[:20],
        "subtitle": str(suggestion.get("subtitle", ""))[:30],
    }


# ------------------------------------------------------------
# 5.x P3 新版接口专用图表构造器（13 个）—— 命中 chart_hint 时调用
# 每个函数签名：(intent, api_result, suggestion) -> {chart_type, option, _suggestion_source}
# ------------------------------------------------------------
def _base_title(suggestion: dict, default_text: str) -> dict:
    """构造 ECharts title 对象，优先用 LLM 建议的标题。"""
    title_obj = {"text": suggestion.get("title") or default_text,
                 "left": "center", "textStyle": {"fontSize": 15}}
    sub = suggestion.get("subtitle")
    if sub:
        title_obj["subtext"] = sub
        title_obj["itemGap"] = 8
    return title_obj


def _fmt_num(v) -> str:
    """统一数字格式化：浮点保留 2 位带千分位，整数直接千分位。"""
    if v is None:
        return "-"
    try:
        if isinstance(v, float):
            return f"{v:,.2f}"
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _build_top_diagnoses_option(intent, api_result, suggestion):
    """4.1 top-diagnoses 柱状图：X=name（人类可读名），Y=value。"""
    data = api_result.get("data", [])
    metric = intent.get("metric", "count")
    metric_zh = METRIC_ZH.get(metric, metric)
    cats = [r.get("name") or r.get("code") or r.get("key") or "-" for r in data]
    vals = [r.get("value") or r.get("count") or 0 for r in data]
    title_obj = _base_title(suggestion, "诊断排行 Top N")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}<br/>" + metric_zh + ": {c}"},
        "grid": {"left": 70, "right": 30, "bottom": 110, "top": 50},
        "xAxis": {"type": "category", "data": cats,
                  "axisLabel": {"rotate": 35, "interval": 0, "fontSize": 11},
                  "name": "诊断"},
        "yAxis": {"type": "value", "name": metric_zh},
        "series": [{
            "type": "bar", "name": metric_zh, "data": vals, "barMaxWidth": 50,
            "itemStyle": {"borderRadius": [4, 4, 0, 0]},
            "label": {"show": True, "position": "top", "fontSize": 10},
            "markPoint": {"data": [{"type": "max", "name": "最大值"}]},
        }],
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_top_procedures_option(intent, api_result, suggestion):
    """4.2 top-procedures 柱状图：X=name，Y=value。"""
    data = api_result.get("data", [])
    metric = intent.get("metric", "count")
    metric_zh = METRIC_ZH.get(metric, metric)
    cats = [r.get("name") or r.get("code") or r.get("key") or "-" for r in data]
    vals = [r.get("value") or r.get("count") or 0 for r in data]
    title_obj = _base_title(suggestion, "手术谱排行 Top N")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 70, "right": 30, "bottom": 110, "top": 50},
        "xAxis": {"type": "category", "data": cats,
                  "axisLabel": {"rotate": 35, "interval": 0, "fontSize": 11},
                  "name": "手术"},
        "yAxis": {"type": "value", "name": metric_zh},
        "series": [{
            "type": "bar", "name": metric_zh, "data": vals, "barMaxWidth": 50,
            "itemStyle": {"borderRadius": [4, 4, 0, 0]},
            "label": {"show": True, "position": "top", "fontSize": 10},
            "markPoint": {"data": [{"type": "max", "name": "最大值"}]},
        }],
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_severity_profile_option(intent, api_result, suggestion):
    """4.3 severity-profile 堆叠柱：X=group，系列=severity（按 Minor→Extreme 顺序）。"""
    data = api_result.get("data", [])
    by = intent.get("by", "age_group")
    by_zh = P3_DIM_ZH.get(by, by)
    # 提取所有 group（按首次出现顺序）和所有 severity（按固定顺序）
    groups, seen = [], set()
    for r in data:
        g = r.get("group")
        if g and g not in seen:
            groups.append(g); seen.add(g)
    sev_list = [s for s in SEVERITY_ORDER if any(r.get("severity") == s for r in data)]
    # 没在固定顺序里的 severity（理论上不会发生）
    for r in data:
        s = r.get("severity")
        if s and s not in SEVERITY_ORDER and s not in sev_list:
            sev_list.append(s)
    # 重建二维索引：{group: {severity: value}}
    idx = {g: {} for g in groups}
    for r in data:
        g, s = r.get("group"), r.get("severity")
        if g in idx:
            idx[g][s] = r.get("value") or r.get("count") or 0
    series = []
    for s in sev_list:
        series.append({
            "type": "bar", "name": SEVERITY_ZH.get(s, s), "stack": "severity",
            "data": [idx[g].get(s, 0) for g in groups],
            "itemStyle": {"color": SEVERITY_COLORS.get(s)},
            "emphasis": {"focus": "series"},
        })
    title_obj = _base_title(suggestion, f"按{by_zh}看严重程度构成")
    option = {
        "color": [SEVERITY_COLORS.get(s, COLORS[i % len(COLORS)]) for i, s in enumerate(sev_list)],
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"top": 30, "data": [SEVERITY_ZH.get(s, s) for s in sev_list]},
        "grid": {"left": 70, "right": 30, "bottom": 60, "top": 80},
        "xAxis": {"type": "category", "data": [str(g) for g in groups],
                  "axisLabel": {"rotate": 20, "interval": 0}, "name": by_zh},
        "yAxis": {"type": "value", "name": "人数"},
        "series": series,
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_population_diff_option(intent, api_result, suggestion):
    """4.4 population-diff 分组柱（其实只有 1 维，可视作单系列柱 + 占比标签）。"""
    data = api_result.get("data", [])
    by = intent.get("by", "gender")
    by_zh = P3_DIM_ZH.get(by, by)
    metric = intent.get("metric", "count")
    metric_zh = METRIC_ZH.get(metric, metric)
    cats = [str(r.get("key") or "-") for r in data]
    vals = [r.get("value") or r.get("count") or 0 for r in data]
    pcts = [r.get("pct") or 0 for r in data]
    title_obj = _base_title(suggestion, f"按{by_zh}看人群分布")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}<br/>" + metric_zh + ": {c}"},
        "grid": {"left": 70, "right": 30, "bottom": 60, "top": 50},
        "xAxis": {"type": "category", "data": cats, "name": by_zh},
        "yAxis": {"type": "value", "name": metric_zh},
        "series": [{
            "type": "bar", "name": metric_zh, "data": vals, "barMaxWidth": 80,
            "itemStyle": {"borderRadius": [4, 4, 0, 0]},
            "label": {"show": True, "position": "top", "fontSize": 10},
            "markPoint": {"data": [{"type": "max", "name": "最大值"}]},
        }],
    }
    # 给每条柱标签带上 pct（ECharts 没法直接 lambda，用 raw 数组）
    label_data = [{"value": v, "label": {"show": True, "position": "top",
                                          "formatter": f"{v:,}\n({pcts[i]}%)"}}
                  for i, v in enumerate(vals)]
    option["series"][0]["data"] = label_data
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_pyramid_option(intent, api_result, suggestion):
    """4.5 pyramid 人口金字塔：男为负值向左，女为正值向右（双向条形图）。"""
    data = api_result.get("data", [])
    cats = [str(r.get("age_group") or "-") for r in data]
    male_vals = [-int(r.get("male") or 0) for r in data]  # 取负数让男性向左
    female_vals = [int(r.get("female") or 0) for r in data]
    title_obj = _base_title(suggestion, "人口金字塔（按年龄段 × 性别）")
    option = {
        "color": ["#1e6fd9", "#ff6b6b"],
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}<br/>{a}: {c}"},
        "legend": {"top": 30, "data": ["男", "女"]},
        "grid": {"left": 80, "right": 30, "bottom": 40, "top": 70},
        "xAxis": {"type": "value",
                  "axisLabel": {"formatter": "{value}"}},
        "yAxis": {"type": "category", "data": cats, "inverse": True,
                  "axisLabel": {"fontSize": 11}},
        "series": [
            {"name": "男", "type": "bar", "stack": "pyramid",
             "data": male_vals, "itemStyle": {"color": "#1e6fd9"},
             "label": {"show": True, "position": "left"}},
            {"name": "女", "type": "bar", "stack": "pyramid",
             "data": female_vals, "itemStyle": {"color": "#ff6b6b"},
             "label": {"show": True, "position": "right"}},
        ],
    }
    # 把绝对值显示在标签里（male_vals 是负数，label 显示 |v|）
    option["series"][0]["data"] = [{"value": v, "label": {"show": True, "position": "left",
                                                          "formatter": "{c}"}}
                                    for v in male_vals]
    option["series"][1]["data"] = [{"value": v, "label": {"show": True, "position": "right",
                                                          "formatter": "{c}"}}
                                    for v in female_vals]
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_region_diff_option(intent, api_result, suggestion):
    """4.6 region-diff 横向柱：facility 模式 key 太长，强制横向 + 截断。"""
    data = api_result.get("data", [])
    level = intent.get("level", "service_area")
    level_zh = P3_DIM_ZH.get(level, level)
    metric = intent.get("metric", "count")
    metric_zh = METRIC_ZH.get(metric, metric)
    # 截断长名（医院名可能 30+ 字符）
    name_limit = 25 if level == "facility" else 40
    cats = [(str(r.get("key") or "-"))[:name_limit] for r in data]
    vals = [r.get("value") or r.get("count") or 0 for r in data]
    title_obj = _base_title(suggestion, f"按{level_zh}看住院分布")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 130, "right": 50, "bottom": 40, "top": 50},
        "xAxis": {"type": "value", "name": metric_zh},
        "yAxis": {"type": "category", "data": cats, "inverse": True,
                  "axisLabel": {"fontSize": 10}},
        "series": [{
            "type": "bar", "name": metric_zh, "data": vals, "barMaxWidth": 20,
            "itemStyle": {"borderRadius": [0, 4, 4, 0]},
            "label": {"show": True, "position": "right", "fontSize": 10},
            "markPoint": {"data": [{"type": "max", "name": "最大值"}]},
        }],
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_heatmap_option(intent, api_result, suggestion):
    """4.7 heatmap 热力图：dim1 × dim2 × value 三元组。"""
    data = api_result.get("data", [])
    dim1 = intent.get("dim1", "diagnosis")
    dim2 = intent.get("dim2", "age_group")
    dim1_zh = P3_DIM_ZH.get(dim1, dim1)
    dim2_zh = P3_DIM_ZH.get(dim2, dim2)
    metric = intent.get("metric", "count")
    metric_zh = METRIC_ZH.get(metric, metric)
    # 提取两个轴的标签（按首次出现顺序）
    x_cats, x_seen = [], set()
    y_cats, y_seen = [], set()
    for r in data:
        xv = r.get("dim1_name") or r.get("dim1") or "-"
        if xv not in x_seen:
            x_cats.append(xv); x_seen.add(xv)
        yv = r.get("dim2_name") or r.get("dim2") or "-"
        if yv not in y_seen:
            y_cats.append(yv); y_seen.add(yv)
    # ECharts heatmap 需要 [x_index, y_index, value]
    x_idx = {v: i for i, v in enumerate(x_cats)}
    y_idx = {v: i for i, v in enumerate(y_cats)}
    series_data = []
    max_val = 0
    for r in data:
        xv = r.get("dim1_name") or r.get("dim1") or "-"
        yv = r.get("dim2_name") or r.get("dim2") or "-"
        v = r.get("value") or r.get("count") or 0
        series_data.append([x_idx[xv], y_idx[yv], v])
        if v > max_val:
            max_val = v
    title_obj = _base_title(suggestion, f"{dim1_zh} × {dim2_zh} 热力图")
    option = {
        "title": title_obj,
        "tooltip": {"position": "top"},
        "grid": {"left": 120, "right": 30, "bottom": 100, "top": 70},
        "xAxis": {"type": "category", "data": x_cats, "splitArea": {"show": True},
                  "axisLabel": {"rotate": 35, "interval": 0, "fontSize": 10},
                  "name": dim1_zh},
        "yAxis": {"type": "category", "data": y_cats, "splitArea": {"show": True},
                  "axisLabel": {"fontSize": 10}, "name": dim2_zh},
        "visualMap": {"min": 0, "max": max_val or 1, "calculable": True,
                      "orient": "horizontal", "left": "center", "bottom": 10,
                      "inRange": {"color": ["#e6f7ff", "#69c0ff", "#1890ff", "#0050b3"]}},
        "series": [{
            "type": "heatmap", "data": series_data,
            "label": {"show": False},
            "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0,0,0,0.5)"}},
        }],
    }
    return {"chart_type": "heatmap", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_payment_composition_option(intent, api_result, suggestion):
    """5.1 payment-composition 饼图：key 为扇区，pct 为占比。"""
    data = api_result.get("data", [])
    group = intent.get("group", "payment1")
    group_zh = P3_DIM_ZH.get(group, group)
    meta = api_result.get("meta", {})
    null_excluded = meta.get("null_excluded", 0)
    pie_data = [{"name": r.get("key") or "-", "value": r.get("value") or r.get("count") or 0,
                 "pct": r.get("pct")} for r in data]
    sub_text = ""
    if null_excluded:
        sub_text = f"已排除 {null_excluded:,} 条无该层支付方式记录"
    title_obj = _base_title(suggestion, f"{group_zh}构成")
    if sub_text and "subtext" not in title_obj:
        title_obj["subtext"] = sub_text
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "item",
                    "formatter": "{b}<br/>人数/费用：{c}<br/>占比：{d}%"},
        "legend": {"orient": "vertical", "left": "left", "top": "middle",
                   "type": "scroll"},
        "series": [{
            "type": "pie", "radius": ["40%", "70%"], "center": ["60%", "55%"],
            "label": {"formatter": "{b}\n{d}%"},
            "data": pie_data,
            "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2},
        }],
    }
    return {"chart_type": "pie", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_payment_cross_option(intent, api_result, suggestion):
    """5.2 payment-cross 堆叠柱：X=key（9 类支付），系列=dim2。"""
    data = api_result.get("data", [])
    dim2 = intent.get("dim2", "age_group")
    dim2_zh = P3_DIM_ZH.get(dim2, dim2)
    metric = intent.get("metric", "count")
    metric_zh = METRIC_ZH.get(metric, metric)
    # 提取 X 轴（key）和系列（dim2_name）
    x_cats, x_seen = [], set()
    s_cats, s_seen = [], set()
    for r in data:
        k = r.get("key")
        if k and k not in x_seen:
            x_cats.append(k); x_seen.add(k)
        s = r.get("dim2_name") or r.get("dim2")
        if s and s not in s_seen:
            s_cats.append(s); s_seen.add(s)
    # 二维索引：{x: {series: value}}
    idx = {k: {} for k in x_cats}
    for r in data:
        k, s = r.get("key"), r.get("dim2_name") or r.get("dim2")
        if k in idx:
            idx[k][s] = r.get("value") or r.get("count") or 0
    series = []
    for i, s in enumerate(s_cats):
        series.append({
            "type": "bar", "name": str(s), "stack": "cross",
            "data": [idx[k].get(s, 0) for k in x_cats],
            "itemStyle": {"color": COLORS[i % len(COLORS)]},
            "emphasis": {"focus": "series"},
        })
    title_obj = _base_title(suggestion, f"支付方式 × {dim2_zh} 交叉分析")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"top": 30, "data": [str(s) for s in s_cats], "type": "scroll"},
        "grid": {"left": 70, "right": 30, "bottom": 90, "top": 80},
        "xAxis": {"type": "category", "data": [str(k) for k in x_cats],
                  "axisLabel": {"rotate": 30, "interval": 0, "fontSize": 10},
                  "name": "支付方式"},
        "yAxis": {"type": "value", "name": metric_zh},
        "series": series,
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_sankey_option(intent, api_result, suggestion):
    """5.3 sankey 桑葚图：直接消费 P3 返回的 nodes/links。"""
    raw = api_result.get("data") or {}
    if isinstance(raw, list):  # 容错：某些实现可能返回 list
        raw = {"nodes": [], "links": []}
    nodes = raw.get("nodes", [])
    links = raw.get("links", [])
    # 节点按 layer_index 着色
    for n in nodes:
        li = n.get("layer_index", 0)
        n["itemStyle"] = {"color": SANKEY_LAYER_COLORS[li % len(SANKEY_LAYER_COLORS)]}
        n["label"] = {"formatter": n.get("display") or n.get("name")}
    title_obj = _base_title(suggestion, "支付流向桑葚图")
    meta = api_result.get("meta", {})
    null_excluded = meta.get("null_excluded", 0)
    levels = meta.get("levels", "payment,payment2")
    sub_text = ""
    if null_excluded:
        # 计算占比：null_excluded 占 (null_excluded + total) 的比例
        total = meta.get("total_records", 0) or 0
        if total + null_excluded:
            kept_pct = total * 100.0 / (total + null_excluded)
            sub_text = f"链路 {levels}：仅 {total:,} 条记录走完全程（占 {kept_pct:.1f}%）"
    if sub_text and "subtext" not in title_obj:
        title_obj["subtext"] = sub_text
    option = {
        "title": title_obj,
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "sankey", "data": nodes, "links": links,
            "emphasis": {"focus": "adjacency"},
            "lineStyle": {"color": "gradient", "curveness": 0.5, "opacity": 0.5},
            "label": {"fontSize": 11},
            "layoutIterations": 32,
        }],
    }
    return {"chart_type": "sankey", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_cost_relation_option(intent, api_result, suggestion):
    """5.4 cost-relation 散点图：X=avg_costs，Y=avg_charges，气泡=count，颜色=ratio。"""
    data = api_result.get("data", [])
    by = intent.get("by", "payment")
    by_zh = P3_DIM_ZH.get(by, by)
    # 找 ratio 范围
    ratios = [r.get("charge_cost_ratio") or 0 for r in data]
    ratio_max = max(ratios) if ratios else 5
    ratio_min = min(ratios) if ratios else 1
    series_data = []
    for r in data:
        v = [
            float(r.get("avg_costs") or 0),
            float(r.get("avg_charges") or 0),
            int(r.get("count") or 0),
            float(r.get("charge_cost_ratio") or 0),
            r.get("key") or r.get("name") or "-",
        ]
        series_data.append({"value": v, "name": v[4]})
    title_obj = _base_title(suggestion, f"按{by_zh}看费用-成本关系")
    option = {
        "title": title_obj,
        "tooltip": {"trigger": "item",
                    "formatter": "{b}<br/>成本: {c[0]}<br/>费用: {c[1]}<br/>人数: {c[2]}<br/>费/本比: {c[3]}"},
        "grid": {"left": 80, "right": 30, "bottom": 60, "top": 50},
        "xAxis": {"type": "value", "name": "平均成本（元）", "scale": True},
        "yAxis": {"type": "value", "name": "平均费用（元）", "scale": True},
        "visualMap": {"show": True, "min": ratio_min, "max": max(ratio_max, ratio_min + 0.1),
                      "dimension": 3, "calculable": True,
                      "orient": "horizontal", "left": "center", "bottom": 5,
                      "inRange": {"color": ["#52c41a", "#faad14", "#ff4d4f"]},
                      "text": ["费用/成本比高", "低"]},
        "series": [{
            "type": "scatter", "data": series_data,
            "symbolSize": 20,
            "label": {"show": True, "position": "top", "formatter": "{b}",
                      "fontSize": 10},
            "emphasis": {"label": {"show": True}},
        }],
    }
    # ECharts symbolSize 在 Python 端不好传 lambda，用预计算的 size 数组
    counts = [int(r.get("count") or 0) for r in data]
    cmax = max(counts) if counts else 1
    series_data2 = []
    for i, r in enumerate(data):
        size = 10 + (counts[i] * 30.0 / cmax) if cmax else 10
        series_data2.append({
            "value": [float(r.get("avg_costs") or 0), float(r.get("avg_charges") or 0),
                      counts[i], float(r.get("charge_cost_ratio") or 0)],
            "name": r.get("key") or r.get("name") or "-",
            "symbolSize": min(size, 60),
        })
    option["series"][0]["data"] = series_data2
    return {"chart_type": "scatter", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_oop_burden_option(intent, api_result, suggestion):
    """5.5 oop-burden 横向柱：X=key，Y=self_pay_pct（自付占比%）。"""
    data = api_result.get("data", [])
    dimension = intent.get("dimension", "disease")
    dim_zh = P3_DIM_ZH.get(dimension, dimension)
    mode = intent.get("mode", "selfpay1")
    # 截断长名
    name_limit = 25 if dimension == "disease" else 40
    cats = [(str(r.get("key") or "-"))[:name_limit] for r in data]
    pcts = [float(r.get("self_pay_pct") or 0) for r in data]
    title_obj = _base_title(suggestion, f"按{dim_zh}看自付负担（{mode} 模式）")
    option = {
        "color": ["#fa8c16"],
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}<br/>自付占比: {c}%"},
        "grid": {"left": 130, "right": 50, "bottom": 40, "top": 50},
        "xAxis": {"type": "value", "name": "自付占比（%）", "axisLabel": {"formatter": "{value}%"}},
        "yAxis": {"type": "category", "data": cats, "inverse": True,
                  "axisLabel": {"fontSize": 10}},
        "series": [{
            "type": "bar", "name": "自付占比", "data": pcts, "barMaxWidth": 20,
            "itemStyle": {"borderRadius": [0, 4, 4, 0]},
            "label": {"show": True, "position": "right", "fontSize": 10,
                      "formatter": "{c}%"},
            "markPoint": {"data": [{"type": "max", "name": "最大负担"}]},
        }],
    }
    # enriched data：把更多字段塞进 series.data，前端 tooltip 可自行扩展
    enriched = []
    for r in data:
        enriched.append({
            "value": float(r.get("self_pay_pct") or 0),
            "self_pay_count": r.get("self_pay_count"),
            "self_pay_avg_charges": r.get("self_pay_avg_charges"),
            "self_pay_share_of_charges": r.get("self_pay_share_of_charges"),
            "name": (str(r.get("key") or "-"))[:name_limit],
        })
    option["series"][0]["data"] = enriched
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_payment_summary_option(intent, api_result, suggestion):
    """5.6 payment-summary KPI 卡片：用 dataset + 多 series-gauge 或纯文本。

    由于 ECharts 没有原生"卡片"组件，这里用 graphic + 文本近似渲染。
    返回 chart_type=kpi，前端可识别并改用 HTML 卡片渲染；如果前端没适配，
    也能 fallback 到一个柱状图展示严重程度分布。
    """
    raw = api_result.get("data") or {}
    if isinstance(raw, list):  # 容错
        raw = {}
    kpi_data = {
        "total_records": raw.get("total_records", 0),
        "total_charges": raw.get("total_charges", 0),
        "total_costs": raw.get("total_costs", 0),
        "avg_charges": raw.get("avg_charges", 0),
        "avg_costs": raw.get("avg_costs", 0),
        "avg_los": raw.get("avg_los", 0),
        "self_pay_count": raw.get("self_pay_count", 0),
        "self_pay_pct": raw.get("self_pay_pct", 0),
        "top_payment": raw.get("top_payment", {}),
        "ed_count": raw.get("ed_count", 0),
    }
    sev = raw.get("severity_distribution", {})
    sev_data = [{"name": SEVERITY_ZH.get(k, k), "value": v, "color": SEVERITY_COLORS.get(k),
                 "code": k}
                for k, v in sev.items() if k in SEVERITY_ORDER]
    # 按 Minor → Extreme 固定顺序排（用 code 字段反查 SEVERITY_ORDER，避免 next() 崩）
    sev_data.sort(key=lambda x: SEVERITY_ORDER.index(x["code"]) if x["code"] in SEVERITY_ORDER else 99)
    title_obj = _base_title(suggestion, "KPI 总览大屏")
    # 用饼图展示严重程度分布作为主图（KPI 数字放 title 的 subtext）
    pie_data = [{"name": d["name"], "value": d["value"]} for d in sev_data]
    sub_lines = [
        f"总记录 {kpi_data['total_records']:,} 条",
        f"总费用 {kpi_data['total_charges']:,.0f} 元",
        f"次均费用 {kpi_data['avg_charges']:,.2f} 元",
        f"平均住院 {kpi_data['avg_los']} 天",
        f"自付占比 {kpi_data['self_pay_pct']}%",
    ]
    if kpi_data["top_payment"]:
        tp = kpi_data["top_payment"]
        sub_lines.append(f"主要支付：{tp.get('key', '-')}（{tp.get('pct', 0)}%）")
    title_obj["subtext"] = "\n".join(sub_lines)
    title_obj["subtextStyle"] = {"fontSize": 11, "lineHeight": 16}
    option = {
        "color": [d["color"] for d in sev_data],
        "title": title_obj,
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"orient": "vertical", "left": "left", "top": "middle"},
        "series": [{
            "type": "pie", "radius": ["35%", "60%"], "center": ["65%", "55%"],
            "label": {"formatter": "{b}\n{d}%"},
            "data": pie_data,
            "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2},
        }],
    }
    return {"chart_type": "kpi", "option": option, "kpi": kpi_data,
            "_suggestion_source": "llm" if suggestion else "rules"}


# chart_hint → 图表构造函数路由表
CHART_BUILDERS = {
    "top_diagnoses":       _build_top_diagnoses_option,
    "top_procedures":      _build_top_procedures_option,
    "severity_profile":    _build_severity_profile_option,
    "population_diff":     _build_population_diff_option,
    "pyramid":             _build_pyramid_option,
    "region_diff":         _build_region_diff_option,
    "heatmap":             _build_heatmap_option,
    "payment_composition": _build_payment_composition_option,
    "payment_cross":       _build_payment_cross_option,
    "sankey":              _build_sankey_option,
    "cost_relation":       _build_cost_relation_option,
    "oop_burden":          _build_oop_burden_option,
    "payment_summary":     _build_payment_summary_option,
}


def generate_chart_config(intent: dict, api_result: dict, use_llm: bool = True) -> dict:
    """根据分析结果类型，生成美观、完整的 ECharts option 配置。

    架构：
      - 规则引擎：负责生成稳定、可渲染的 option 结构（核心）
      - LLM 辅助（可选）：给出图表类型建议 + 个性化标题 + 副标题

    路由优先级：
      1) chart_hint 命中 CHART_BUILDERS → 直接走 P3 新版专用构造器（13 种新图表）
      2) 未命中 → 走旧版 metric 路由（pie/line/bar，向后兼容）
    """
    # —— 路由1：chart_hint 命中 P3 新接口专用图表构造器 ——
    chart_hint = intent.get("chart_hint")
    if chart_hint and chart_hint in CHART_BUILDERS:
        # LLM 标题建议仍然调用（让标题更生动），但 chart_type 不取 LLM 的（专用图表固定）
        suggestion = {}
        if use_llm and LLM_ENABLED:
            try:
                # 复用旧 LLM：它会返回 title/subtitle/chart_type，我们只取 title/subtitle
                # 用 P3 维度翻译更友好
                p3_dim_zh = (P3_DIM_ZH.get(chart_hint, "")
                             or DIMENSION_ZH.get(intent.get("dimension", ""), "维度"))
                p3_metric_zh = METRIC_ZH.get(intent.get("metric", ""), intent.get("metric", ""))
                # 给 LLM 一条空 data（P3 数据可能很大，不必全部塞进 prompt）
                sample = (api_result.get("data", []) or [])[:3]
                suggestion = _suggest_chart_by_llm(intent, p3_dim_zh, p3_metric_zh, sample)
            except Exception:
                suggestion = {}
        try:
            return CHART_BUILDERS[chart_hint](intent, api_result, suggestion)
        except Exception as e:
            # 兜底：专用构造器异常时降级到旧版 metric 路由（保证总有图出）
            print(f"[CHART BUILDER ERROR] {chart_hint}: {e}，降级到旧版 metric 路由")

    # —— 路由2：旧版 metric 路由（pie/line/bar）—— 向后兼容
    data = api_result.get("data", [])
    metric = intent["metric"]
    metric_zh = METRIC_ZH.get(metric, metric)
    dim_zh = DIMENSION_ZH.get(intent.get("dimension", ""), "维度")
    default_title = f"{dim_zh} × {metric_zh}"

    # —— LLM 辅助：先问 LLM 有什么好的建议（不阻塞核心逻辑，超时/乱码直接忽略）——
    suggestion = {}
    if use_llm and LLM_ENABLED and data:
        try:
            suggestion = _suggest_chart_by_llm(intent, dim_zh, metric_zh, data)
        except Exception:
            suggestion = {}  # 永远不让 LLM 的错影响出图
    suggestion_title = suggestion.get("title") or default_title
    suggestion_subtitle = suggestion.get("subtitle") or ""
    suggestion_ct = suggestion.get("chart_type")

    # —— 规则引擎：稳定出图（核心，不依赖 LLM）——
    # 先按 metric 规则定类型，若 LLM 给了合法建议且没冲突，就采用
    if metric == "payment_mix":
        chart_type = "pie"  # 占比必须用饼图，LLM 建议也覆盖不了
    elif metric == "trend":
        chart_type = "line"  # 时间趋势必须用折线
    else:
        chart_type = suggestion_ct if suggestion_ct in {"bar", "line"} else "bar"

    title_obj = {"text": suggestion_title, "left": "center", "textStyle": {"fontSize": 15}}
    if suggestion_subtitle:
        title_obj["subtext"] = suggestion_subtitle
        title_obj["itemGap"] = 8

    # --- 情况1：支付占比 → 饼图 ---
    if chart_type == "pie":
        pie_data = [{"name": r.get("payment"), "value": r.get("count"),
                     "pct": r.get("pct")} for r in data]
        option = {
            "color": COLORS,
            "title": title_obj,
            "tooltip": {"trigger": "item",
                        "formatter": "{b}<br/>人数：{c}<br/>占比：{d}%"},
            "legend": {"orient": "vertical", "left": "left", "top": "middle"},
            "series": [{
                "type": "pie", "radius": ["40%", "70%"],
                "center": ["55%", "55%"],
                "label": {"formatter": "{b}\n{d}%"},
                "data": pie_data,
                "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2}
            }],
        }

    # --- 情况2：趋势 → 折线图 ---
    elif chart_type == "line":
        line_data = [r.get("count") or r.get("value") for r in data]
        line_cats = [str(r.get("year") or r.get("key")) for r in data]
        option = {
            "color": COLORS,
            "title": title_obj,
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 60, "right": 30, "bottom": 50, "top": 50},
            "xAxis": {"type": "category", "boundaryGap": False,
                      "data": line_cats, "name": dim_zh},
            "yAxis": {"type": "value", "name": metric_zh},
            "series": [{
                "type": "line", "name": metric_zh,
                "smooth": True, "symbol": "circle", "symbolSize": 8,
                "data": line_data,
                "areaStyle": {"opacity": 0.2},
                "label": {"show": True, "position": "top"},
            }],
        }

    # --- 情况3：柱状图 ---
    else:  # bar
        bar_data = [r.get("value") or r.get("count") for r in data]
        categories = [str(r.get("key") or r.get("year") or r.get("payment")) for r in data]
        option = {
            "color": COLORS,
            "title": title_obj,
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 70, "right": 30, "bottom": 90, "top": 50},
            "legend": {"top": 30},
            "xAxis": {
                "type": "category",
                "data": categories,
                "axisLabel": {"rotate": 40, "interval": 0, "fontSize": 11},
                "name": dim_zh,
            },
            "yAxis": {"type": "value", "name": metric_zh},
            "series": [{
                "type": "bar", "name": metric_zh,
                "data": bar_data,
                "barMaxWidth": 50,
                "itemStyle": {"borderRadius": [4, 4, 0, 0]},
                "label": {"show": True, "position": "top", "fontSize": 10},
                "markPoint": {"data": [{"type": "max", "name": "最大值"}]},
            }],
        }

    return {"chart_type": chart_type, "option": option, "_suggestion_source":
            "llm" if suggestion else "rules"}


# ------------------------------------------------------------
# 6. 医疗洞察报告生成（LLM 个性化生成 + 模板兜底）
# ------------------------------------------------------------
_REPORT_SYSTEM_PROMPT = """你是智慧医疗大数据平台的「资深报告撰写分析师」。
你的任务：基于提供的结构化医疗分析结果，输出一份严格的 JSON 格式洞察报告。

⚠️ 严格要求：
1. 数据必须忠于输入，禁止编造数字。
2. 语言专业、具体、贴合医疗业务，禁止空洞的套话（如"加强管理"），必须说清楚"关注什么指标""做什么事"。
3. 每个 key_findings 必须是一个有洞察的句子，不能只是"排名XX的是XX"——要带对比（"高于第二名 2.3 倍"）或业务解读（"占总住院的 25%"）。
4. 每个 recommendation 必须具体可执行，结合本报告的数据，不能用通用模板。
5. 控制长度：summary 50-100字；每个 key_findings 1句话；recommendations 3-4条。
6. 输出必须是严格合法的 JSON，不要加 markdown 代码块，不要任何解释文字。

输出格式：
{
  "summary": "一句话概括本报告分析了什么，覆盖多少条数据，核心洞察方向",
  "key_findings": ["发现1（带具体数字）", "发现2（带对比）", "发现3（业务解读）"],
  "recommendations": ["建议1（具体）", "建议2（具体）", "建议3（具体）"]
}
"""


def _generate_report_by_llm(context: str) -> tuple[bool, dict, str]:
    """让 LLM 生成个性化洞察报告（JSON 输出）。"""
    if not LLM_ENABLED:
        return False, {}, "LLM 未启用"

    messages = [
        {"role": "system", "content": _REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": f"【待分析的数据】\n{context}\n\n请按要求输出 JSON 报告："},
    ]
    ok, content = _call_llm_safely(messages)
    if not ok:
        return False, {}, content

    # 解析 JSON（容错）
    import re as _re
    cleaned = content.strip()
    for _ in range(3):
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
            cleaned = _re.sub(r"^[a-zA-Z]*\s*", "", cleaned, count=1)
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    match = _re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, _re.DOTALL)
    if match:
        cleaned = match.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return False, {}, f"LLM 返回非合法 JSON: {e}。原文: {content[:200]}"

    # 字段类型校验 + 兜底
    summary = data.get("summary") or ""
    if not isinstance(summary, str):
        summary = str(summary)
    key_findings = data.get("key_findings") or []
    if not isinstance(key_findings, list):
        key_findings = [str(key_findings)]
    key_findings = [str(f) for f in key_findings[:6]]  # 最多 6 条
    recommendations = data.get("recommendations") or []
    if not isinstance(recommendations, list):
        recommendations = [str(recommendations)]
    recommendations = [str(r) for r in recommendations[:5]]

    return True, {
        "summary": summary,
        "key_findings": key_findings,
        "recommendations": recommendations,
    }, ""


def _fallback_report_template(sections_meta: list[dict], total_records: int,
                              sections_count: int) -> dict:
    """模板兜底：LLM 失败时生成的通用报告，保证用户至少能看。"""
    def _default_recs():
        return [
            "🏥 建议重点关注高费用/长住院时长的疾病类型，优化诊疗路径以降低平均住院天数。",
            "💳 关注支付方式占比变化趋势，配合医保政策做好医院收费结构优化。",
            "📈 定期跟踪疾病趋势，对发病率上升较快的病种提前做好资源储备与预防宣传。",
            "⚠️ 针对病情严重程度高的病例，建立专项质量评估与随访机制。",
        ]

    return {
        "summary": (
            f"本报告共整合 {sections_count} 个维度的医疗数据洞察，覆盖"
            f" {total_records:,} 条住院记录。"
        ),
        "recommendations": _default_recs(),
    }


# chart_hint → 报告 section 标题中文名（用于报告展示，比 dimension 更直观）
CHART_HINT_TITLE_ZH = {
    "top_diagnoses":       "Top 诊断排行",
    "top_procedures":      "Top 手术排行",
    "severity_profile":    "病重程度构成",
    "population_diff":    "人群分布差异",
    "pyramid":            "人口金字塔",
    "region_diff":        "地区分布差异",
    "heatmap":            "诊断×维度热力图",
    "payment_composition": "支付方式构成",
    "payment_cross":      "支付×维度交叉",
    "sankey":             "支付流向桑葚图",
    "cost_relation":      "费用-成本关系",
    "oop_burden":         "自付负担分析",
    "payment_summary":    "KPI 总览大屏",
}


def _extract_topn_keyvalue(item: dict, chart_hint: str | None = None) -> tuple[str, object]:
    """从 P3 数据项中提取 (key, value)，按 chart_hint 选择字段优先级。

    不同 chart_hint 的数据结构差异较大：
      - top_diagnoses/top_procedures: {code, name, value/count}
      - severity_profile: {group, severity, value/count}      → key = "group/severity_zh"
      - population_diff/region_diff/payment_composition: {key, value/count, pct?}
      - pyramid: {age_group, male, female, total}             → value = total
      - heatmap: {dim1_name/dim1, dim2_name/dim2, value/count} → key = "x × y"
      - payment_cross: {key, dim2_name/dim2, value/count}      → key = "key × dim2"
      - cost_relation: {key, charge_cost_ratio, avg_charges...} → value = ratio
      - oop_burden: {key, self_pay_count, self_pay_pct}        → value = self_pay_count
      - sankey/payment_summary: data 是 dict 不是 list，不应调用本函数
    """
    if not isinstance(item, dict):
        return ("-", 0)

    if chart_hint == "severity_profile":
        g = item.get("group") or "-"
        s = item.get("severity") or "-"
        key = f"{g}/{SEVERITY_ZH.get(s, s)}"
        value = item.get("value") or item.get("count") or 0
    elif chart_hint == "pyramid":
        key = item.get("age_group") or "-"
        m, f = item.get("male", 0) or 0, item.get("female", 0) or 0
        value = item.get("total") or (m + f)
    elif chart_hint == "heatmap":
        x = item.get("dim1_name") or item.get("dim1") or "-"
        y = item.get("dim2_name") or item.get("dim2") or "-"
        key = f"{x} × {y}"
        value = item.get("value") or item.get("count") or 0
    elif chart_hint == "payment_cross":
        k = item.get("key") or "-"
        s = item.get("dim2_name") or item.get("dim2") or "-"
        key = f"{k} × {s}"
        value = item.get("value") or item.get("count") or 0
    elif chart_hint == "cost_relation":
        key = item.get("key") or "-"
        value = item.get("charge_cost_ratio") or 0
    elif chart_hint == "oop_burden":
        key = item.get("key") or "-"
        value = item.get("self_pay_count") or 0
    else:
        # 通用：top_diagnoses/top_procedures/population_diff/region_diff/payment_composition/旧路由
        key = (item.get("name") or item.get("key") or item.get("payment")
               or item.get("year") or "-")
        value = (item.get("value") or item.get("pct")
                 or item.get("count") or 0)
    return (key, value)


def _build_section_findings(chart_hint: str | None, data, meta: dict) -> list[str]:
    """生成 report section 的 key_findings（Top3 或特殊结构）。

    返回最多 3 条字符串。处理 3 种情形：
      1) sankey: data 是 dict {nodes, links}，提取 Top3 流向
      2) payment_summary: data 是 dict (KPI 大屏)，提取关键 KPI
      3) 其他: data 是 list，按 chart_hint 走 _extract_topn_keyvalue 取 Top3 + ratio
    """
    findings: list[str] = []

    # —— 特殊 1：sankey 的 data 是 dict（nodes/links）——
    if chart_hint == "sankey":
        raw = data if isinstance(data, dict) else {}
        links = raw.get("links", []) or []
        top_links = sorted(links, key=lambda l: l.get("value") or 0, reverse=True)[:3]
        for j, lk in enumerate(top_links):
            src = lk.get("source", "-")
            tgt = lk.get("target", "-")
            # 去掉 layer 前缀让展示更友好（"支付1|Medicare" → "Medicare"）
            if "|" in src:
                src = src.split("|", 1)[1]
            if "|" in tgt:
                tgt = tgt.split("|", 1)[1]
            v = lk.get("value", 0) or 0
            findings.append(f"第{j+1}大流向：「{src}」→「{tgt}」流量 {v:,}")
        return findings

    # —— 特殊 2：payment_summary 的 data 是 dict（KPI 大屏）——
    if chart_hint == "payment_summary":
        if not isinstance(data, dict) or not data:
            return findings
        findings.append(f"总记录 {data.get('total_records', 0):,} 条 · "
                        f"总费用 {data.get('total_charges', 0):,.0f} 元")
        findings.append(f"次均费用 {data.get('avg_charges', 0):,.2f} 元 / "
                        f"次均成本 {data.get('avg_costs', 0):,.2f} 元 / "
                        f"平均住院 {data.get('avg_los', 0)} 天")
        sp_count = data.get("self_pay_count", 0) or 0
        sp_pct = data.get("self_pay_pct", 0) or 0
        tp = data.get("top_payment") or {}
        tp_str = f" · 主要支付「{tp.get('key', '-')}」({tp.get('pct', 0)}%)" if tp else ""
        findings.append(f"自付 {sp_count:,} 人（{sp_pct}%）{tp_str}")
        return findings

    # —— 通用：data 是 list，按 chart_hint 取 Top3 ——
    if not isinstance(data, list) or not data:
        return findings

    top_n = min(3, len(data))
    for j in range(top_n):
        item = data[j]
        key, value = _extract_topn_keyvalue(item, chart_hint)
        # 计算 ratio = 当前 / 下一名
        v1 = value
        v2 = None
        if j + 1 < len(data):
            _, v2 = _extract_topn_keyvalue(data[j + 1], chart_hint)
        # 格式化 value
        if isinstance(value, float):
            v_str = f"{value:,.2f}"
        elif isinstance(value, int):
            v_str = f"{value:,}"
        else:
            v_str = str(value)
        if v2:
            try:
                ratio = float(v1) / float(v2) if v2 else 1
                findings.append(
                    f"排名第{j+1}的是「{key}」，指标值为 {v_str}，是第二名的 {ratio:.2f} 倍"
                )
            except (TypeError, ZeroDivisionError, ValueError):
                findings.append(f"排名第{j+1}的是「{key}」，指标值为 {v_str}")
        else:
            findings.append(f"排名第{j+1}的是「{key}」，指标值为 {v_str}")
    return findings


def generate_insight_report(single_result: dict = None, multi_results: list = None,
                            use_llm: bool = True) -> dict:
    """基于分析结果生成结构化医疗洞察报告。
    两种使用场景：
      a) single_result：针对单个分析结果生成简要报告（用户问完后自动生成）
      b) multi_results：整合多个维度分析结果，生成完整报告（Dashboard 大屏用）

    use_llm=True 时优先用 LLM 生成个性化报告，失败自动降级到模板。
    返回报告字典，字段：title / generated_at / summary / sections / recommendations
    """
    report = {
        "title": "智慧医疗数据洞察报告",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": "",
        "sections": [],
        "recommendations": [],
        "report_source": "template",  # llm / template，前端可展示
    }

    results = multi_results if multi_results else ([single_result] if single_result else [])

    total_records = 0
    sections_meta = []
    for i, r in enumerate(results):
        if not r:
            continue
        api_result = r.get("api_result", r) if isinstance(r, dict) else {}
        data = api_result.get("data", [])
        meta = api_result.get("meta", {})

        # 从 r.intent 读 chart_hint（用于走专用字段提取和标题生成）
        chart_hint = None
        if isinstance(r, dict):
            _intent = r.get("intent")
            if isinstance(_intent, dict):
                chart_hint = _intent.get("chart_hint")

        # sankey 和 payment_summary 的 data 是 dict（不是 list），
        # 既不是空也不能按 list 走 Top3 逻辑，统一交给 _build_section_findings 处理
        is_dict_data = chart_hint in ("sankey", "payment_summary")
        if (is_dict_data and not data) or (not is_dict_data and not data):
            continue

        dim_code = meta.get("dimension", "-")
        metric_code = meta.get("metric", "-")
        # chart_hint 命中时优先用 CHART_HINT_TITLE_ZH（更直观），否则降级到 dimension_zh
        if chart_hint and chart_hint in CHART_HINT_TITLE_ZH:
            section_dim_zh = CHART_HINT_TITLE_ZH[chart_hint]
            dim_zh = section_dim_zh
        else:
            dim_zh = DIMENSION_ZH.get(dim_code, dim_code)
            section_dim_zh = dim_zh
        metric_zh = METRIC_ZH.get(metric_code, metric_code)
        records = meta.get("total_records", 0) or 0
        total_records += records

        # 关键发现（先用规则生成一份保底；sankey/payment_summary 走专用分支）
        rule_findings = _build_section_findings(chart_hint, data, meta)

        # data_sample：list 取前 10 项；dict（sankey/summary）整体给前端
        data_sample = data[:10] if isinstance(data, list) else data

        report["sections"].append({
            "section_title": f"分析维度 {i+1}：{section_dim_zh}",
            "key_findings": rule_findings,
            "chart_type": r.get("chart", {}).get("chart_type") if isinstance(r, dict) and "chart" in r else "bar",
            "data": data_sample,
            "meta": {
                "dimension": dim_code,
                "metric": metric_code,
                "dimension_zh": dim_zh,
                "metric_zh": metric_zh,
                "total_records": records,
                "chart_hint": chart_hint,
            },
        })
        sections_meta.append({
            "dim": dim_zh, "metric": metric_zh, "records": records,
            "top3": rule_findings,
            "chart_hint": chart_hint,
        })

    sections_count = len(report["sections"])
    # —— LLM 个性化生成报告（优先）——
    if use_llm and LLM_ENABLED and sections_meta:
        # 给 LLM 的上下文：每个维度的核心信息（不要传太多数据省 token）
        context_parts = []
        for i, sm in enumerate(sections_meta, 1):
            context_parts.append(
                f"【维度{i}】{sm['dim']} × {sm['metric']}\n"
                f"   覆盖记录数: {sm['records']:,}\n"
                f"   Top3发现: {'; '.join(sm['top3'])}"
            )
        context_parts.append(f"【合计】{sections_count} 个维度 · {total_records:,} 条记录")
        context = "\n\n".join(context_parts)

        ok, llm_report, reason = _generate_report_by_llm(context)
        if ok:
            report["summary"] = llm_report.get("summary") or report.get("summary", "")
            report["recommendations"] = llm_report.get("recommendations", [])
            # 如果 LLM 给了 key_findings，把它附加到第一个 section 的 key_findings 后面（作为"深度洞察"）
            if llm_report.get("key_findings") and report["sections"]:
                report["sections"][0]["deep_insights"] = llm_report["key_findings"]
            report["report_source"] = "llm"
        else:
            # LLM 失败：默默降级到模板兜底
            tpl = _fallback_report_template(sections_meta, total_records, sections_count)
            report["summary"] = tpl["summary"]
            report["recommendations"] = tpl["recommendations"]
            report["report_source"] = "template_fallback"
            report["_llm_failure"] = reason[:150]
    else:
        # 没启用 LLM：直接模板
        tpl = _fallback_report_template(sections_meta, total_records, sections_count)
        report["summary"] = tpl["summary"]
        report["recommendations"] = tpl["recommendations"]
        report["report_source"] = "template"

    return report


# ------------------------------------------------------------
# 7. 主流程：自然语言 -> 分析结果（文字 + 图表配置 + 洞察报告）
# ------------------------------------------------------------
def handle_question(question: str, with_report: bool | str = False,
                    conversation_id: str | None = None,
                    use_llm_intent: bool = True) -> dict:
    """AI 智能交互完整闭环。

    with_report 支持三种形式：
      - False：不生成报告（最快）
      - True：同步生成报告（默认方式，慢，但一次性返回全量）
      - "async"：异步生成报告，先返回摘要+图表，报告写入 ASYNC_REPORT_STORE，
                 前端轮询 /api/report/status?report_id=xxx 取结果
    conversation_id 不为空时，启用多轮对话：读取历史上下文 + 记录本轮到历史
    use_llm_intent=True 时，优先用 LLM 解析意图（二期功能），失败自动降级到规则
    """
    # 1. 意图解析（LLM 优先，带上下文）
    intent = parse_intent(question, conversation_id=conversation_id,
                          use_llm=use_llm_intent)

    # 2. 调用后端分析 API（规则路由，LLM 审查写入 meta，不改变路由）
    api_result = call_analysis_api(intent, question=question)

    # 3. 文本摘要（如果有多轮历史，告诉 LLM 让回答更连贯）
    history = MEMORY.get_history(conversation_id)
    summary = generate_text_summary(question, intent, api_result, history=history)

    # 4. 图表配置
    chart = generate_chart_config(intent, api_result)

    result = {
        "question": question,
        "intent": intent,
        "answer": summary,
        "chart": chart,
        "meta": api_result.get("meta", {}),
    }

    # 5. 记录本轮到会话历史（为下一轮多轮对话做准备，并支持历史详情回看）
    if conversation_id:
        # 存入历史的 intent 去掉调试字段，只留核心字段
        clean_intent = {k: v for k, v in intent.items() if not k.startswith("_")}
        # 同时存入 answer + chart，前端可在"历史详情"里直接展示当时回答的图文
        MEMORY.add_turn(conversation_id, question, clean_intent,
                        answer=summary, chart=chart)
        result["conversation_id"] = conversation_id
        result["conversation_turn"] = len(MEMORY.get_history(conversation_id))

    # 6. 医疗洞察报告（同步 / 异步 二选一）
    async_mode = (isinstance(with_report, str) and with_report.lower() == "async")
    if with_report and not async_mode:
        # 同步：报告慢，但返回完整
        result["report"] = generate_insight_report(single_result={
            "api_result": api_result,
            "chart": chart,
        })
    elif async_mode:
        # 异步：起一个后台线程生成，返回 report_id 让前端轮询
        report_id = _submit_async_report(api_result=api_result, chart=chart)
        result["report_pending"] = True
        result["report_id"] = report_id
        result["report"] = None  # 先给占位，等前端查状态再取

    return result


# ------------------------------------------------------------
# 7.1 异步报告存储 + 任务提交（简单实现：内存字典 + 线程）
# 说明：这是「先返回关键路径 + 稍后补报告」的轻量实现；
#       若上生产可换 Celery / RQ / Redis Stream 做任务队列。
# ------------------------------------------------------------
import concurrent.futures

_REPORT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.getenv("ASYNC_REPORT_WORKERS", "4")),
    thread_name_prefix="async_report",
)
ASYNC_REPORT_STORE: dict[str, dict] = {}
_ASYNC_REPORT_LOCK = threading.Lock()
_ASYNC_REPORT_MAX = 500  # 最多挂 500 个报告结果，多了就踢最旧的（LRU 粗粒度）
# D1 修复：异步报告 TTL 过期（默认 1 小时未读取自动清理，可配）
ASYNC_REPORT_TTL_SECONDS = int(os.getenv("ASYNC_REPORT_TTL_SECONDS", str(60 * 60)))


def _async_report_ttl_sweep_locked(ratio: float = 0.2) -> int:
    """持有锁的情况下做一次「懒清理」：扫描 ratio 比例（默认 20%）的最旧条目，
    把已过期的（距 created_ts >= ASYNC_REPORT_TTL_SECONDS）删掉。
    返回清理条数。方便每次提交/查询时顺手跑，避免单独开定时器。
    """
    ttl = ASYNC_REPORT_TTL_SECONDS  # 允许 0（立刻过期）/ 1（测试），不强制最小 60s
    now = time.time()
    all_keys = list(ASYNC_REPORT_STORE.keys())
    if not all_keys:
        return 0
    sample_size = max(1, int(len(all_keys) * ratio))
    scan_keys = all_keys[:sample_size]  # Python 3.7+ dict keys 保持插入顺序，从最旧开始扫正好
    removed = 0
    for k in scan_keys:
        entry = ASYNC_REPORT_STORE.get(k)
        if entry is None:
            continue
        created_ts = entry.get("created_ts", 0)
        if now - created_ts >= ttl:
            ASYNC_REPORT_STORE.pop(k, None)
            removed += 1
    return removed


def _submit_async_report(api_result: dict, chart: dict) -> str:
    """提交一个异步报告任务，返回 report_id（用于 /api/report/status 查询）"""
    report_id = "rp_" + uuid.uuid4().hex
    now = time.time()

    # 先占位：状态 = pending
    with _ASYNC_REPORT_LOCK:
        # 顺手做一次过期懒清理（不占关键路径太久）
        try:
            _async_report_ttl_sweep_locked(0.1)
        except Exception:
            pass
        ASYNC_REPORT_STORE[report_id] = {
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "created_ts": now,            # D1：秒级时间戳，用于 TTL 判断
            "last_access_ts": now,        # D1：最后一次访问时间（读就更新）
            "started_at": None,
            "finished_at": None,
            "report": None,
            "error": None,
        }
        # 粗粒度 LRU：超过上限就删最旧的 10%
        if len(ASYNC_REPORT_STORE) > _ASYNC_REPORT_MAX:
            keys_to_del = list(ASYNC_REPORT_STORE.keys())[
                :int(_ASYNC_REPORT_MAX * 0.1)
            ]
            for k in keys_to_del:
                ASYNC_REPORT_STORE.pop(k, None)

    # 后台线程里生成报告
    def _runner():
        with _ASYNC_REPORT_LOCK:
            entry = ASYNC_REPORT_STORE.get(report_id)
            if entry is None:
                return
            entry["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            report = generate_insight_report(single_result={
                "api_result": api_result,
                "chart": chart,
            })
            with _ASYNC_REPORT_LOCK:
                entry = ASYNC_REPORT_STORE.get(report_id)
                if entry is None:
                    return
                entry["status"] = "done"
                entry["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                entry["report"] = report
        except Exception as e:
            with _ASYNC_REPORT_LOCK:
                entry = ASYNC_REPORT_STORE.get(report_id)
                if entry is None:
                    return
                entry["status"] = "error"
                entry["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                entry["error"] = f"{type(e).__name__}: {str(e)[:300]}"

    _REPORT_EXECUTOR.submit(_runner)
    return report_id


def _get_async_report_status(report_id: str) -> dict | None:
    """给 HTTP 接口用：根据 report_id 查询异步报告状态 + 结果。找不到返回 None

    D1 修复：读取时：
      ① 更新 last_access_ts（读就续命，但不延长「绝对创建时间 TTL」——避免无限续命脏数据）
      ② 检查是否超过 ASYNC_REPORT_TTL_SECONDS：是 → 删除并返回 None（视为 404 过期）
      ③ 顺手再扫 10% 条目触发懒清理
    """
    if not report_id:
        return None
    ttl = ASYNC_REPORT_TTL_SECONDS  # 允许 0/小值（供测试 / 低 TTL 场景）
    now = time.time()
    with _ASYNC_REPORT_LOCK:
        # 懒清理（10% 最旧）
        try:
            _async_report_ttl_sweep_locked(0.1)
        except Exception:
            pass
        entry = ASYNC_REPORT_STORE.get(report_id)
        if entry is None:
            return None
        # 绝对过期：从「创建时间」算起（不管后续读不读，保证不会永久占内存）
        created_ts = entry.get("created_ts", 0)
        if now - created_ts >= ttl:
            ASYNC_REPORT_STORE.pop(report_id, None)
            return None
        # 命中则刷新「最后访问时间」元数据（仅记录，不影响绝对过期）
        entry["last_access_ts"] = now
        return dict(entry)  # 复制一份避免外部修改内部状态



# ------------------------------------------------------------
# 8. Flask HTTP 服务（供 P5 前端调用）
# ------------------------------------------------------------
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": CORS_ORIGINS}})


@app.route("/api/health", methods=["GET"])
def health():
    """健康检查：P5 前端可以先调这个判断 P4 活不活着 + LLM 是否可用
    ⚠️ 生产安全：返回 has_key/后端状态，**绝不泄露任何 key 片段**
    """
    try:
        p3_resp = requests.get(f"{ANALYSIS_API}/health", timeout=3)
        p3_status = "connected" if p3_resp.status_code == 200 else "error"
    except Exception:
        p3_status = "disconnected"

    llm_info = {
        "enabled": LLM_ENABLED,
        "provider": "SiliconFlow（OpenAI 兼容）" if LLM_ENABLED else "disabled（未设置 LLM_API_KEY，使用模板兜底）",
        "model": LLM_MODEL_ID,
        "model_small": LLM_MODEL_ID_SMALL if LLM_SMALL_ENABLED else "",
        "base_url": LLM_BASE_URL,
        "has_key": bool(LLM_API_KEY),  # 只给布尔，不给任何字符
    }

    return jsonify({
        "code": 0,
        "message": "success",
        "data": {
            "p4": "ok",
            "p3": p3_status,
            "p3_endpoint": ANALYSIS_API,
            "llm": llm_info,
            "conversation": {
                **MEMORY.stats(),
                "backend": SESSION_BACKEND,  # 告诉前端当前用 memory 还是 redis
            },
            "intent_cache": INTENT_CACHE.stats(),
            "cors_origins_count": len(CORS_ORIGINS),
            "flask_debug": FLASK_DEBUG,
            "dotenv": {
                "loaded_from": _DOTENV_LOADED_FROM,  # None 表示没从文件加载
                "hint": _DOTENV_HINT,  # 有值时表示 python-dotenv 未安装或加载失败
            },
        },
        "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    """P5 前端主入口（支持多轮对话）：
    请求 JSON: {
        "question": "...",
        "with_report": false,
        "conversation_id": "可选，传入后启用多轮对话",
        "use_llm_intent": true   // 可选，false 则强制用规则引擎解析意图
    }
    返回 JSON: { question, intent, answer, chart, meta, [report],
                 conversation_id, conversation_turn }
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}
    question = (body.get("question") or "").strip()
    # with_report 严格化（D2 修复）：
    #   - 字符串：仅接受 "async"（异步生成）/ "true"（同步）/ "false"（不生成）
    #     其他任何字符串（包括 "yes"、"1"、"0" 等）一律返回 400 错误，避免模糊真值触发同步报告
    #   - 数字/布尔：bool(_wr) 强转（0=False，非0=True，True/False 保持）
    #   - None / 缺省：False
    _wr_raw = body.get("with_report", False)
    if _wr_raw is None:
        _wr_raw = False

    _invalid = False
    if isinstance(_wr_raw, str):
        _w = _wr_raw.strip().lower()
        if _w in ("async",):
            with_report: bool | str = "async"
        elif _w in ("true", "1", "yes", "on"):
            # 同步：明确的布尔真字符串 → 转 True
            with_report = True
        elif _w in ("false", "0", "no", "off", "", "none", "null"):
            # 不生成：明确的布尔假字符串 → 转 False
            with_report = False
        else:
            # 其他字符串一律非法："sometimes" "wait" "pending" "2" 等
            _invalid = True
    else:
        with_report = bool(_wr_raw)

    if _invalid:
        return jsonify({
            "code": 400,
            "message": (
                "with_report 参数非法：仅接受 true/false/async（字符串大小写不敏感），"
                f"实际收到 with_report={_wr_raw!r}。"
                "如需异步生成报告，请传 \"async\"；同步生成传 true；不生成传 false 或省略。"
            ),
            "question": "",
            "answer": None,
            "chart": None,
            "report": None,
            "meta": {},
        }), 200

    conversation_id = (body.get("conversation_id") or "").strip() or None
    use_llm_intent = body.get("use_llm_intent", True)  # 默认用 LLM 意图解析

    if not question:
        return jsonify({
            "code": 400,
            "message": "请输入问题（question 字段不能为空）",
            "question": "",
            "answer": "⚠️ 请先输入您的问题哦~",
            "chart": None,
            "report": None,
            "meta": {},
        }), 200

    # 编码自检：如果 question 全是 ASCII 问号/数字/标点（没中文也没英文单词），
    # 极可能是 PowerShell 5.1 把中文 ConvertTo-Json 编码成了 "???"
    # —— 用户以为是后端坏了，其实是请求体里的中文已丢失。
    import re as _re_enc
    has_cjk = bool(_re_enc.search(r"[\u4e00-\u9fff]", question))
    has_english_word = bool(_re_enc.search(r"[A-Za-z]{3,}", question))
    looks_like_lost_encoding = (
        not has_cjk
        and not has_english_word
        and "?" in question
        and len(question.replace("?", "").strip()) < 5
    )
    if looks_like_lost_encoding:
        return jsonify({
            "code": 400,
            "message": (
                "question 字段疑似编码丢失（收到全是 '?' 的字符串，没有中文字符）。"
                "通常是 PowerShell 5.1 的 ConvertTo-Json 把中文转成了 '?'。"
                "请改用以下任一方式：(1) PowerShell 7+；(2) 调用前执行 "
                "[Console]::InputEncoding=[Console]::OutputEncoding=[Text.Encoding]::UTF8；"
                "(3) 用 curl -d 直接发 UTF-8 body；(4) 用 Postman 测试。"
            ),
            "question": question,
            "answer": (
                "⚠️ 收到的问题已变成一堆 '?'，中文在传输过程中丢失了。\n"
                "这是 PowerShell 5.1 编码问题，不是 P4 后端 Bug。\n\n"
                "推荐改用以下任一测试方式：\n"
                "1) 升级到 PowerShell 7\n"
                "2) 在 PowerShell 5.1 里先跑：\n"
                "   [Console]::InputEncoding = [Text.Encoding]::UTF8\n"
                "   [Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
                "   $OutputEncoding = [Text.Encoding]::UTF8\n"
                "3) 用 curl：\n"
                '   curl -X POST http://127.0.0.1:5001/api/chat -H "Content-Type: application/json" -d "{\\"question\\":\\"不同支付方式的费用占比如何？\\"}"'
            ),
            "chart": None,
            "report": None,
            "meta": {},
        }), 200

    t0 = time.time()
    try:
        result = handle_question(
            question,
            with_report=with_report,
            conversation_id=conversation_id,
            use_llm_intent=use_llm_intent,
        )
        result["code"] = 0
        result["message"] = "success"
        result["meta"] = dict(result.get("meta", {}))
        result["meta"]["p4_total_ms"] = int((time.time() - t0) * 1000)
        return jsonify(result), 200
    except requests.exceptions.RequestException as e:
        # P3 连不上，单独提示
        return jsonify({
            "code": 502,
            "message": f"分析服务（P3）连接失败：{str(e)}，请确认 P3 是否已启动在 {ANALYSIS_API}",
            "question": question,
            "answer": (
                f"⚠️ 后端分析服务暂时连不上（{ANALYSIS_API}）。\n"
                "请先检查 P3 服务是否已启动（端口 5000）。"
            ),
            "chart": None,
            "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
        }), 200
    except Exception as e:
        # 其他异常兜底，不让前端崩
        return jsonify({
            "code": 500,
            "message": f"分析失败：{type(e).__name__}: {str(e)}",
            "question": question,
            "answer": "⚠️ 抱歉，分析过程中出现异常，请检查日志或换个问题再试。",
            "chart": None,
            "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
        }), 200


@app.route("/api/conversations", methods=["GET"])
def list_conversations():
    """列出所有会话（按最后更新时间倒序），供前端左侧"会话列表"使用。
    请求: GET /api/conversations?limit=50
    返回:
      {
        "code": 0,
        "data": {
          "conversations": [
            {
              "conversation_id": "xxx",
              "last_updated": 1786929464,    # Unix 秒
              "turn_count": 3,
              "last_question": "不同支付方式的费用占比？",  # 最后一个问题（预览）
              "last_metric": "payment_mix"               # 最后一个问题指标（前端图标）
            }
          ],
          "total": 1,
          "backend": "memory"   # 告诉前端当前用 memory 还是 redis
        }
      }
    """
    try:
        limit = int(request.args.get("limit", "50"))
        limit = max(1, min(limit, 500))
    except (ValueError, TypeError):
        limit = 50
    conversations = MEMORY.list_conversations(limit=limit)
    return jsonify({
        "code": 0,
        "message": "success",
        "data": {
            "conversations": conversations,
            "total": len(conversations),
            "backend": SESSION_BACKEND,
        },
        "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
    }), 200


@app.route("/api/conversation/history", methods=["GET"])
def get_conversation_history():
    """查询某个会话的历史记录（调试/前端展示用）。
    请求: GET /api/conversation/history?conversation_id=xxx
    返回的 history 列表每项包含: question / intent / answer / chart / ts
    （answer 和 chart 是该轮当时系统生成的图文，可直接用于历史详情回看）
    """
    conversation_id = request.args.get("conversation_id", "").strip()
    if not conversation_id:
        return jsonify({"code": 400, "message": "conversation_id 不能为空"}), 200
    history = MEMORY.get_history(conversation_id)
    return jsonify({
        "code": 0,
        "message": "success",
        "conversation_id": conversation_id,
        "turns": len(history),
        "history": history,
    }), 200


@app.route("/api/conversation/clear", methods=["POST"])
def clear_conversation():
    """清空某个会话的历史记录。
    请求: POST /api/conversation/clear  body: {"conversation_id": "xxx"}
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}
    conversation_id = (body.get("conversation_id") or "").strip()
    if not conversation_id:
        return jsonify({"code": 400, "message": "conversation_id 不能为空"}), 200
    MEMORY.clear(conversation_id)
    return jsonify({
        "code": 0,
        "message": "success",
        "conversation_id": conversation_id,
        "cleared": True,
    }), 200


@app.route("/api/report", methods=["POST"])
def chat_with_report():
    """便捷接口：等价于 /api/chat + with_report=true"""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}
    body["with_report"] = True
    return chat()


@app.route("/api/report/status", methods=["GET"])
def get_async_report_status():
    """查询异步生成的医疗洞察报告状态。
    请求：GET /api/report/status?report_id=rp_xxx
    返回：
      - 找不到 → 404
      - pending → {"status":"pending"}
      - done    → {"status":"done", "report": {...}}
      - error   → {"status":"error", "error": "..."}
    """
    report_id = (request.args.get("report_id") or "").strip()
    if not report_id:
        return jsonify({"code": 400, "message": "report_id 不能为空"}), 200
    entry = _get_async_report_status(report_id)
    if entry is None:
        return jsonify({"code": 404, "message": f"report_id={report_id} 不存在（或已过期）"}), 200
    payload = {"code": 0, "message": "success", "report_id": report_id}
    payload.update(entry)  # status / report / error / created_at 等
    return jsonify(payload), 200


if __name__ == "__main__":
    # 默认启动 Flask HTTP 服务（端口 5001），让 P5 前端能调用
    # 也可以先本地自测： python agent.py --selftest
    import sys
    # 启动前先打印 dotenv 状态（方便排查 "我 .env 写了为什么没生效"）
    if _DOTENV_HINT:
        print(_DOTENV_HINT)
    if _DOTENV_LOADED_FROM:
        print(f"[dotenv] ✅ 配置已从文件加载：{_DOTENV_LOADED_FROM}")
    elif not _DOTENV_HINT:
        print(f"[dotenv] ℹ️ 未找到 .env 文件，全部配置从系统环境变量读取")
    if "--selftest" in sys.argv:
        # 综合离线自测：路由表 + 图表 + 摘要 + 报告 4 套测试一起跑
        # 用样例数据，不依赖 LLM/P3，适合 CI 和本地健康检查
        import subprocess as _sp
        print("=" * 70)
        print("[本地自测] 综合离线测试套件（不依赖 LLM/P3）")
        print(f"  INTENT_CACHE_VERSION = {INTENT_CACHE_VERSION!r}（旧缓存将自动失效）")
        print(f"  LLM_ENABLED = {LLM_ENABLED}")
        print("=" * 70)
        _test_files = [
            "test_route_table.py",      # 19 例：13 chart_hint 路由 + 2 多轮 + 3 反例
            "test_chart_builders.py",   # 13 例：13 种 chart_hint 的 ECharts option 构造
            "test_summary_builders.py", # 13 例：13 种 chart_hint 的中文摘要
            "test_report_builders.py",  # 15 例：13 种 chart_hint + 2 旧用例的报告 section
        ]
        _all_passed = True
        for _t in _test_files:
            print(f"\n>>> 运行 {_t}")
            print("-" * 70)
            try:
                _r = _sp.run(
                    [sys.executable, _t],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                if _r.returncode != 0:
                    _all_passed = False
                    print(f"  ❌ {_t} 退出码 {_r.returncode}")
                else:
                    print(f"  ✅ {_t} 通过")
            except FileNotFoundError:
                print(f"  ⚠️  {_t} 不存在，跳过")
            except Exception as _e:
                _all_passed = False
                print(f"  ❌ {_t} 执行异常：{type(_e).__name__}: {_e}")
        print("\n" + "=" * 70)
        if _all_passed:
            print(f"[自测] ✅ 全部 {len(_test_files)} 套测试通过")
            print(f"[自测] ✅ INTENT_CACHE_VERSION={INTENT_CACHE_VERSION!r} 已就绪，旧缓存会自动失效")
        else:
            print(f"[自测] ❌ 有失败用例，请查看上方输出")
            sys.exit(1)
    elif "--selftest-e2e" in sys.argv:
        # 端到端自测：走真实 LLM + P3，需要服务可用
        q = "2021年哪类疾病的平均住院时长最长？前5名"
        print("=" * 60)
        print(f"[端到端自测] 问题：{q}")
        print(f"  LLM_ENABLED = {LLM_ENABLED}  LLM_MODEL_ID = {LLM_MODEL_ID}")
        print(f"  ANALYSIS_API = {ANALYSIS_API}")
        print("=" * 60)
        result = handle_question(q, with_report=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        port = int(os.getenv("P4_PORT", "5001"))
        print(f"🚀 P4 AI 交互服务启动中...")
        print(f"   监听地址：http://127.0.0.1:{port}")
        print(f"   主入口接口：POST http://127.0.0.1:{port}/api/chat")
        print(f"   健康检查：GET  http://127.0.0.1:{port}/api/health")
        print(f"   会话列表：GET  http://127.0.0.1:{port}/api/conversations")
        print(f"   历史详情：GET  http://127.0.0.1:{port}/api/conversation/history?conversation_id=xxx")
        print(f"   依赖 P3 服务：{ANALYSIS_API}")
        print(f"   本地自测命令：python agent.py --selftest（离线）/ --selftest-e2e（端到端）")
        print(f"   CORS 白名单：{CORS_ORIGINS}")
        print(f"   会话存储：{SESSION_BACKEND}")
        print(f"   意图缓存版本：{INTENT_CACHE_VERSION}（升级路由表后旧缓存自动失效）")
        llm_status = "✅ 已启用" if LLM_ENABLED else "❌ 未启用（请检查 LLM_API_KEY 环境变量）"
        print(f"   LLM 状态：{llm_status}")
        if LLM_ENABLED:
            print(f"   LLM 模型：{LLM_MODEL_ID}")
            if LLM_MODEL_ID_SMALL:
                print(f"   LLM 小模型：{LLM_MODEL_ID_SMALL}")
            print(f"   LLM Base URL：{LLM_BASE_URL}")
        if _DOTENV_LOADED_FROM:
            print(f"   .env 文件：{_DOTENV_LOADED_FROM}")
        else:
            print(f"   .env 文件：未使用（所有配置来自环境变量）")
        app.run(host="0.0.0.0", port=port, debug=FLASK_DEBUG)
