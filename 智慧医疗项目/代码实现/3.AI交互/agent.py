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
import hashlib
import json
import logging
import os
import queue
import threading
import time
import uuid

# ------------------------------------------------------------
# 0.0 日志系统配置（生产可分级控制，避免 print 散落难统一收集）
#    级别策略：
#      - DEBUG  : 开发调试（缓存命中、数据长度等）
#      - INFO   : 正常运行（启动横幅、LLM 来源、降级提示）
#      - WARNING: 容错降级（LLM 失败回退模板、Redis 不可用降级 memory）
#      - ERROR  : 真正异常（P3 路由异常、JSON 解析失败、构造器异常）
#    通过环境变量 LOG_LEVEL=DEBUG/INFO/WARNING/ERROR 控制（默认 INFO）
# ------------------------------------------------------------
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("p4.agent")

# ------------------------------------------------------------
# 0.1 运行时可观测性基础设施（可观测日志 + 指标聚合）
#     纯标准库实现，零额外依赖；多线程安全（全局锁）。
#     - _RUNTIME_STATS：累计计数器 / 耗时，供 /api/health 暴露
#     - _log_event：结构化单行 JSON 日志（便于 grep / 日志采集）
#     埋点覆盖：请求路径（Agent/旧管道）、意图来源、P3 调用/错误/耗时、
#               摘要生成/LLM 调用/耗时、Agent 降级原因。
# ------------------------------------------------------------
_RUNTIME_LOCK = threading.Lock()
_RUNTIME_STATS = {
    "requests_total": 0,          # 进入 handle_question 的总请求数
    "agent_path_total": 0,        # 走 LangChain Agent 路径的请求数
    "legacy_path_total": 0,       # 走旧 pipeline 的请求数（含 Agent 降级）
    "agent_fallback_total": 0,    # Agent 返回 None 降级到旧管道的次数
    "agent_fallback_reasons": {}, # 降级原因 -> 计数
    "intent_sources": {},         # 意图来源(llm/rules/rules_fallback/langchain_agent/out_of_scope) -> 计数
    "out_of_scope_total": 0,      # Agent 判定非数据分析问题（未调用任何工具）的次数
    "agent_no_tool_total": 0,     # Agent 未调用任何工具的次数（与 out_of_scope_total 同源）
    "p3_calls_total": 0,          # P3 接口调用总次数（两条路径合计）
    "p3_error_total": 0,          # P3 调用失败次数（按 kind 细分）
    "p3_errors_by_kind": {},      # 错误类型(timeout/connection_failed/invalid_response/p3_error) -> 计数
    "p3_latency_ms_total": 0,     # P3 调用累计耗时（ms）
    "summary_calls_total": 0,     # 摘要生成总次数
    "summary_llm_calls": 0,       # 摘要中实际调用 LLM 的次数
    "summary_errors": 0,          # 摘要生成异常次数（兜底前）
    "summary_cache_hits": 0,      # 摘要缓存命中次数（省掉的 LLM 调用数）
    "summary_latency_ms_total": 0,# 摘要生成累计耗时（ms）
    "langchain_version": None,    # Agent 创建后写入（v02/v1x）
    "start_ts": int(time.time()), # 进程启动时刻（用于 uptime）
}


def _obs_inc(key: str, amount: int = 1) -> None:
    """累加计数器（线程安全）。"""
    with _RUNTIME_LOCK:
        _RUNTIME_STATS[key] = _RUNTIME_STATS.get(key, 0) + amount


def _obs_nested_inc(key: str, subkey, amount: int = 1) -> None:
    """累加嵌套字典中的子计数器（线程安全），如 agent_fallback_reasons[reason]。"""
    with _RUNTIME_LOCK:
        bucket = _RUNTIME_STATS.setdefault(key, {})
        bucket[subkey] = bucket.get(subkey, 0) + amount


def _obs_latency(key: str, ms: float) -> None:
    """累加耗时（ms，线程安全）。"""
    with _RUNTIME_LOCK:
        _RUNTIME_STATS[key] = _RUNTIME_STATS.get(key, 0) + ms


def _log_event(event: str, **fields) -> None:
    """结构化可观测日志：单行 JSON，便于 grep / 日志采集系统解析。

    event 为事件名（request_received / path_decided / agent_invoked /
    p3_result / summary_built / request_done / agent_fallback），
    fields 为任意结构化字段。
    """
    payload = {"event": event, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    payload.update(fields)
    logger.info("[OBS] %s", json.dumps(payload, ensure_ascii=False, default=str))


def _get_runtime_stats() -> dict:
    """返回运行态统计的快照（含派生指标），供 /api/health 使用。"""
    with _RUNTIME_LOCK:
        s = dict(_RUNTIME_STATS)
        s["agent_fallback_reasons"] = dict(s.get("agent_fallback_reasons", {}))
        s["intent_sources"] = dict(s.get("intent_sources", {}))
        s["p3_errors_by_kind"] = dict(s.get("p3_errors_by_kind", {}))
    req = s.get("requests_total", 0) or 0
    p3 = s.get("p3_calls_total", 0) or 0
    summ = s.get("summary_calls_total", 0) or 0
    s["agent_hit_rate"] = round(s.get("agent_path_total", 0) / req, 4) if req else 0.0
    s["p3_error_rate"] = round(s.get("p3_error_total", 0) / p3, 4) if p3 else 0.0
    s["avg_p3_latency_ms"] = round(s.get("p3_latency_ms_total", 0) / p3, 1) if p3 else 0.0
    s["avg_summary_latency_ms"] = round(s.get("summary_latency_ms_total", 0) / summ, 1) if summ else 0.0
    s["uptime_seconds"] = int(time.time()) - s.get("start_ts", int(time.time()))
    return s

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
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from typing import Literal
from pydantic import BaseModel, Field

# LangChain 可选导入（未安装时自动降级到旧 parse_intent + call_analysis_api pipeline）
# 兼容 langchain 0.2.x (create_tool_calling_agent) 和 1.x (create_agent) 两个 API 版本
try:
    from langchain_core.tools import StructuredTool
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    # 优先尝试 0.2.x API
    try:
        from langchain.agents import create_tool_calling_agent, AgentExecutor
        _LC_AGENT_API = "v02"  # langchain 0.2.x: create_tool_calling_agent + AgentExecutor
    except ImportError:
        # 回退到 1.x API
        try:
            from langchain.agents import create_agent as _lc_create_agent
            _LC_AGENT_API = "v1x"  # langchain 1.x: create_agent (returns CompiledStateGraph)
        except ImportError:
            _LC_AGENT_API = None

    _LANGCHAIN_AVAILABLE = _LC_AGENT_API is not None
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    _LC_AGENT_API = None

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
# 多轮对话保留轮数（环境变量可配；Redis 后端用 LTRIM 几乎零成本，可调大；memory 后端看内存预算）
# 默认 20：覆盖大多数长对话场景；5 太短，用户问到第 6 轮就丢失第 1 轮上下文
MAX_HISTORY_TURNS = max(1, int(os.getenv("MAX_HISTORY_TURNS", "20")))

# —— 模型分档配置（简单任务用小模型省时间 + 省钱，复杂任务用大模型保质量）——
# 默认统一走大模型，如果设置了 LLM_MODEL_ID_SMALL，意图解析等简单任务会用它
LLM_MODEL_ID_SMALL = os.getenv("LLM_MODEL_ID_SMALL", "")  # 例如：Qwen/Qwen2.5-7B-Instruct

LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "Qwen/Qwen2.5-72B-Instruct")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# —— Agent（工具调用）专用模型 ——
# 可单独指定一个 function-calling 更稳的模型，不影响摘要等其它 LLM 调用。
# 默认与 LLM_MODEL_ID 一致。硅基流动上 function-calling 较稳的候选（按需切换，注意各自配额/价格）：
#   - Qwen/Qwen2.5-72B-Instruct  （默认，已支持 tools）
#   - deepseek-ai/DeepSeek-V3
#   - Pro/Qwen/Qwen2.5-72B-Instruct  （Pro 版更稳定，需 Pro 额度）
LLM_MODEL_ID_AGENT = os.getenv("LLM_MODEL_ID_AGENT", LLM_MODEL_ID)
# 工具调用提取失败时的重试次数（每次重新让 Agent 走一遍工具选择），
# 用于应对模型偶发返回空工具调用/乱码。默认 1（即最多 2 次尝试）。
AGENT_TOOL_RETRIES = max(0, int(os.getenv("AGENT_TOOL_RETRIES", "1")))

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
    """给 LLM 构造标准 ChatML 消息列表（system + user），让输出更可控。

    优化 2：让 LLM 在同一次调用里同时产出「文本摘要」和「图表标题建议」，
    避免下游 generate_chart_config 再调一次 LLM。
    输出格式从纯文本改为严格 JSON：{"summary": "...", "chart_suggestion": {...}}
    """
    system_prompt = (
        "你是智慧医疗大数据分析平台的「医疗数据解读专家」。\n"
        "你的任务：基于结构化的住院患者数据分析结果，输出严格 JSON，"
        "同时包含「中文摘要」和「图表标题建议」两部分，给医院管理者/医保人员/临床科室看。\n"
        "\n"
        "写作原则（只有第 1 条是硬约束，其余请自由发挥）：\n"
        "1. 【硬约束】数据必须严格忠于输入，禁止编造或修改任何数字；"
        "禁止重复字符/乱码；禁止使用 markdown 反斜杠转义，只用普通中文标点。\n"
        "2. 开头直接切入主题，不要「好的我来分析」之类的套话。\n"
        "3. 语言要自然、有辨识度：像一位资深医疗数据分析师在向科室主任口头汇报，"
        "句式应随数据内容而变化，避免千篇一律的模板腔（例如总是「结果显示…位居榜首…建议…」）；"
        "尤其不要每次都用「数据显示」「从数据来看」「分析结果显示」这类固定开头，"
        "尽量直接从最有信息量的事实切入。\n"
        "4. 突出数据里真正值得说的点：关键对比、异常值、占比或趋势，不必面面俱到地罗列 Top1/2/3。\n"
        "5. 若数据中有值得注意的业务洞察（如某病种占比异常高、费用或住院时间明显偏离），"
        "可以点出来；不要为了凑「建议」而硬编一条。\n"
        "6. 篇幅适中（80-250 字），自然成段；emoji 最多 2 个，克制使用。\n"
        "7. 数据中若出现英文维度取值（如性别 F/M、支付方式 Medicare、严重程度 Minor、\n"
        "   疾病名、出院去向等），在摘要正文中一律使用中文表达（如「女」「联邦医疗保险」\n"
        "   「轻度」「活产儿」），不要原样保留英文缩写或代码。\n"
        "\n"
        "输出格式（严格 JSON，不要 markdown 代码块，不要任何额外文字）：\n"
        "{\n"
        "  \"summary\": \"中文摘要正文\",\n"
        "  \"chart_suggestion\": {\n"
        "    \"title\": \"图表标题（10字以内，具体而非泛化，如『Top 诊断排行』而非『分析结果』）\",\n"
        "    \"subtitle\": \"15字内副标题（可选，没灵感给空字符串）\"\n"
        "  }\n"
        "}\n"
        "\n"
        "注意：chart_suggestion 只需要给标题和副标题，不要给 chart_type（图表类型由系统规则决定）。\n"
        "如果数据样例不适合给标题建议（如 KPI 大屏），chart_suggestion 可以给空对象 {}。"
    )

    # 只取 Top 10 让 LLM 不乱花 token（足够写摘要了）
    compact_data = []
    for item in data[:10]:
        compact = {}
        for k, v in item.items():
            if v is not None:
                compact[k] = v
        compact_data.append(compact)

    # 优化 5：把 P3 meta 里的更多字段塞进 prompt，让 LLM 有更多上下文
    # 不同 chart_hint 的 meta 字段差异较大，统一用 .get 容错
    null_excluded = meta.get("null_excluded", 0) or 0
    filters = meta.get("filters") or intent.get("filters") or {}
    levels = meta.get("levels") or ""
    chart_hint = intent.get("chart_hint") or ""
    dim_code = meta.get("dimension") or intent.get("dimension") or ""

    # filters dict → 友好文本（key: value 列表）
    filters_text = "无"
    if filters:
        parts = []
        for k, v in filters.items():
            parts.append(f"{k}={v}")
        filters_text = ", ".join(parts) if parts else "无"

    meta_extra_lines = []
    if null_excluded:
        meta_extra_lines.append(f"- null_excluded（排除空值条数）：{null_excluded:,}")
    if levels:
        meta_extra_lines.append(f"- levels（桑基图层级）：{levels}")
    if chart_hint:
        meta_extra_lines.append(f"- chart_hint（图表类型提示）：{chart_hint}")
    if dim_code and dim_code != intent.get("dimension"):
        meta_extra_lines.append(f"- P3 实际查询维度代码：{dim_code}")
    meta_extra = "\n".join(meta_extra_lines) if meta_extra_lines else ""

    user_prompt = (
        f"【用户原始问题】\n{question}\n\n"
        f"【系统解析出的查询维度】\n"
        f"- 维度：{dim_zh}（代码: {intent.get('dimension')}）\n"
        f"- 指标：{metric_zh}（代码: {meta.get('metric')}）\n"
        f"- 过滤条件：{filters_text}\n"
        f"- 返回 Top N：{intent.get('top', '默认')}\n"
        f"- 参与计算的总记录数：{total:,} 条\n"
        f"- P3 后端查询耗时：{meta.get('query_ms', 0)} ms\n"
        f"{meta_extra}\n\n"
        f"【P3 返回的结构化结果（Top {len(compact_data)}）】\n"
        f"{json.dumps(compact_data, ensure_ascii=False, indent=2)}\n\n"
        "请按系统要求，输出一段流畅的中文解读摘要。"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_llm_messages_for_kpi(question: str, intent: dict, kpi: dict,
                                meta: dict) -> list[dict]:
    """为 payment_summary（KPI 大屏，data 是单个 dict）构造 LLM 消息。

    KPI 数据结构是扁平的 dict（total_records / total_charges / avg_charges /
    avg_costs / avg_los / self_pay_count / self_pay_pct / top_payment / ed_count /
    severity_distribution），不能套用 list 模板，需要专门提示。
    """
    system_prompt = (
        "你是智慧医疗大数据分析平台的「医疗数据解读专家」。\n"
        "你的任务：基于一份 KPI 总览数据（关键指标卡片），输出一段通俗、专业、"
        "业务友好的中文摘要，给医院管理者/医保人员看。\n"
        "\n"
        "⚠️ 严格写作要求：\n"
        "1. 数据必须严格忠于输入，禁止编造或修改任何数字。\n"
        "2. 禁止重复字符（如「22年年年」），每个字只写一遍。\n"
        "3. 禁止使用 markdown 转义符 \\; 或反斜杠。\n"
        "4. 开头直接点题，不要说「好的我来分析」这类废话。\n"
        "5. 突出核心 KPI：总记录数、总费用、次均费用、次均成本、平均住院天数、"
        "自付占比、主要支付方式、严重程度分布。\n"
        "6. 指出值得关注的信号（如自付占比偏高/偏低、次均费用与成本的差值、"
        "严重程度集中度），并给出 1-2 条业务观察或建议。\n"
        "7. 最多使用 2 个 emoji（📊 💡 🏥），不要滥用。\n"
        "8. 控制在 150-300 字之间，分 2-3 段。\n"
    )
    # 把 KPI dict 完整给 LLM（字段不多，token 够用）
    user_prompt = (
        f"【用户原始问题】\n{question}\n\n"
        f"【系统解析出的查询维度】\n"
        f"- chart_hint：payment_summary（KPI 总览大屏）\n"
        f"- 参与计算的总记录数：{kpi.get('total_records', 0):,} 条\n"
        f"- P3 后端查询耗时：{meta.get('query_ms', 0)} ms\n"
        f"- null_excluded（排除空值条数）：{meta.get('null_excluded', 0)}\n"
        f"- filters（筛选条件）：{meta.get('filters') or '无'}\n\n"
        f"【P3 返回的 KPI 数据（完整）】\n"
        f"{json.dumps(kpi, ensure_ascii=False, indent=2)}\n\n"
        "请按系统要求，输出一段流畅的中文解读摘要，覆盖以上 KPI 要点。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_multiturn_context(history: list[dict]) -> str:
    """构建多轮对话上下文片段，附加到 LLM user prompt 末尾。

    优化 6：不再只传「上一轮问题」，而是同时传「上一轮答案摘要（前 200 字）」，
    让 LLM 知道上一轮已经说过什么，避免重复，并能做承接式开头。
    """
    if not history:
        return ""
    lines = []
    # 取最近 2 轮，每轮包含：问题 + 答案摘要
    for i, t in enumerate(history[-2:], 1):
        q = t.get("question", "")
        a = (t.get("answer") or "").strip()
        # 答案截取前 200 字（避免 token 爆炸 + 也避免把图表 JSON 当答案）
        a_brief = a[:200] + ("…" if len(a) > 200 else "") if a else "（无文字摘要）"
        lines.append(f"第{i}轮问题: 「{q}」\n第{i}轮回答摘要: 「{a_brief}」")
    history_context = "\n".join(lines)
    return (
        f"\n\n【多轮对话上下文】\n{history_context}\n\n"
        "⚠️ 回答要求：当前问题可能是对上轮的追问，请：\n"
        "1) 用承接式开头（如「继续看费用数据：……」「改为按年龄段来看：……」）\n"
        "2) 不要重复上一轮已经说过的背景介绍和数字，直接说本轮新增的核心结论\n"
        "3) 如果维度或指标换了，直接点出来\n"
        "4) 如果当前问题与上轮无关（完全新话题），可以忽略上下文"
    )


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


# 流式 token 合并阈值：累积 >= 该字符数才回调一次（SiliconFlow 常逐字符返回）
_STREAM_FLUSH_CHARS = int(os.getenv("STREAM_FLUSH_CHARS", "8"))


def _call_llm_stream(messages: list[dict], on_token, use_small_model: bool = False) -> tuple[bool, str]:
    """流式调用 LLM（SSE 真流式用）：每个增量 token 通过 on_token(piece) 回调逐段输出，
    同时累积完整文本。返回 (True, 完整文本) / (False, 失败原因)，失败不抛异常。

    与 _call_llm_safely 保持同一套容错（超时/网络/乱码检测），仅传输方式为 stream=True。
    on_token 回调异常不影响主流程（前端断连时静默忽略）。
    小 token 按 _STREAM_FLUSH_CHARS 阈值合并后再回调（SiliconFlow 常逐字符返回，
    直接透传会产生上百个 SSE 事件，合并后更平滑）。
    """
    if not LLM_ENABLED:
        return False, "LLM 未启用（未设置 LLM_API_KEY 环境变量）"
    use_small = bool(use_small_model and LLM_SMALL_ENABLED)
    model_id = LLM_MODEL_ID_SMALL if use_small else LLM_MODEL_ID
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
            "stream": True,
        }
        content = ""
        pending = []          # 待合并的小 token 缓冲
        pending_len = 0

        def _flush_pending():
            """把缓冲的小 token 合并成一段回调（SSE 事件数收敛）。"""
            nonlocal pending, pending_len
            if not pending:
                return
            try:
                on_token("".join(pending))
            except Exception:
                pass  # 回调异常（前端断连等）不影响主流程
            pending = []
            pending_len = 0

        with requests.post(url, headers=headers, json=body,
                           timeout=LLM_TIMEOUT, stream=True) as resp:
            if resp.status_code != 200:
                return False, f"LLM HTTP {resp.status_code}: {resp.text[:300]}"
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload_str = line[5:].strip()
                if payload_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}) or {}
                piece = delta.get("content") or ""
                if piece:
                    content += piece
                    pending.append(piece)
                    pending_len += len(piece)
                    if pending_len >= _STREAM_FLUSH_CHARS:
                        _flush_pending()
        _flush_pending()  # 流结束前 flush 剩余 token
        content = content.strip()
        if not content:
            return False, "LLM 流式返回空 content"
        # 乱码检测：与 _call_llm_safely 一致，垃圾输出降级到模板
        if _detect_llm_garbage(content):
            return False, (f"LLM 输出质量不合格（检测到重复字符或乱码），自动降级到模板。"
                           f"前80字预览：{content[:80]}")
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
    # —— 费用成本分析（新接口 /cost/*）——
    "费用成本差": "profit_difference", "成本差": "profit_difference",
    "收支差额": "profit_difference", "费用减成本": "profit_difference",
    "利润率": "profit_margin", "利润": "profit_margin", "收费成本比": "profit_margin",
    "成本效益": "efficiency_ranking", "效益排行": "efficiency_ranking", "效益排名": "efficiency_ranking",
    "费用构成": "composition", "费用占比": "composition", "费用组成": "composition",
    "费用趋势": "cost_trend", "年度费用": "cost_trend", "费用走势": "cost_trend", "历年费用": "cost_trend",
    # —— 医疗质量监测（模块四 /api/v1/quality/*）——
    "医疗质量": "quality_overview", "质量总览": "quality_overview",
    "质量概览": "quality_overview", "质量指标": "quality_overview",
    "死亡率排行": "quality_mortality", "死亡率排名": "quality_mortality",
    "死亡排行": "quality_mortality", "死亡率": "quality_mortality",
    "平均住院日": "quality_los", "住院日排行": "quality_los",
    "医院质量对比": "quality_facility", "医院质量": "quality_facility",
    "质量对比": "quality_facility",
    "离院去向": "quality_disposition", "出院去向": "quality_disposition",
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
# 1.7 LLM 输出 JSON 提取公共函数（消除 4 处重复逻辑）
# ------------------------------------------------------------
def _extract_json_from_llm_output(raw: str) -> tuple[bool, object, str]:
    """从 LLM 的原始输出中提取 JSON 对象/数组，统一容错逻辑。

    处理步骤：
      1) 剥 markdown 代码块 ```...```（容错多层嵌套、带语言标签如 ```json）
      2) 尝试找最外层 { ... } 或 [ ... ] 块
      3) json.loads 解析

    返回 (成功?, 解析后的 dict/list, 失败原因或空字符串)。
    成功时 reason 为空字符串；失败时 reason 包含简短诊断信息。

    严格约束：只接受 JSON 容器类型（dict 或 list）。纯数字、字符串、布尔、null
    虽然是合法 JSON 但不是容器，会被判失败——因为调用方（意图/摘要/图表建议）
    只期望 dict 或 list，纯标量没有意义。
    """
    if not raw or not isinstance(raw, str):
        return False, None, "空输入"
    import re as _re
    cleaned = raw.strip()
    # 步骤 1：剥 markdown 代码块（最多 3 层嵌套）
    for _ in range(3):
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
            # 去掉开头的语言标签（json/python/...）
            cleaned = _re.sub(r"^[a-zA-Z]*\s*", "", cleaned, count=1)
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    # 步骤 2：尝试直接解析；失败再提取最外层 {...} 或 [...]
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, (dict, list)):
            return True, obj, ""
        # 合法 JSON 但不是容器（数字/字符串/布尔/null）→ 失败
        return False, None, f"解析成功但非容器类型：{type(obj).__name__}，期望 dict/list"
    except json.JSONDecodeError:
        pass
    # 找最外层一对 {} 或 []（用 DOTALL 让 . 匹配换行）
    # 注意：贪婪匹配会拿到最外层闭合，对于嵌套 JSON 也能正确取到完整结构
    match_obj = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
    match_arr = _re.search(r"\[.*\]", cleaned, _re.DOTALL)
    # 取更早出现的那个
    candidates = [m for m in (match_obj, match_arr) if m]
    if not candidates:
        return False, None, f"未找到 JSON 块，原文: {cleaned[:200]}"
    match = min(candidates, key=lambda m: m.start())
    try:
        obj = json.loads(match.group(0))
        if isinstance(obj, (dict, list)):
            return True, obj, ""
        return False, None, f"解析成功但非容器类型：{type(obj).__name__}，期望 dict/list"
    except json.JSONDecodeError as e:
        return False, None, f"JSON 解析失败: {e}，原文: {cleaned[:200]}"


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
    MAX_HISTORY = MAX_HISTORY_TURNS  # 从全局配置读取（环境变量 MAX_HISTORY_TURNS）
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
    MAX_HISTORY = MAX_HISTORY_TURNS  # 从全局配置读取（Redis LTRIM 零成本，可调大）
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
            logger.info("会话存储 ✅ 使用 Redis：%s，TTL=%ss", REDIS_URL, SESSION_TTL_SECONDS)
            return rm  # type: ignore[return-value]
        # Redis 连不上 → 降级，打印提示
        logger.warning("会话存储 ⚠️ Redis 配置了但不可用（%s），自动降级为 memory 后端",
                       rm._last_err or "未知原因")
        return MemoryConversationMemory(ttl_seconds=SESSION_TTL_SECONDS)
    # 默认 memory
    mm = MemoryConversationMemory(ttl_seconds=SESSION_TTL_SECONDS)
    logger.info("会话存储 使用 memory（单节点模式，重启会丢会话）。设置 SESSION_BACKEND=redis 可启用持久化存储。")
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
            last_intent = last.get("intent", {}) or {}
            dim = last_intent.get("dimension", "")
            met = last_intent.get("metric", "")
            chart_hint = last_intent.get("chart_hint") or ""
            # 修复 BUG 7：缓存键纳入所有影响查询参数的子字段，
            # 避免相同问句但子参数不同时误命中缓存（虽概率低，但后果严重——返回错误数据）
            sub = "|".join(
                f"{k}={last_intent.get(k)}" for k in
                ("by", "dim1", "dim2", "group", "levels", "level", "mode")
                if last_intent.get(k) is not None
            )
            ctx_parts.append(f"last:{q}|{dim}|{met}|hint={chart_hint}|sub={sub}")
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


# 多轮上下文增强：意图解析阶段注入给 LLM 的历史轮数（默认 ≤5，省 token 同时保留足够上下文）
MULTITURN_HISTORY_TURNS = int(os.getenv("MULTITURN_HISTORY_TURNS",
                                         str(min(5, MAX_HISTORY_TURNS))))

# Agent 工具选择注入的历史轮数：历史过长会淹没工具选择判断（实测 2 轮以上历史时
# DeepSeek-V3 对「交叉分布热力图」类问题开始 no-tool 误判 out_of_scope）。
# 多轮真正需要的上下文（filters 继承/追问补参）由规则引擎在意图重建层处理，
# 工具选择只需最近几轮即可，默认 3。
AGENT_HISTORY_TURNS = int(os.getenv("AGENT_HISTORY_TURNS", "3"))


def _format_history_for_intent(history: list[dict],
                               max_turns: int = None,
                               answer_chars: int = 200) -> str:
    """把会话历史格式化为给意图 LLM / 摘要 LLM 的多轮上下文文本。

    与旧实现相比的增强点：
      - 轮数可配置（MULTITURN_HISTORY_TURNS），不再硬编码 3 轮；
      - 额外带上上一轮的**答案摘要**（截断 answer_chars 字），使"把第 1 个疾病按
        性别拆开"这类结果引用型追问能被正确解析；
      - 轮次编号基于「最近 N 轮」连续编号，便于 LLM 定位。
    无历史时返回明确占位，避免 LLM 误判。
    """
    max_turns = max_turns or MULTITURN_HISTORY_TURNS
    if not history:
        return "（无历史，这是第一轮对话）"
    recent = history[-max_turns:]
    lines = []
    for i, turn in enumerate(recent, 1):
        q = turn.get("question", "")
        it = turn.get("intent") or {}
        ans = (turn.get("answer") or "")[:answer_chars]
        lines.append(
            f"第{i}轮 - 用户问: {q}\n"
            f"        解析: dimension={it.get('dimension')}, metric={it.get('metric')}, "
            f"filters={it.get('filters')}, top={it.get('top')}\n"
            f"        回答摘要: {ans}"
        )
    return "\n".join(lines)


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
  "reasoning": "简要说明解析思路",
  "validation": {
    "is_valid": true,
    "issues": [],
    "suggestions": [],
    "warnings": []
  }
}

⚠️ validation 字段（优化1：合并意图解析 + 校验，省一次 LLM 调用）：
  - is_valid: bool，整个意图是否合理（dimension/metric/filters/top 都说得通）
  - issues: list[str]，发现的问题（如"问占比但 top<4"、"year=2099 太远"）
  - suggestions: list[str]，改进建议（如"payment_mix 应配 payment_typology 维度"）
  - warnings: list[str]，温和提醒（如"严重程度筛选同时含儿童和老年人可能数据稀疏"）
  - 没有问题就返回空数组，is_valid=true
  - 不要重复 reasoning 的内容，validation 只关注「参数合理性」

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

    # 构造对话历史摘要给 LLM（多轮上下文增强：含上一轮答案摘要，支持结果引用型追问）
    history_text = _format_history_for_intent(history)

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

    # 解析 LLM 返回的 JSON（公共函数统一容错：剥 markdown + 提取 {...} + json.loads）
    ok_json, intent_raw, reason = _extract_json_from_llm_output(content)
    if not ok_json or not isinstance(intent_raw, dict):
        return False, {}, f"LLM 返回的不是合法 JSON: {reason}"

    # 字段校验 + 兜底
    valid_dims = {"age_group", "gender", "discharge_year", "ccsr_diagnosis",
                  "facility", "payment_typology", "severity"}
    valid_metrics = {"count", "avg_length_of_stay", "total_charges", "avg_charges",
                     "total_costs", "avg_costs", "payment_mix", "trend"}
    valid_genders = {"M", "F"}
    valid_age_groups = {"0 to 17", "18 to 29", "30 to 49", "50 to 69", "70 or Older"}
    # 新版 chart_hint 白名单 + 子参数白名单（与 P3 common.py 对齐）
    # 修复 BUG 2.1：valid_chart_hints 只用 ROUTE_TABLE keys（英文 chart_hint 名）。
    # 之前误用 set(CHART_HINT_KEYWORDS.keys()) | set(ROUTE_TABLE.keys()) 会把
    # 中文触发词（"人口金字塔"等）也当成合法 chart_hint 接受，但下游
    # `if chart_hint in ROUTE_TABLE` 查不到中文 key，会静默降级到旧接口。
    # 单一真相源是 ROUTE_TABLE（chart_hint → 端点的实际映射），不是关键词表。
    valid_chart_hints = set(ROUTE_TABLE.keys())
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

    # 优化1：从 LLM 输出里抽取 validation 字段，挂到 intent["_validation"]，
    # call_analysis_api 直接读，省掉一次独立的 _validate_intent_by_llm 调用。
    validation_raw = intent_raw.get("validation") or {}
    if not isinstance(validation_raw, dict):
        validation_raw = {}

    def _as_list(v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]

    validation = {
        "is_valid": bool(validation_raw.get("is_valid", True)),
        "issues": _as_list(validation_raw.get("issues")),
        "suggestions": _as_list(validation_raw.get("suggestions")),
        "warnings": _as_list(validation_raw.get("warnings")),
    }

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
        # 优化1：合并校验报告，避免下游再调一次 LLM
        "_validation": validation,
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
    elif hint in ("quality_mortality", "quality_los"):
        # dimension: diagnosis / facility / age_group / severity / risk_mortality
        dim = intent.get("dimension")
        if dim and dim in _QUALITY_DIM_MAP:
            intent["dimension"] = _QUALITY_DIM_MAP[dim]
        else:
            # P4 未命中合法维度 → 从问句关键词二次推断（含 risk_mortality）
            if "风险" in q:
                intent["dimension"] = "risk_mortality"
            elif "医院" in q or "机构" in q:
                intent["dimension"] = "facility"
            elif "年龄" in q:
                intent["dimension"] = "age_group"
            elif "严重" in q or "病情" in q:
                intent["dimension"] = "severity"
            else:
                intent["dimension"] = "diagnosis"
        if not intent.get("top"):
            intent["top"] = 20
    elif hint == "quality_facility":
        # 固定 facility 维度，只补 top 默认 15（医院名长）
        if not intent.get("top"):
            intent["top"] = 15
    elif hint == "quality_overview":
        pass  # 无业务参数，只接受 filters
    elif hint == "quality_disposition":
        pass  # 无业务参数，只接受 filters


def _parse_intent_by_rules(question: str, history: list[dict]) -> dict:
    """规则引擎解析意图，支持简单的上下文继承。"""
    intent = {
        "dimension": None, "metric": None, "filters": {}, "top": None,
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

    # 兜底：问句含「费用」+「构成」但「费用构成」非连续（如"住院费用按医院是怎么构成的"），
    # 归到费用构成端点，避免被指标匹配误判为通用聚合（/analysis/aggregate）。
    if not intent["chart_hint"] and "费用" in question and "构成" in question:
        intent["chart_hint"] = "composition"

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
        intent["top"] = max(intent["top"] or 0, 3)

    # 上下文继承（多轮上下文增强）：从最近轮开始回填当前缺失的字段。
    # 只填空缺项、不覆盖当前问题已明确解析出的字段，避免误继承；
    # 一旦 dimension 已被最近的某轮填好即停止回溯，避免被更早的无关话题覆盖。
    # 相比旧实现（仅继承 history[-1]），本实现支持「中途换话题后再次追问」仍能
    # 正确继承更早的相关上下文。
    if history:
        for turn in reversed(history):
            prev = turn.get("intent", {}) or {}
            if not intent["dimension"] and prev.get("dimension"):
                intent["dimension"] = prev["dimension"]
            if not intent["metric"] and prev.get("metric"):
                intent["metric"] = prev["metric"]
            # top 继承（当前没指定且没默认时，沿用历史中的 top）
            if not intent["top"] and prev.get("top"):
                intent["top"] = prev["top"]
            pf = prev.get("filters", {}) or {}
            # 年份继承（只有当前没指定才继承）
            if "year" not in intent["filters"] and pf.get("year"):
                intent["filters"]["year"] = pf["year"]
            # gender 继承
            if "gender" not in intent["filters"] and pf.get("gender"):
                intent["filters"]["gender"] = pf["gender"]
            # age_group 继承
            if "age_group" not in intent["filters"] and pf.get("age_group"):
                intent["filters"]["age_group"] = pf["age_group"]
            # chart_hint 继承（用户第 2 轮"换成年龄段视角"时自动继承第 1 轮的 chart_hint）
            if not intent["chart_hint"] and prev.get("chart_hint"):
                intent["chart_hint"] = prev["chart_hint"]
            for f in ("by", "dim1", "dim2", "group", "levels", "level", "mode"):
                if not intent.get(f) and prev.get(f):
                    intent[f] = prev[f]
            # 注意：这里**不**在遇到 dimension 后提前 break。只填空缺字段、不覆盖已解析值，
            # 所以继续扫描更靠前的轮次也能安全补回缺失的 filters（如更早轮带的 year），
            # 同时不会把 dimension 覆盖成更早的无关话题。

    # —— 命中 chart_hint 时，补 by/dim1/dim2/group/levels 默认值 ——
    if intent["chart_hint"]:
        _infer_chart_hint_params(intent, question)
    else:
        # 智能推断 1：top-N 自然句式 —— "住院人数最多的前3种疾病"
        # 没命中显式关键词，但 dimension 已识别为 diagnosis/procedure 且问句含 top-N 意图时，
        # 自动升级到新接口（新接口能返回 code+name，旧 /analysis/aggregate 只返回 key）
        dim = intent.get("dimension")
        top_intent = any(w in question for w in ("最多", "前几", "排行", "top", "Top", "TOP",
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

    # 修复 BUG 2.2 兜底：top 最终保底为 10（避免 None 透传给 P3）
    # 优先级：显式数字 > chart_hint 专用默认（_infer_chart_hint_params 设的 20/15）
    #          > 上下文继承 > 全局默认 10
    if not intent["top"]:
        intent["top"] = 10
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
    ok_json, check, _reason = _extract_json_from_llm_output(content)
    if not ok_json or not isinstance(check, dict):
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
def _map_metric(metric: str, allowed: set) -> tuple[str, bool]:
    """把 P4 metric 翻译为 P3 新接口 metric，并校验白名单。不支持时降级 count。

    返回 (p3_metric, was_degraded)：
      - p3_metric: 实际使用的 P3 metric
      - was_degraded: 是否发生了静默降级（True 时调用方应写 meta 警告，避免用户误以为数据是原 metric）

    修复 BUG 1：之前 total_costs/avg_costs 直接降级 count 不提示，用户问"总成本排行"
    会拿到"人数排行"还以为正确。现在降级会暴露给用户。
    """
    p3_metric = METRIC_TO_P3.get(metric)
    if p3_metric is None or p3_metric not in allowed:
        return "count", True
    return p3_metric, False


def _build_severity_profile_params(intent: dict) -> dict:
    by = intent.get("by") or "age_group"
    if by not in ("age_group", "medical_surgical", "payment"):
        by = "age_group"
    metric, degraded = _map_metric(intent.get("metric"), {"count", "avg_charges"})
    params = {"by": by, "metric": metric}
    if degraded:
        params["__metric_degraded"] = True
    return params


def _build_population_diff_params(intent: dict) -> dict:
    dim = intent.get("by") or "gender"
    if dim not in ("gender", "race", "medical_surgical"):
        dim = "gender"
    metric, degraded = _map_metric(intent.get("metric"), {"count", "avg_charges", "avg_los"})
    params = {"dimension": dim, "metric": metric}
    if degraded:
        params["__metric_degraded"] = True
    return params


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
    metric, degraded = _map_metric(intent.get("metric"), {"count", "avg_charges", "avg_los"})
    params = {"dim1": dim1, "dim2": dim2, "metric": metric,
              "top": min(intent.get("top", 15), 50)}
    if degraded:
        params["__metric_degraded"] = True
    return params


def _build_payment_composition_params(intent: dict) -> dict:
    group = intent.get("group") or "payment1"
    if group not in ("payment1", "payment2", "payment3"):
        group = "payment1"
    metric, degraded = _map_metric(intent.get("metric"), {"count", "total_charges"})
    params = {"group": group, "metric": metric}
    if degraded:
        params["__metric_degraded"] = True
    return params


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
    metric, degraded = _map_metric(intent.get("metric"), {"count", "total_charges", "avg_charges"})
    params = {
        "level": level,
        "metric": metric,
        "top": min(intent.get("top", top_default), 50),
    }
    if degraded:
        params["__metric_degraded"] = True
    return params


def _build_payment_cross_params(intent: dict) -> dict:
    dim2 = intent.get("dim2") or "age_group"
    if dim2 not in ("age_group", "diagnosis", "severity"):
        dim2 = "age_group"
    metric, degraded = _map_metric(intent.get("metric"), {"count", "total_charges"})
    params = {
        "dim2": dim2,
        "metric": metric,
        "top": min(intent.get("top", 15), 50),
    }
    if degraded:
        params["__metric_degraded"] = True
    return params


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
    metric, degraded = _map_metric(intent.get("metric"),
                                    {"count", "total_charges", "avg_charges", "avg_los"})
    params = {"metric": metric, "top": min(intent.get("top", 20), 100)}
    if degraded:
        params["__metric_degraded"] = True
    return params


def _build_top_procedures_params(intent: dict) -> dict:
    metric, degraded = _map_metric(intent.get("metric"),
                                    {"count", "total_charges", "avg_charges"})
    params = {"metric": metric, "top": min(intent.get("top", 20), 100)}
    if degraded:
        params["__metric_degraded"] = True
    return params


# —— 费用成本分析模块（5 个，对接 P3 /cost/* 新端点）——
# cost 模块维度翻译：规则引擎对「病种/诊断/疾病」产出 ccsr_diagnosis，
# 而 cost 新接口（/cost/*）的合法维度是 diagnosis，需在此归一。
# 注意：不要用 DIM_TO_P3_DIM（那是 disease 模块的 by 维度翻译，会把
# payment_typology 翻成 payment，反而不被 cost 接受而 400）。
_COST_DIM_ALIASES = {"ccsr_diagnosis": "diagnosis"}


def _build_cost_profit_difference_params(intent: dict) -> dict:
    _dim = _COST_DIM_ALIASES.get(intent.get("dimension"), intent.get("dimension"))
    params = {"dimension": _dim, "top": min(intent.get("top") or 20, 100)}
    if intent.get("year"):
        params["year"] = intent["year"]
    return params


def _build_cost_profit_margin_params(intent: dict) -> dict:
    _dim = _COST_DIM_ALIASES.get(intent.get("dimension"), intent.get("dimension"))
    params = {"dimension": _dim, "top": min(intent.get("top") or 20, 100),
              "order": intent.get("order") or "desc"}
    if intent.get("year"):
        params["year"] = intent["year"]
    return params


def _build_cost_efficiency_ranking_params(intent: dict) -> dict:
    _dim = _COST_DIM_ALIASES.get(intent.get("dimension"), intent.get("dimension"))
    params = {"dimension": _dim, "top": min(intent.get("top") or 30, 100)}
    if intent.get("year"):
        params["year"] = intent["year"]
    return params


def _build_cost_composition_params(intent: dict) -> dict:
    _dim = _COST_DIM_ALIASES.get(intent.get("dimension"), intent.get("dimension"))
    params = {"dimension": _dim, "top": min(intent.get("top") or 10, 50)}
    if intent.get("year"):
        params["year"] = intent["year"]
    return params


def _build_cost_trend_params(intent: dict) -> dict:
    params = {"metric": intent.get("metric") or "total_charges"}
    if intent.get("start_year"):
        params["start_year"] = intent["start_year"]
    if intent.get("end_year"):
        params["end_year"] = intent["end_year"]
    dim = intent.get("dimension")
    # 趋势端点本身按 discharge_year 聚合；规则引擎把“近年趋势”解析出的
    # discharge_year 维度是冗余的，直接视为整体趋势（否则 P3 报 400）。
    if dim and dim != "discharge_year":
        params["dimension"] = _COST_DIM_ALIASES.get(dim, dim)
    if intent.get("dimension_value"):
        params["dimension_value"] = intent["dimension_value"]
    return params


# 医疗质量监测模块维度命名空间：P4 dimension → P3 quality dimension。
# 注意 facility 在 quality 命名空间仍是 facility（不同于 DIM_TO_P3_DIM 的 service_area 映射）。
_QUALITY_DIM_MAP = {
    "ccsr_diagnosis": "diagnosis",
    "diagnosis": "diagnosis",
    "facility": "facility",
    "age_group": "age_group",
    "severity": "severity",
    "risk_mortality": "risk_mortality",
}


def _norm_quality_dimension(dim):
    """把 P4/P3 两套 dimension 统一到 quality 白名单，非法值回退 diagnosis。"""
    if dim not in _QUALITY_DIM_MAP:
        return "diagnosis"
    return _QUALITY_DIM_MAP[dim]


def _build_quality_overview_params(intent: dict) -> dict:
    return {}  # overview 只接受 filters，无业务参数


def _build_quality_mortality_params(intent: dict) -> dict:
    return {
        "dimension": _norm_quality_dimension(intent.get("dimension")),
        "top": min(intent.get("top", 20), 100),
        "min_cases": min(max(intent.get("min_cases", 30), 1), 10000),
    }


def _build_quality_los_params(intent: dict) -> dict:
    return {
        "dimension": _norm_quality_dimension(intent.get("dimension")),
        "top": min(intent.get("top", 20), 100),
        "min_cases": min(max(intent.get("min_cases", 30), 1), 10000),
    }


def _build_quality_facility_params(intent: dict) -> dict:
    return {
        "top": min(intent.get("top", 15), 100),
        "min_cases": min(max(intent.get("min_cases", 100), 1), 10000),
    }


def _build_quality_disposition_params(intent: dict) -> dict:
    return {}  # disposition 只接受 filters，无业务参数


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
    # —— 模块三：费用成本分析（5 个，对接 /cost/*）——
    # 注意：趋势端点 chart_hint 用 cost_trend，避免与遗留 /analysis/trend 的 trend 冲突
    # 数据量为百万级（2021+2022 全量），聚合查询较慢，timeout 提高到 60s（旧管道共用）
    "profit_difference":   {"endpoint": "/cost/profit-difference",   "build": _build_cost_profit_difference_params,   "timeout": 60},
    "profit_margin":       {"endpoint": "/cost/profit-margin",       "build": _build_cost_profit_margin_params,       "timeout": 60},
    "efficiency_ranking":  {"endpoint": "/cost/efficiency-ranking",  "build": _build_cost_efficiency_ranking_params,  "timeout": 60},
    "composition":         {"endpoint": "/cost/composition",         "build": _build_cost_composition_params,         "timeout": 60},
    "cost_trend":          {"endpoint": "/cost/trend",               "build": _build_cost_trend_params,               "timeout": 60},
    # —— 模块四：医疗质量监测（5 个，/api/v1/quality/*）——
    "quality_overview":    {"endpoint": "/quality/overview",         "build": _build_quality_overview_params,    "timeout": 15},
    "quality_mortality":   {"endpoint": "/quality/mortality",        "build": _build_quality_mortality_params,   "timeout": 15},
    "quality_los":         {"endpoint": "/quality/length-of-stay",   "build": _build_quality_los_params,         "timeout": 15},
    "quality_facility":    {"endpoint": "/quality/facility-ranking", "build": _build_quality_facility_params,    "timeout": 15},
    "quality_disposition": {"endpoint": "/quality/disposition",      "build": _build_quality_disposition_params, "timeout": 15},
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
    # —— 第一步：意图审查（不阻塞、不改变调用）——
    # 优化1：优先复用 _parse_intent_by_llm 已经产出的 _validation 字段，
    # 避免在这里再调一次小模型；只有字段缺失（规则解析或老缓存）才回退到独立调用。
    validation = {}
    # 修复 BUG 2.3：如果意图来自 rules_fallback（LLM 解析失败）或纯 rules（LLM 没启用），
    # 直接跳过 LLM 校验——既然 LLM 刚才失败了，这里再调大概率也失败，白白浪费一次请求。
    # 只有 LLM 成功解析（intent["_source"] == "llm"）时才尝试复用或调用 LLM 校验。
    intent_source = intent.get("_source", "rules")
    if use_llm_validate and LLM_ENABLED and intent_source == "llm":
        cached_validation = intent.get("_validation")
        if isinstance(cached_validation, dict) and cached_validation:
            validation = cached_validation
        else:
            try:
                validation = _validate_intent_by_llm(intent, question)
            except Exception:
                validation = {}  # 永远不让审查影响主链路

    # —— 第二步：路由决策（chart_hint 优先，未命中走旧 if-elif）——
    chart_hint = intent.get("chart_hint")
    filters = intent.get("filters", {})
    # 待写入 meta 的警告列表（BUG 1/2：metric 降级 / dimension 被忽略都要提示用户）
    _pending_meta_warnings = []

    if chart_hint and chart_hint in ROUTE_TABLE:
        # 走 P3 新版接口
        route = ROUTE_TABLE[chart_hint]
        url = f"{ANALYSIS_API}{route['endpoint']}"
        params = route["build"](intent)
        timeout = route["timeout"]

        # 修复 BUG 1：检测 _map_metric 的静默降级，写入 meta 警告告知用户
        # （例如用户问"总成本排行"，但 total_costs 不支持，会降级为 count，必须提示）
        if params.pop("__metric_degraded", False):
            original_metric = intent.get("metric") or ""
            logger.warning(
                "metric 降级：chart_hint=%s 用户期望 metric=%s，"
                "但该接口不支持，已降级为 count。请提示用户。",
                chart_hint, original_metric
            )
            # 把降级信息写到 meta，下游 handle_question 会传给前端
            _pending_meta_warnings.append({
                "type": "metric_degraded",
                "chart_hint": chart_hint,
                "original_metric": original_metric,
                "actual_metric": params.get("metric", "count"),
                "message": (
                    f"您询问的指标「{METRIC_ZH.get(original_metric, original_metric)}」"
                    f"在当前图表类型下不支持，已自动改用「住院人数」展示。"
                    "如需费用相关排行，请尝试：『各诊断的总费用排行』（用 total_charges）。"
                ),
            })

        # 修复 BUG 2：检测 dimension 拋留（新接口语义是固定维度，残留 dimension 会误导用户）
        # 仅在 dimension 非空且不是该接口预期维度时提示
        residual_dim = intent.get("dimension")
        if residual_dim:
            # chart_hint 对应的"预期维度"集合（None 表示该接口不接受 dimension 参数）
            expected_dims = {
                "top_diagnoses": None,        # 只看诊断排行，不按其他维度分组
                "top_procedures": None,
                "pyramid": None,             # 固定 年龄×性别
                "payment_summary": None,     # 固定 KPI 大屏
                "severity_profile": {"severity"},  # 严重程度是主题，by 才是分组维度
                "population_diff": {"gender", "race", "medical_surgical"},
                "region_diff": {"service_area", "county", "facility"},
                "heatmap": None,             # dim1/dim2 才是有效维度
                "payment_composition": None,
                "payment_cross": None,       # dim2 才是有效维度
                "sankey": None,
                "cost_relation": None,       # by 才是有效维度
                "oop_burden": {"disease", "age_group", "county"},
                "quality_overview": None,    # 全局 KPI 卡片，不接受 dimension
                "quality_mortality": {"diagnosis", "facility", "age_group", "severity", "risk_mortality"},
                "quality_los": {"diagnosis", "facility", "age_group", "severity", "risk_mortality"},
                "quality_facility": {"facility"},  # 固定医院维度（避免误报"维度被忽略"）
                "quality_disposition": None, # 全局饼图，不接受 dimension
            }
            expected = expected_dims.get(chart_hint)
            if expected is None and chart_hint in expected_dims:
                # 该接口完全不接受 dimension 参数 → 用户指定的维度会被忽略，必须提示
                logger.warning(
                    "dimension 被忽略：chart_hint=%s 用户指定 dimension=%s，"
                    "但该接口不接受 dimension 参数，返回全局结果。",
                    chart_hint, residual_dim
                )
                _pending_meta_warnings.append({
                    "type": "dimension_ignored",
                    "chart_hint": chart_hint,
                    "ignored_dimension": residual_dim,
                    "message": (
                        f"您指定的维度「{DIMENSION_ZH.get(residual_dim, residual_dim)}」"
                        f"在当前图表类型（{CHART_HINT_TITLE_ZH.get(chart_hint, chart_hint)}）"
                        "下不支持分组，已返回全局排行结果。"
                        "如需按该维度分组，请换用『通用聚合』问法（如『各医院住院人数』）。"
                    ),
                })
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
    # 统一复用 _apply_filters_to_params（与 _call_p3_api 一致，避免两处重复维护）
    _apply_filters_to_params(params, filters)

    # —— 容错加固：旧管道 P3 调用统一错误兜底（与 Agent 路径 _call_p3_api 一致）——
    # P3 超时/连接失败/非 JSON/业务错误 均返回结构化 {"error":...,"data":[],"meta":...}
    # 而非抛出未捕获异常（避免 Agent 降级链再次崩溃，最终落到 Flask 500）。
    try:
        _obs_inc("p3_calls_total")
        _t0 = time.time()
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        try:
            result = resp.json()
        except (ValueError, json.JSONDecodeError):
            logger.error("P3 返回非 JSON（旧管道）：url=%s status=%s",
                         url, resp.status_code)
            _obs_latency("p3_latency_ms_total", (time.time() - _t0) * 1000)
            _log_event("p3_result", chart_hint=chart_hint, endpoint=url,
                       ok=False, error="invalid_response")
            return _make_p3_error(chart_hint, "invalid_response",
                                  f"status={resp.status_code}")
        if _is_p3_logical_error(result):
            reason = (result.get("message") or result.get("msg")
                      or result.get("error") or f"code={result.get('code')}")
            logger.warning("P3 业务错误（旧管道）：chart_hint=%s reason=%s",
                           chart_hint, reason)
            _obs_latency("p3_latency_ms_total", (time.time() - _t0) * 1000)
            _log_event("p3_result", chart_hint=chart_hint, endpoint=url,
                       ok=False, error="p3_error")
            return _make_p3_error(chart_hint, "p3_error", str(reason)[:200])
        _obs_latency("p3_latency_ms_total", (time.time() - _t0) * 1000)
        _log_event("p3_result", chart_hint=chart_hint, endpoint=url, ok=True)
        # 旧接口分支不走 _call_p3_api，需在此把 chart_hint 写入 meta（与新接口分支一致）
        result.setdefault("meta", {})["chart_hint"] = chart_hint

        # 把 LLM 审查结果写入 meta（前端可以展示"系统建议"）
        if validation:
            result.setdefault("meta", {})
            result["meta"]["intent_validation"] = validation
            result["meta"]["intent_validation_used"] = "llm"
        else:
            result.setdefault("meta", {})
            result["meta"]["intent_validation_used"] = "rules_only"

        # 修复 BUG 1/2：把降级/忽略警告写入 meta，下游会传给前端
        if _pending_meta_warnings:
            result.setdefault("meta", {})
            result["meta"]["warnings"] = _pending_meta_warnings

        return result
    except requests.exceptions.Timeout:
        logger.warning("P3 超时（旧管道）：chart_hint=%s", chart_hint)
        return _make_p3_error(chart_hint, "timeout")
    except requests.exceptions.ConnectionError:
        logger.warning("P3 连接失败（旧管道）：chart_hint=%s", chart_hint)
        return _make_p3_error(chart_hint, "connection_failed")
    except Exception as e:
        logger.error("P3 异常（旧管道）：chart_hint=%s err=%s", chart_hint, e)
        return _make_p3_error(chart_hint, str(e)[:200])


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
    "facility": "医院", "risk_mortality": "死亡风险",
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


# ============================================================
# LangChain Agent 重构区
# 将 13 个 chart_hint 路由 + 3 个遗留路由封装为 StructuredTool，
# 用 create_tool_calling_agent 替换 parse_intent + call_analysis_api 的手工分发
# ============================================================

# --- Section A: P3 API 调用公共辅助 ---

def _make_p3_error(chart_hint, kind: str, detail: str = "") -> dict:
    """生成结构统一的 P3 调用失败结果，供 _call_p3_api / call_analysis_api 共用。

    下游 _finalize_result → generate_text_summary 会据此返回友好提示，
    而不是把原始异常抛到 Flask 层变成 500。
    """
    meta = {"chart_hint": chart_hint, "error": kind}
    if detail:
        meta["error_detail"] = detail[:200]
    # 可观测：所有 P3 错误（Agent 路径 + 旧管道）统一在此累加，单一计数源
    _obs_inc("p3_error_total")
    _obs_nested_inc("p3_errors_by_kind", kind)
    return {"error": kind, "data": [], "meta": meta}


def _is_p3_logical_error(result) -> bool:
    """识别 P3 返回 200 但业务失败的信封（避免把错误当成功继续处理）：

    - 含 "error" 键
    - success 显式为 False
    - code 为非 0 整数
    """
    if not isinstance(result, dict):
        return False
    if "error" in result:
        return True
    if result.get("success") is False:
        return True
    code = result.get("code")
    if isinstance(code, int) and code != 0:
        return True
    return False


def _call_p3_api(chart_hint: str | None, endpoint: str, params: dict,
                 timeout: int = 15) -> dict:
    """通用 P3 API GET 调用，统一错误处理，返回带 chart_hint 标记的 result。

    chart_hint 为 None 表示遗留路由（aggregate / payment-mix / trend）。

    容错分层：
      1) 非 JSON 响应（200 但 body 非法）→ invalid_response
      2) 业务错误信封（200 但 code!=0 / error / success=false）→ p3_error
      3) 瞬时可重试错误（超时/连接失败）按 P3_API_RETRIES 退避重试一次
      4) 其它异常 → 原始错误字符串
    """
    url = f"{ANALYSIS_API}{endpoint}"
    retries = int(os.getenv("P3_API_RETRIES", "1"))
    last_err = None
    _obs_inc("p3_calls_total")
    _t0 = time.time()
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            try:
                result = resp.json()
            except (ValueError, json.JSONDecodeError):
                logger.error("P3 返回非 JSON：chart_hint=%s endpoint=%s status=%s",
                             chart_hint, endpoint, resp.status_code)
                return _make_p3_error(chart_hint, "invalid_response",
                                      f"status={resp.status_code}")
            if _is_p3_logical_error(result):
                reason = (result.get("message") or result.get("msg")
                          or result.get("error") or f"code={result.get('code')}")
                logger.warning("P3 业务错误：chart_hint=%s endpoint=%s reason=%s",
                               chart_hint, endpoint, reason)
                return _make_p3_error(chart_hint, "p3_error", str(reason)[:200])
            result.setdefault("meta", {})["chart_hint"] = chart_hint
            _obs_latency("p3_latency_ms_total", (time.time() - _t0) * 1000)
            _log_event("p3_result", chart_hint=chart_hint, endpoint=endpoint,
                       ok=True, attempt=attempt + 1)
            return result
        except requests.exceptions.Timeout:
            last_err = "timeout"
            logger.warning("P3 超时(第%d次)：chart_hint=%s endpoint=%s",
                           attempt + 1, chart_hint, endpoint)
        except requests.exceptions.ConnectionError:
            last_err = "connection_failed"
            logger.warning("P3 连接失败(第%d次)：chart_hint=%s endpoint=%s",
                           attempt + 1, chart_hint, endpoint)
        except Exception as e:
            last_err = str(e)[:200]
            logger.error("P3 异常：chart_hint=%s endpoint=%s err=%s",
                         chart_hint, endpoint, e)
            break  # 非瞬时错误不重试
        # 仅瞬时可重试错误才退避后重试
        if attempt < retries and last_err in ("timeout", "connection_failed"):
            time.sleep(0.3)
    _obs_latency("p3_latency_ms_total", (time.time() - _t0) * 1000)
    _log_event("p3_result", chart_hint=chart_hint, endpoint=endpoint,
               ok=False, error=last_err or "unknown")
    return _make_p3_error(chart_hint, last_err or "unknown")


def _apply_filters_to_params(params: dict, filters: dict | None) -> dict:
    """把 filters 中的白名单字段透传到 params（复用 P3_FILTER_KEYS）。"""
    filters = filters or {}
    for fkey in P3_FILTER_KEYS:
        if fkey in filters:
            params[fkey] = filters[fkey]
    return params


def _check_metric_degradation(params: dict, chart_hint: str,
                              original_metric: str) -> list:
    """检测 _build_xxx_params 产出的 __metric_degraded 标记，返回 warning 列表。"""
    warnings = []
    if params.pop("__metric_degraded", False):
        actual_metric = params.get("metric", "count")
        warnings.append({
            "type": "metric_degraded",
            "chart_hint": chart_hint,
            "original_metric": original_metric or "",
            "actual_metric": actual_metric,
            "message": (
                f"您询问的指标「{METRIC_ZH.get(original_metric, original_metric)}」"
                f"在当前图表类型下不支持，已自动改用"
                f"「{METRIC_ZH.get(actual_metric, actual_metric)}」展示。"
                "如需费用相关排行，请尝试：『各诊断的总费用排行』。"
            ),
        })
    return warnings


def _dispatch_chart_hint(chart_hint: str, **kwargs) -> dict:
    """13 个 chart_hint 工具共用的调度器（消除 _execute_xxx 样板代码）。

    从 ROUTE_TABLE 取 endpoint / timeout / build，用工具入参构造 intent，
    构建参数 → 应用 filters → 调用 P3 → 检查 metric 降级，返回结构化结果。
    """
    route = ROUTE_TABLE[chart_hint]
    filters = kwargs.get("filters") or {}
    intent = {k: v for k, v in kwargs.items() if k != "filters"}
    intent["filters"] = filters
    params = route["build"](intent)
    _apply_filters_to_params(params, filters)
    result = _call_p3_api(chart_hint, route["endpoint"], params,
                          timeout=route["timeout"])
    # 仅当 _build_xxx_params 标记了静默降级时才告警（与原逐函数逻辑一致）
    w = _check_metric_degradation(params, chart_hint, intent.get("metric", ""))
    if w:
        result.setdefault("meta", {})["warnings"] = w
    return result


def _dispatch_legacy(endpoint: str, timeout: int, **kwargs) -> dict:
    """3 个遗留路由（aggregate / payment-mix / trend）共用的调度器。

    遗留路由不在 ROUTE_TABLE 中（向后兼容旧 /analysis/* 端点），故单独传 endpoint + timeout。
    """
    filters = kwargs.get("filters") or {}
    params = {k: v for k, v in kwargs.items() if k != "filters" and v is not None}
    _apply_filters_to_params(params, filters)
    return _call_p3_api(None, endpoint, params, timeout=timeout)


# --- Section B: Pydantic 输入模型（每个工具的参数 schema）---
# 13 个 chart_hint 工具 + 3 个遗留路由工具

_FILTERS_DESC = (
    "筛选条件，可选key: year(int 如2021), gender('M'男性/'F'女性), "
    "age_group(如'70 or Older','0 to 17','18 to 29','30 to 49','50 to 69'), "
    "payment, payment2, payment3, severity('Minor'/'Moderate'/'Major'/'Extreme'), "
    "diagnosis, procedure, service_area, county, facility"
)


class _TopDiagnosesInput(BaseModel):
    metric: Literal["count", "total_charges", "avg_charges", "avg_los"] = Field(
        default="count",
        description="统计指标：count=住院人数, total_charges=总费用(元), "
                    "avg_charges=平均费用(元), avg_los=平均住院时长(天)")
    top: int = Field(default=20, ge=1, le=100, description="返回前N条，默认20，最大100")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _TopProceduresInput(BaseModel):
    metric: Literal["count", "total_charges", "avg_charges"] = Field(
        default="count",
        description="统计指标：count=住院人数, total_charges=总费用(元), "
                    "avg_charges=平均费用(元)")
    top: int = Field(default=20, ge=1, le=100, description="返回前N条，默认20，最大100")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _SeverityProfileInput(BaseModel):
    by: Literal["age_group", "medical_surgical", "payment"] = Field(
        default="age_group",
        description="分组维度：age_group=年龄段, medical_surgical=医疗/外科, payment=支付方式")
    metric: Literal["count", "avg_charges"] = Field(
        default="count", description="统计指标：count=住院人数, avg_charges=平均费用(元)")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _PopulationDiffInput(BaseModel):
    dimension: Literal["gender", "race", "medical_surgical"] = Field(
        default="gender",
        description="人群维度：gender=性别, race=种族, medical_surgical=医疗/外科")
    metric: Literal["count", "avg_charges", "avg_los"] = Field(
        default="count",
        description="统计指标：count=住院人数, avg_charges=平均费用(元), avg_los=平均住院时长(天)")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _PyramidInput(BaseModel):
    filters: dict = Field(
        default_factory=dict,
        description=_FILTERS_DESC + "。人口金字塔固定按年龄段×性别展示，无额外业务参数")


class _HeatmapInput(BaseModel):
    dim1: Literal["diagnosis", "procedure", "age_group", "severity",
                  "gender", "payment", "service_area"] = Field(
        default="diagnosis", description="热力图X轴维度")
    dim2: Literal["diagnosis", "procedure", "age_group", "severity",
                  "gender", "payment", "service_area"] = Field(
        default="age_group", description="热力图Y轴维度（不能与dim1相同）")
    metric: Literal["count", "avg_charges", "avg_los"] = Field(
        default="count", description="统计指标")
    top: int = Field(default=15, ge=1, le=50,
                     description="每个维度返回前N条，默认15，最大50")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _RegionDiffInput(BaseModel):
    level: Literal["service_area", "county", "facility"] = Field(
        default="service_area",
        description="地区层级：service_area=服务区, county=区县, facility=医院")
    metric: Literal["count", "total_charges", "avg_charges"] = Field(
        default="count", description="统计指标")
    top: int = Field(default=20, ge=1, le=50,
                     description="返回前N条，默认20(facility为15)，最大50")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _PaymentCompositionInput(BaseModel):
    group: Literal["payment1", "payment2", "payment3"] = Field(
        default="payment1",
        description="支付层级：payment1=一级支付, payment2=二级支付, payment3=三级支付")
    metric: Literal["count", "total_charges"] = Field(
        default="count", description="统计指标：count=住院人数, total_charges=总费用(元)")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _PaymentCrossInput(BaseModel):
    dim2: Literal["age_group", "diagnosis", "severity"] = Field(
        default="age_group",
        description="交叉维度：age_group=年龄段, diagnosis=疾病诊断, severity=严重程度")
    metric: Literal["count", "total_charges"] = Field(
        default="count", description="统计指标")
    top: int = Field(default=15, ge=1, le=50, description="返回前N条，默认15，最大50")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _SankeyInput(BaseModel):
    levels: Literal[
        "payment,payment2", "payment,payment2,payment3",
        "payment,age_group", "payment,age_group,disease",
        "payment,disease", "payment,severity"] = Field(
        default="payment,payment2", description="桑基图分层级别，用逗号分隔")
    top_disease: int = Field(default=8, ge=1, le=20,
                             description="显示前N种疾病，默认8，最大20")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _CostRelationInput(BaseModel):
    by: Literal["payment", "age_group", "diagnosis"] = Field(
        default="payment",
        description="分组维度：payment=支付方式, age_group=年龄段, diagnosis=疾病诊断")
    top: int = Field(default=30, ge=1, le=100, description="返回前N条，默认30，最大100")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _OopBurdenInput(BaseModel):
    dimension: Literal["disease", "age_group", "county"] = Field(
        default="disease",
        description="分析维度：disease=按疾病, age_group=按年龄段, county=按区县")
    mode: Literal["selfpay1", "any_layer"] = Field(
        default="selfpay1",
        description="自付计算方式：selfpay1=仅一级自付, any_layer=任意层自付")
    top: int = Field(default=15, ge=1, le=50, description="返回前N条，默认15，最大50")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _PaymentSummaryInput(BaseModel):
    filters: dict = Field(
        default_factory=dict,
        description=_FILTERS_DESC + "。KPI总览无额外业务参数")


# 费用成本分析模块（5 个，对接 P3 /cost/*）
_COST_DIMS = Literal["age_group", "diagnosis", "drg", "facility", "mdc", "payment_typology"]


class _CostProfitDifferenceInput(BaseModel):
    dimension: _COST_DIMS = Field(
        default="drg",
        description="分组维度：age_group=年龄段, diagnosis=疾病诊断, drg=DRG分组, "
                    "facility=医院, mdc=MDC大类, payment_typology=支付方式")
    top: int = Field(default=20, ge=1, le=100, description="返回前N条，默认20，最大100")
    year: int = Field(default=0, description="年份筛选(如2021)，0表示不限")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _CostProfitMarginInput(BaseModel):
    dimension: _COST_DIMS = Field(
        default="age_group",
        description="分组维度：age_group=年龄段, diagnosis=疾病诊断, drg=DRG分组, "
                    "facility=医院, mdc=MDC大类, payment_typology=支付方式")
    top: int = Field(default=20, ge=1, le=100, description="返回前N条，默认20，最大100")
    order: Literal["desc", "asc"] = Field(default="desc", description="排序：desc降序/asc升序")
    year: int = Field(default=0, description="年份筛选(如2021)，0表示不限")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _CostEfficiencyRankingInput(BaseModel):
    dimension: _COST_DIMS = Field(
        default="mdc",
        description="分组维度：age_group=年龄段, diagnosis=疾病诊断, drg=DRG分组, "
                    "facility=医院, mdc=MDC大类, payment_typology=支付方式")
    top: int = Field(default=30, ge=1, le=100, description="返回前N条，默认30，最大100")
    year: int = Field(default=0, description="年份筛选(如2021)，0表示不限")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _CostCompositionInput(BaseModel):
    dimension: _COST_DIMS = Field(
        default="mdc",
        description="分组维度：age_group=年龄段, diagnosis=疾病诊断, drg=DRG分组, "
                    "facility=医院, mdc=MDC大类, payment_typology=支付方式")
    top: int = Field(default=10, ge=1, le=50, description="返回前N条，默认10，最大50")
    year: int = Field(default=0, description="年份筛选(如2021)，0表示不限")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _CostTrendInput(BaseModel):
    metric: Literal["total_charges", "total_costs", "profit_margin"] = Field(
        default="total_charges",
        description="指标：total_charges=总费用, total_costs=总成本, profit_margin=利润率")
    start_year: int = Field(default=0, description="起始年份，0表示不限")
    end_year: int = Field(default=0, description="结束年份，0表示不限")
    dimension: str = Field(default="", description="可选分组维度(age_group/diagnosis/drg/facility/mdc/payment_typology)，留空为整体趋势")
    dimension_value: str = Field(default="", description="指定维度取值(配合 dimension 使用)")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


# 遗留路由模型（向后兼容旧 /analysis/aggregate, payment-mix, trend）
class _GeneralAggregateInput(BaseModel):
    dimension: Literal["age_group", "gender", "ccsr_diagnosis",
                       "payment_typology", "facility", "discharge_year"] = Field(
        default="ccsr_diagnosis", description="分组维度")
    metric: Literal["count", "avg_length_of_stay", "total_charges",
                    "avg_charges"] = Field(
        default="count",
        description="统计指标：count=住院人数, avg_length_of_stay=平均住院时长(天), "
                    "total_charges=总费用(元), avg_charges=平均费用(元)")
    top: int = Field(default=10, ge=1, le=100, description="返回前N条，默认10，最大100")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _PaymentMixInput(BaseModel):
    filters: dict = Field(
        default_factory=dict,
        description=_FILTERS_DESC + "。支付方式占比无额外业务参数")


class _TrendInput(BaseModel):
    filters: dict = Field(
        default_factory=dict,
        description=_FILTERS_DESC + "。历年趋势无额外业务参数")


# --- Section C: _execute_xxx 工具函数（13 个核心 + 3 个遗留）---

def _execute_top_diagnoses(metric: str = "count", top: int = 20,
                           filters: dict = None) -> dict:
    """查询住院患者疾病诊断排行（按CCSR编码+名称返回Top N）。
    适用于"常见疾病""高发疾病""诊断排行""疾病top""什么病最多"等问法。"""
    return _dispatch_chart_hint("top_diagnoses", metric=metric, top=top, filters=filters)


def _execute_top_procedures(metric: str = "count", top: int = 20,
                            filters: dict = None) -> dict:
    """查询住院患者手术术式排行（按术式编码+名称返回Top N）。
    适用于"常见手术""高频手术""手术排行""手术top"等问法。"""
    return _dispatch_chart_hint("top_procedures", metric=metric, top=top, filters=filters)


def _execute_severity_profile(by: str = "age_group", metric: str = "count",
                               filters: dict = None) -> dict:
    """查询病重程度构成（按指定维度分组的严重程度堆叠分布）。
    适用于"严重程度""病重分布""危重患者""堆叠图"等问法。"""
    return _dispatch_chart_hint("severity_profile", by=by, metric=metric, filters=filters)


def _execute_population_diff(dimension: str = "gender", metric: str = "count",
                             filters: dict = None) -> dict:
    """查询人群分布差异（按性别/种族/医疗外科分组的对比柱状图）。
    适用于"性别差异""年龄差异""种族差异""人群差异"等问法。"""
    return _dispatch_chart_hint("population_diff", by=dimension, metric=metric, filters=filters)


def _execute_pyramid(filters: dict = None) -> dict:
    """查询人口金字塔（按年龄段×性别的双侧金字塔图）。
    适用于"人口金字塔""性别年龄分布""金字塔图"等问法。"""
    return _dispatch_chart_hint("pyramid", filters=filters)


def _execute_heatmap(dim1: str = "diagnosis", dim2: str = "age_group",
                     metric: str = "count", top: int = 15,
                     filters: dict = None) -> dict:
    """查询二维交叉热力图（如诊断×年龄段的热力分布）。
    适用于"热力图""热图""交叉表""诊断×年龄"等问法。"""
    return _dispatch_chart_hint("heatmap", dim1=dim1, dim2=dim2, metric=metric, top=top, filters=filters)


def _execute_region_diff(level: str = "service_area", metric: str = "count",
                         top: int = 20, filters: dict = None) -> dict:
    """查询地区分布差异（按服务区/区县/医院的排行）。
    适用于"地区差异""区域分布""各县""医院分布""地理分布"等问法。"""
    return _dispatch_chart_hint("region_diff", level=level, metric=metric, top=top, filters=filters)


def _execute_payment_composition(group: str = "payment1", metric: str = "count",
                                 filters: dict = None) -> dict:
    """查询支付方式构成（一级/二级/三级支付的分层构成）。
    适用于"支付构成""三层支付""一级支付""支付层级"等问法。"""
    return _dispatch_chart_hint("payment_composition", group=group, metric=metric, filters=filters)


def _execute_payment_cross(dim2: str = "age_group", metric: str = "count",
                           top: int = 15, filters: dict = None) -> dict:
    """查询支付方式与指定维度的交叉分析。
    适用于"支付×年龄""支付与病种""支付交叉""支付与严重程度"等问法。"""
    return _dispatch_chart_hint("payment_cross", dim2=dim2, metric=metric, top=top, filters=filters)


def _execute_sankey(levels: str = "payment,payment2", top_disease: int = 8,
                    filters: dict = None) -> dict:
    """查询支付流向桑基图（支付方式之间的资金流向）。
    适用于"桑基图""资金流向""支付链路""支付流向"等问法。"""
    return _dispatch_chart_hint("sankey", levels=levels, top_disease=top_disease, filters=filters)


def _execute_cost_relation(by: str = "payment", top: int = 30,
                           filters: dict = None) -> dict:
    """查询费用-成本关系散点图（费用与成本的对比关系）。
    适用于"费用关系""成本对比""费用散点图""成本费用"等问法。"""
    return _dispatch_chart_hint("cost_relation", by=by, top=top, filters=filters)


def _execute_cost_profit_difference(dimension: str = "drg", top: int = 20,
                                    year: int = 0, filters: dict = None) -> dict:
    """查询费用成本差(各维度下总费用减去总成本的差额排名)。
    适用于"费用成本差""成本差""收支差额""费用减成本"等问法。"""
    return _dispatch_chart_hint("profit_difference", dimension=dimension, top=top,
                                year=year, filters=filters)


def _execute_cost_profit_margin(dimension: str = "age_group", top: int = 20,
                                order: str = "desc", year: int = 0,
                                filters: dict = None) -> dict:
    """查询利润率(费用相对成本的比率，按维度排名)。
    适用于"利润率""利润""收费成本比""费用利润"等问法。"""
    return _dispatch_chart_hint("profit_margin", dimension=dimension, top=top,
                                order=order, year=year, filters=filters)


def _execute_cost_efficiency_ranking(dimension: str = "mdc", top: int = 30,
                                     year: int = 0, filters: dict = None) -> dict:
    """查询成本效益排行(按利润率分级 A/B/C/D 并给出依据)。
    适用于"成本效益""效益排行""效益排名""效益分级"等问法。"""
    return _dispatch_chart_hint("efficiency_ranking", dimension=dimension, top=top,
                                year=year, filters=filters)


def _execute_cost_composition(dimension: str = "mdc", top: int = 10,
                              year: int = 0, filters: dict = None) -> dict:
    """查询费用构成(各维度占总费用的比例)。
    适用于"费用构成""费用占比""费用组成""费用分布"等问法。"""
    return _dispatch_chart_hint("composition", dimension=dimension, top=top,
                                year=year, filters=filters)


def _execute_cost_trend(metric: str = "total_charges", start_year: int = 0,
                       end_year: int = 0, dimension: str = "",
                       dimension_value: str = "", filters: dict = None) -> dict:
    """查询费用年度趋势(按年份统计费用/成本/利润率，可指定维度拆分)。
    适用于"费用趋势""年度费用""费用走势""历年费用"等问法。"""
    return _dispatch_chart_hint("cost_trend", metric=metric, start_year=start_year,
                                end_year=end_year, dimension=dimension,
                                dimension_value=dimension_value, filters=filters)


def _execute_oop_burden(dimension: str = "disease", mode: str = "selfpay1",
                        top: int = 15, filters: dict = None) -> dict:
    """查询自付负担分析（患者自付费用负担程度）。
    适用于"自付""自费""自付负担""out of pocket"等问法。"""
    return _dispatch_chart_hint("oop_burden", dimension=dimension, mode=mode, top=top, filters=filters)


def _execute_payment_summary(filters: dict = None) -> dict:
    """查询KPI总览大屏（全量统计概览）。
    适用于"总览""大屏""KPI""概览""全量统计""整体情况"等问法。"""
    return _dispatch_chart_hint("payment_summary", filters=filters)


# 遗留路由工具（向后兼容）
def _execute_general_aggregate(dimension: str = "ccsr_diagnosis",
                               metric: str = "count", top: int = 10,
                               filters: dict = None) -> dict:
    """通用聚合分析：按指定维度和指标统计住院数据。
    适用于"各年龄段住院人数""按性别统计费用"等通用查询，
    当问题不匹配任何专用图表工具时使用。"""
    return _dispatch_legacy("/analysis/aggregate", 10,
                            dimension=dimension, metric=metric, top=top, filters=filters)


def _execute_payment_mix(filters: dict = None) -> dict:
    """查询支付方式占比分布。
    适用于"支付方式占比""医保分布""自费比例"等问法。"""
    return _dispatch_legacy("/analysis/payment-mix", 10, filters=filters)


def _execute_trend(filters: dict = None) -> dict:
    """查询历年住院数据趋势。
    适用于"历年趋势""逐年变化""时间走势"等问法。"""
    return _dispatch_legacy("/analysis/trend", 10, filters=filters)


# --- Section C2: 医疗质量监测工具（5 个，与 disease/payment/cost 同级的 StructuredTool）---
# 说明：quality 的 ROUTE_TABLE 条目、_build_quality_*_params 参数构造器、P3 /quality/* 端点、
# 摘要与图表 builder 此前已全部实现，唯独缺本段 StructuredTool 注册，导致 Agent 看不见这 5
# 个工具、质量类问题全部被误判 out_of_scope。此处补齐，使工具集完整覆盖 4 大分析模块。

class _QualityOverviewInput(BaseModel):
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _QualityMortalityInput(BaseModel):
    dimension: Literal["diagnosis", "facility", "age_group", "severity", "risk_mortality"] = Field(
        default="diagnosis",
        description="死亡率排行维度：diagnosis=疾病, facility=医院, age_group=年龄段, "
                    "severity=严重程度, risk_mortality=死亡风险分级")
    top: int = Field(default=20, ge=1, le=100, description="返回前N条，默认20，最大100")
    min_cases: int = Field(default=30, ge=1, le=10000, description="最小病例数阈值，默认30")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _QualityLosInput(BaseModel):
    dimension: Literal["diagnosis", "facility", "age_group", "severity", "risk_mortality"] = Field(
        default="diagnosis",
        description="平均住院日排行维度：diagnosis=疾病, facility=医院, age_group=年龄段, "
                    "severity=严重程度, risk_mortality=死亡风险分级")
    top: int = Field(default=20, ge=1, le=100, description="返回前N条，默认20，最大100")
    min_cases: int = Field(default=30, ge=1, le=10000, description="最小病例数阈值，默认30")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _QualityFacilityInput(BaseModel):
    top: int = Field(default=15, ge=1, le=100, description="返回前N条，默认15，最大100")
    min_cases: int = Field(default=100, ge=1, le=10000, description="最小病例数阈值，默认100")
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


class _QualityDispositionInput(BaseModel):
    filters: dict = Field(default_factory=dict, description=_FILTERS_DESC)


def _execute_quality_overview(filters: dict = None) -> dict:
    """查询医疗质量总览（KPI 大屏：死亡率、平均住院日、再入院率等全局指标）。
    适用于"医疗质量""质量总览""质量指标""质量概览"等问法。"""
    return _dispatch_chart_hint("quality_overview", filters=filters)


def _execute_quality_mortality(dimension: str = "diagnosis", top: int = 20,
                               min_cases: int = 30, filters: dict = None) -> dict:
    """查询住院死亡率排行（按指定维度统计死亡率，可限定最小病例数）。
    适用于"死亡率""死亡排行""死亡率最高""住院死亡"等问法。"""
    return _dispatch_chart_hint("quality_mortality", dimension=dimension, top=top,
                                min_cases=min_cases, filters=filters)


def _execute_quality_los(dimension: str = "diagnosis", top: int = 20,
                         min_cases: int = 30, filters: dict = None) -> dict:
    """查询平均住院日排行（按指定维度统计平均住院天数，可限定最小病例数）。
    适用于"平均住院日""住院天数""住院最久""住院日排行"等问法。"""
    return _dispatch_chart_hint("quality_los", dimension=dimension, top=top,
                                min_cases=min_cases, filters=filters)


def _execute_quality_facility(top: int = 15, min_cases: int = 100,
                              filters: dict = None) -> dict:
    """查询各医院质量对比排行（固定 facility 维度）。
    适用于"医院质量""哪家医院质量好""医院质量排名""质量对比"等问法。"""
    return _dispatch_chart_hint("quality_facility", top=top,
                                min_cases=min_cases, filters=filters)


def _execute_quality_disposition(filters: dict = None) -> dict:
    """查询出院结局/离院去向构成（全局饼图）。
    适用于"出院去向""离院去向""出院情况""出院构成"等问法。"""
    return _dispatch_chart_hint("quality_disposition", filters=filters)


# --- Section D: StructuredTool 列表 ---

if _LANGCHAIN_AVAILABLE:
    _TOOLS = [
        StructuredTool.from_function(
            _execute_top_diagnoses, name="top_diagnoses",
            description=(
                "查询住院患者疾病诊断排行(Top N)。适用于'常见疾病''高发疾病'"
                "'诊断排行''疾病top''什么病最多'等问法。"
                "返回疾病名称、编码和对应指标值。"),
            args_schema=_TopDiagnosesInput),
        StructuredTool.from_function(
            _execute_top_procedures, name="top_procedures",
            description=(
                "查询住院患者手术术式排行(Top N)。适用于'常见手术''高频手术'"
                "'手术排行''手术top'等问法。返回术式名称和指标值。"),
            args_schema=_TopProceduresInput),
        StructuredTool.from_function(
            _execute_severity_profile, name="severity_profile",
            description=(
                "查询病重程度构成(按指定维度分组的严重程度堆叠分布)。"
                "适用于'严重程度''病重分布''危重患者''堆叠图'等问法。"),
            args_schema=_SeverityProfileInput),
        StructuredTool.from_function(
            _execute_population_diff, name="population_diff",
            description=(
                "查询人群分布差异(按性别/种族/医疗外科分组的对比)。"
                "适用于'性别差异''年龄差异''种族差异''人群差异'等问法。"),
            args_schema=_PopulationDiffInput),
        StructuredTool.from_function(
            _execute_pyramid, name="pyramid",
            description=(
                "查询人口金字塔(按年龄段x性别的双侧金字塔图)。"
                "适用于'人口金字塔''性别年龄分布''金字塔图'等问法。"),
            args_schema=_PyramidInput),
        StructuredTool.from_function(
            _execute_heatmap, name="heatmap",
            description=(
                "查询二维交叉热力图(如诊断x年龄段的热力分布)。"
                "适用于'热力图''热图''交叉表''诊断x年龄'等问法。"),
            args_schema=_HeatmapInput),
        StructuredTool.from_function(
            _execute_region_diff, name="region_diff",
            description=(
                "查询地区分布差异(按服务区/区县/医院的排行)。"
                "适用于'地区差异''区域分布''各县''医院分布''地理分布'等问法。"),
            args_schema=_RegionDiffInput),
        StructuredTool.from_function(
            _execute_payment_composition, name="payment_composition",
            description=(
                "查询支付方式构成/占比(一级/二级/三级支付的分层构成)。"
                "适用于'支付构成''支付方式占比''占比''比例''三层支付''一级支付''支付层级'等问法。"),
            args_schema=_PaymentCompositionInput),
        StructuredTool.from_function(
            _execute_payment_cross, name="payment_cross",
            description=(
                "查询支付方式与指定维度(年龄/诊断/严重程度)的交叉分析。"
                "适用于'支付x年龄''支付与病种''支付交叉''支付与严重程度'等问法。"),
            args_schema=_PaymentCrossInput),
        StructuredTool.from_function(
            _execute_sankey, name="sankey",
            description=(
                "查询支付流向桑基图(支付方式之间的资金流向)。"
                "适用于'桑基图''资金流向''支付链路''支付流向'等问法。"),
            args_schema=_SankeyInput),
        StructuredTool.from_function(
            _execute_cost_relation, name="cost_relation",
            description=(
                "查询费用-成本关系散点图(费用与成本的对比关系)。"
                "适用于'费用关系''成本对比''费用散点图''成本费用'等问法。"),
            args_schema=_CostRelationInput),
        StructuredTool.from_function(
            _execute_cost_profit_difference, name="profit_difference",
            description=(
                "查询费用成本差(各维度下总费用减去总成本的差额排名)。"
                "适用于'费用成本差''成本差''收支差额''费用减成本'等问法。"),
            args_schema=_CostProfitDifferenceInput),
        StructuredTool.from_function(
            _execute_cost_profit_margin, name="profit_margin",
            description=(
                "查询利润率(费用相对成本的比率，按维度排名，可升降序)。"
                "适用于'利润率''利润''收费成本比''费用利润'等问法。"),
            args_schema=_CostProfitMarginInput),
        StructuredTool.from_function(
            _execute_cost_efficiency_ranking, name="efficiency_ranking",
            description=(
                "查询成本效益排行(按利润率分级 A/B/C/D 并给出依据)。"
                "适用于'成本效益''效益排行''效益排名''效益分级'等问法。"),
            args_schema=_CostEfficiencyRankingInput),
        StructuredTool.from_function(
            _execute_cost_composition, name="composition",
            description=(
                "查询费用构成(各维度占总费用的比例)。"
                "适用于'费用构成''费用占比''费用组成''费用分布'等问法。"),
            args_schema=_CostCompositionInput),
        StructuredTool.from_function(
            _execute_cost_trend, name="cost_trend",
            description=(
                "查询费用年度趋势(按年份统计费用/成本/利润率，可指定维度拆分)。"
                "适用于'费用趋势''费用变化趋势''近几年费用变化''年度费用''费用走势''历年费用'等问法。"
                "无需用户给出具体年份，未指定时按全部年份返回。"),
            args_schema=_CostTrendInput),
        StructuredTool.from_function(
            _execute_oop_burden, name="oop_burden",
            description=(
                "查询自付负担分析(患者自付费用负担程度)。"
                "适用于'自付''自费''自付负担''out of pocket'等问法。"),
            args_schema=_OopBurdenInput),
        StructuredTool.from_function(
            _execute_payment_summary, name="payment_summary",
            description=(
                "查询KPI总览大屏(全量统计概览)。"
                "适用于'总览''大屏''KPI''概览''全量统计''整体情况'等问法。"),
            args_schema=_PaymentSummaryInput),
        # 遗留路由工具（仅保留真正兜底的 general_aggregate）
        # 注：payment_mix / trend 已从 Agent 工具集移除——它们与 payment_composition / cost_trend
        # 功能重叠且 chart_hint 恒为 None（前端无图表），曾导致"占比/趋势"类问题被路由到旧接口。
        # 旧 pipeline（parse_intent 规则 + _dispatch_legacy）仍保留这两个能力，仅 Agent 不再暴露。
        StructuredTool.from_function(
            _execute_general_aggregate, name="general_aggregate",
            description=(
                "通用聚合分析:按指定维度和指标统计住院数据。"
                "当问题不匹配任何专用图表工具时使用,如'各年龄段住院人数''按性别统计费用'。"),
            args_schema=_GeneralAggregateInput),
        # 医疗质量监测（5 个，/api/v1/quality/*）
        StructuredTool.from_function(
            _execute_quality_overview, name="quality_overview",
            description=(
                "查询医疗质量总览(KPI大屏:死亡率/平均住院日/再入院率等全局指标)。"
                "适用于'医疗质量''质量总览''质量指标''质量概览'等问法。"),
            args_schema=_QualityOverviewInput),
        StructuredTool.from_function(
            _execute_quality_mortality, name="quality_mortality",
            description=(
                "查询住院死亡率排行(按疾病/医院/年龄段等维度统计死亡率)。"
                "适用于'死亡率''死亡排行''死亡率最高''住院死亡'等问法。"),
            args_schema=_QualityMortalityInput),
        StructuredTool.from_function(
            _execute_quality_los, name="quality_los",
            description=(
                "查询平均住院日排行(按疾病/医院/年龄段等维度统计平均住院天数)。"
                "适用于'平均住院日''住院天数''住院最久''住院日排行'等问法。"),
            args_schema=_QualityLosInput),
        StructuredTool.from_function(
            _execute_quality_facility, name="quality_facility",
            description=(
                "查询各医院质量对比排行(固定医院维度)。"
                "适用于'医院质量''哪家医院质量好''医院质量排名''质量对比'等问法。"),
            args_schema=_QualityFacilityInput),
        StructuredTool.from_function(
            _execute_quality_disposition, name="quality_disposition",
            description=(
                "查询出院结局/离院去向构成(全局饼图)。"
                "适用于'出院去向''离院去向''出院情况''出院构成'等问法。"),
            args_schema=_QualityDispositionInput),
    ]
else:
    _TOOLS = []


# --- Section D2: 推荐问法注册表（单一来源） ---
# 覆盖全部 21 个工具，前端 /api/suggested-questions 与 Agent 系统提示词 few-shot 共用。
# 新增工具时只需在此追加一行，前端与 Agent 提示词会自动同步。
SUGGESTED_QUESTIONS: list[dict] = [
    # —— 疾病诊断类 ——
    {"tool": "top_diagnoses", "category": "疾病诊断",
     "question": "2021年最常见的5种住院疾病是哪些？"},
    {"tool": "top_diagnoses", "category": "疾病诊断",
     "question": "高发疾病排名前10的是哪些？"},
    {"tool": "top_procedures", "category": "疾病诊断",
     "question": "住院患者做的最多的手术术式排行是什么？"},
    {"tool": "severity_profile", "category": "疾病诊断",
     "question": "不同年龄段的病重程度分布是怎样的？"},
    {"tool": "population_diff", "category": "疾病诊断",
     "question": "男性和女性患者的住院人数差异大吗？"},
    {"tool": "pyramid", "category": "疾病诊断",
     "question": "住院患者的人口金字塔分布长什么样？"},
    {"tool": "region_diff", "category": "疾病诊断",
     "question": "各个区县的患者数量排名如何？"},
    {"tool": "heatmap", "category": "疾病诊断",
     "question": "不同诊断在各年龄段的分布热力图？"},
    # —— 支付与费用类 ——
    {"tool": "payment_composition", "category": "支付与费用",
     "question": "住院费用的一级支付方式构成比例是多少？"},
    {"tool": "payment_cross", "category": "支付与费用",
     "question": "不同支付方式在年龄段上的交叉分布如何？"},
    {"tool": "sankey", "category": "支付与费用",
     "question": "医保到自付的资金流向桑基图怎么看？"},
    {"tool": "cost_relation", "category": "支付与费用",
     "question": "住院费用和成本之间有什么关系？"},
    {"tool": "oop_burden", "category": "支付与费用",
     "question": "不同疾病的自付负担情况如何？"},
    {"tool": "payment_summary", "category": "支付与费用",
     "question": "给我一个整体的KPI总览大屏"},
    # —— 费用成本分析（对接 /cost/*）——
    {"tool": "profit_difference", "category": "费用成本",
     "question": "不同支付方式的费用成本差是多少？"},
    {"tool": "profit_margin", "category": "费用成本",
     "question": "各年龄段的利润率是多少？"},
    {"tool": "efficiency_ranking", "category": "费用成本",
     "question": "哪些病种的住院成本效益最高？"},
    {"tool": "composition", "category": "费用成本",
     "question": "住院费用按医院是怎么构成的？"},
    {"tool": "cost_trend", "category": "费用成本",
     "question": "近年的住院总费用趋势如何？"},
    # —— 通用分析类 ——
    {"tool": "general_aggregate", "category": "通用分析",
     "question": "各年龄段住院人数分别是多少？"},
    {"tool": "payment_composition", "category": "通用分析",
     "question": "各种支付方式的占比分布是怎样的？"},
    {"tool": "cost_trend", "category": "通用分析",
     "question": "近几年的住院费用趋势如何变化？"},
]


def _build_suggested_examples() -> str:
    """把 SUGGESTED_QUESTIONS 渲染成 Agent 系统提示词的 few-shot 示例段。"""
    lines = ["\n== 示例问法（参考，帮助选择工具）=="]
    for item in SUGGESTED_QUESTIONS:
        lines.append(f"- 「{item['question']}」→ 调用 {item['tool']}")
    lines.append(
        "\n注意：以上仅为问法示例，请依据用户实际问题的语义选择工具，"
        "不要照搬示例中的字面措辞。")
    return "\n".join(lines) + "\n"


# --- Section E: Agent 系统提示词 ---

_AGENT_SYSTEM_PROMPT = """\
你是智慧医疗大数据分析平台的AI助手。你的任务：理解用户的自然语言问题，\
选择最合适的分析工具调用，然后基于返回的数据生成专业、准确的中文摘要。

== 可用工具及适用场景 ==

1. top_diagnoses — 疾病诊断排行。"常见疾病""高发疾病""诊断排行""疾病top""什么病最多"
2. top_procedures — 手术术式排行。"常见手术""高频手术""手术排行""手术top"
3. severity_profile — 病重程度构成。"严重程度""病重分布""危重患者""堆叠图"
4. population_diff — 人群分布差异。"性别差异""年龄差异""种族差异""人群差异"
5. pyramid — 人口金字塔。"人口金字塔""性别年龄分布""金字塔图"
6. region_diff — 地区分布。"地区差异""区域分布""各县""医院分布""地理分布"
7. heatmap — 热力图。"热力图""热图""交叉表""诊断×年龄"
8. payment_composition — 支付构成/占比。"支付构成""支付方式占比""占比""比例""三层支付""支付层级"
9. payment_cross — 支付交叉。"支付×年龄""支付与病种""支付交叉""支付与严重程度"
10. sankey — 桑基图。"桑基图""资金流向""支付链路""支付流向"
11. cost_relation — 费用关系。"费用关系""成本对比""费用散点图""成本费用"
12. oop_burden — 自付负担。"自付""自费""自付负担""out of pocket"
13. payment_summary — KPI总览。"总览""大屏""KPI""概览""全量统计""整体情况"
14. general_aggregate — 通用聚合。当问题不匹配以上任何专用工具时使用，\
如"各年龄段住院人数""按性别统计费用"
15. quality_overview — 医疗质量总览。"医疗质量""质量总览""质量指标""质量概览"
16. quality_mortality — 死亡率排行。"死亡率""死亡排行""死亡率最高""住院死亡"
17. quality_los — 平均住院日。"平均住院日""住院天数""住院最久""住院日排行"
18. quality_facility — 医院质量对比。"医院质量""哪家医院质量好""医院质量排名""质量对比"
19. quality_disposition — 离院去向。"出院去向""离院去向""出院情况""出院构成"

== 筛选条件(filters)可用字段 ==
- year: 年份(整数)，如 2021
- gender: 性别，"M"=男性，"F"=女性
- age_group: 年龄段，如"70 or Older""0 to 17""18 to 29""30 to 49""50 to 69"
- payment / payment2 / payment3: 支付方式编码
- severity: 严重程度，"Minor"/"Moderate"/"Major"/"Extreme"
- diagnosis: 疾病诊断编码(CCSR)
- procedure: 手术术式编码
- service_area / county / facility: 服务区 / 区县 / 医院

== 多轮对话规则 ==
- 如果用户在追问（如"那费用呢""换个性别看"），从历史中继承未明确改变的筛选条件
- 如果用户明确指定了新筛选条件，覆盖历史的对应字段
- 用户说"男性"→gender="M"；"女性"→gender="F"
- 用户说"70岁以上"→age_group="70 or Older"；"儿童"→"0 to 17"

== 非数据分析问题处理（重要）==
- 本平台只回答「医院住院患者出院数据」的分析问题，且必须能映射到上述任一可用分析工具
  （疾病、手术、费用、支付方式、医疗质量、人群/地区分布、历年趋势等）。
- 以下类型【严禁调用任何工具】，也不要编造数据，直接礼貌回复：
  "抱歉，本平台仅支持住院数据的统计分析，暂不支持此类医学咨询/服务问题。
   您可以尝试询问某疾病的住院量、费用、趋势或人群分布等数据分析问题。"
  · 疾病诊疗建议 / 用药指导（如"感冒了该怎么办""吃什么药""挂什么科"）
  · 预后判断（如"严重吗""会死吗""需要手术吗"）
  · 开药/诊断（如"帮我开个药""给我诊断一下"）
  · 医学知识科普（如"XX病是什么意思""怎么预防"）
  · 医院流程（如"怎么挂号""门诊时间""医院地址"）
  · 医保政策（如"报销比例""医保政策""起付线"）
- 判断标准：问题是否可被映射为某个工具的「筛选条件 + 聚合维度」查询。
  若完全无法映射，就不要调用工具，按上面话术直接回复（此时不调用工具是正确的）。
- 反之，只要用户问题属于「住院数据分析」且能映射到上述任一可用工具，你就【必须
  调用对应的那一个工具】来获取真实数据，绝不能用纯文本臆测回答；每次只调用一个最贴切的工具。

== 多轮对话中的工具选择（重要）==
- 即使存在多轮对话历史，当前问题也必须【独立判断】是否属于数据分析问题，并独立选择
  最贴切的工具——每一轮都是独立的数据分析请求。
- 换话题时（如上一轮聊疾病排行，这一轮问费用构成/桑基图/交叉热力图/医疗质量），
  【必须】调用对应的新工具，绝不能因为"延续上轮话题"而不调工具或用错工具。
- 历史中的问题与回答只是背景参考，工具调用依据永远以【当前这个问题】为准。

== 输出要求 ==
1. 每次只调用一个工具
2. 根据用户问题选择最贴切的工具，不要随意选
3. 工具调用后，基于返回的数据生成150-300字的中文摘要
4. 摘要要突出核心数字：总样本量、Top1/Top2/Top3的数值和对比
5. 摘要结尾给出1-2条业务层面的观察或建议
6. 禁止编造或修改数据中的任何数字
7. 摘要最多使用2个emoji（📊 📈 💡 🏥）
8. 摘要分2-3段，每段一句话一个意思

== 工具调用示范（务必以标准工具调用格式返回，不要只把工具名写在文本里）==
- "2021年住院量最高的疾病有哪些" → 调用 top_diagnoses(filters={"year":2021}, metric="count", top=10)
- "哪种病看得最多排名前10"       → 调用 top_diagnoses(metric="count", top=10)
- "2021年做得最多的手术操作是什么" → 调用 top_procedures(filters={"year":2021}, metric="count", top=10)
- "排名前5的手术有哪些"          → 调用 top_procedures(metric="count", top=5)
- "住院患者的严重程度分布"        → 调用 severity_profile()
- "男女住院人数差异"             → 调用 population_diff(dimension="gender")
- "感冒了该怎么办"               → 不调用任何工具，直接按上方拒答话术回复
- "医疗质量总体情况"             → 调用 quality_overview()
- "死亡率最高的病种"             → 调用 quality_mortality(dimension="diagnosis", top=10)
- "哪些病住院最久"               → 调用 quality_los(dimension="diagnosis", top=10)
- "哪家医院质量最好"             → 调用 quality_facility(top=10)
- "出院情况构成"                 → 调用 quality_disposition()
- "各年龄段糖尿病住院人数"       → 调用 top_diagnoses(filters={"diagnosis":"糖尿病相关CCSR编码"}, top=20)
- "城镇职工医保的支付占比"       → 调用 payment_composition(group="payment1")
- "近几年住院费用变化趋势"       → 调用 cost_trend(metric="total_charges")
- "不同支付方式的年度变化"       → 调用 payment_cross(dim2="age_group")
- "去年和今年呼吸道疾病住院量对比" → 调用 top_diagnoses(filters={"diagnosis":"呼吸道疾病CCSR"}, top=20)
注意：能用工具回答的问题【必须】通过工具调用返回，而不是在文本里描述"应该查XX"。

== 带具体取值/模糊表述也要调工具（重要）==
- 用户提到【具体取值】(如"糖尿病""城镇职工医保""呼吸道疾病""2021年")时，仍调用对应的
  排行/构成工具，并通过 filters 传入该取值；绝不能因为问题带了具体值就放弃调用工具。
- 支付方式"构成""分层""一级/二级/三级"或"占比/比例" → payment_composition（占比类问题一律用它）。
- "近几年""历年""年度变化""趋势"无需用户给出具体年份，直接调用 cost_trend / payment_cross
  （按全部年份返回）；"不同XX的年度变化"通常指该维度与年份的交叉，用 payment_cross / cost_relation。
"""

# 注入 few-shot 示例（来自 SUGGESTED_QUESTIONS 单一来源），提升路由准确率
_AGENT_SYSTEM_PROMPT += _build_suggested_examples()


# --- Section F: Agent 创建（懒加载） ---

_AGENT_EXECUTOR = None  # AgentExecutor (0.2.x) | CompiledStateGraph (1.x) | None


def _get_agent_executor():
    """懒加载创建 Agent 执行器（兼容 langchain 0.2.x 和 1.x）。
    LLM 未启用 / LangChain 未安装 / 工具列表为空时返回 None（调用方降级到旧 pipeline）。
    """
    global _AGENT_EXECUTOR
    if _AGENT_EXECUTOR is not None:
        return _AGENT_EXECUTOR
    if not _LANGCHAIN_AVAILABLE or not LLM_ENABLED or not _TOOLS:
        return None

    try:
        llm = ChatOpenAI(
            model=LLM_MODEL_ID_AGENT,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            temperature=LLM_TEMPERATURE,
            timeout=LLM_TIMEOUT,
        )

        if _LC_AGENT_API == "v1x":
            # langchain 1.x: create_agent 返回 CompiledStateGraph
            # system_prompt 直接传字符串，不需要 ChatPromptTemplate
            _AGENT_EXECUTOR = _lc_create_agent(
                model=llm,
                tools=_TOOLS,
                system_prompt=_AGENT_SYSTEM_PROMPT,
            )
            logger.info("[Agent] LangChain 1.x create_agent 就绪（model=%s, tools=%d）",
                        LLM_MODEL_ID_AGENT, len(_TOOLS))
        else:
            # langchain 0.2.x: create_tool_calling_agent + AgentExecutor
            prompt = ChatPromptTemplate.from_messages([
                ("system", _AGENT_SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            agent = create_tool_calling_agent(llm, _TOOLS, prompt)
            _AGENT_EXECUTOR = AgentExecutor(
                agent=agent,
                tools=_TOOLS,
                max_iterations=3,
                return_intermediate_steps=True,
                handle_parsing_errors=True,
                verbose=os.getenv("AGENT_VERBOSE", "0").lower()
                           in ("1", "true", "yes", "on"),
            )
            logger.info("[Agent] LangChain 0.2.x AgentExecutor 就绪（model=%s, tools=%d）",
                        LLM_MODEL_ID_AGENT, len(_TOOLS))
        return _AGENT_EXECUTOR
    except Exception as e:
        logger.warning("[Agent] 创建 Agent 执行器失败，将降级到旧 pipeline：%s", e)
        return None


# --- Section G: 工具调用信息提取 + intent 重建 ---

_VALID_TOOL_NAMES = set()  # 在 _TOOLS 创建后填充


def _init_valid_tool_names():
    """初始化合法工具名集合（在 _TOOLS 创建后调用）。"""
    global _VALID_TOOL_NAMES
    if not _VALID_TOOL_NAMES:
        _VALID_TOOL_NAMES = set(ROUTE_TABLE.keys()) | {"general_aggregate"}


def _normalize_tool_name(raw: str):
    """把工具名归一到合法名（ROUTE_TABLE 键）。

    用于工具调用提取：模型选中的工具名可能因为注册时多了模块前缀
    （如 'cost_profit_difference' vs ROUTE_TABLE 键 'profit_difference'）
    而和 _VALID_TOOL_NAMES 对不上，导致明明命中却被当成“无效工具调用”降级。
    这里在拒绝前先尝试去前缀归一并校验，避免误降级。
    """
    if not raw:
        return None
    _init_valid_tool_names()
    if raw in _VALID_TOOL_NAMES:
        return raw
    # 去已知模块前缀后再次校验（如 cost_/payment_/disease_）。
    stripped = raw
    for prefix in ("cost_", "payment_", "disease_", "analysis_"):
        if raw.startswith(prefix):
            stripped = raw[len(prefix):]
            break
    if stripped in _VALID_TOOL_NAMES:
        return stripped
    return None


def _parse_observation(observation) -> dict:
    """把工具返回值（可能是 dict / str）统一解析为 dict。"""
    if isinstance(observation, dict):
        return observation
    if isinstance(observation, str):
        try:
            return json.loads(observation)
        except json.JSONDecodeError:
            try:
                import ast
                return ast.literal_eval(observation)
            except Exception:
                return {}
    return {}


def _extract_tool_call_from_steps(steps: list) -> tuple[str, dict, dict] | None:
    """从 langchain 0.2.x AgentExecutor 的 intermediate_steps 中提取最后一次有效工具调用。

    返回 (tool_name, tool_args, api_result) 或 None（无有效调用）。
    """
    _init_valid_tool_names()
    for action, observation in reversed(steps):
        raw_name = getattr(action, "tool", "")
        tool_name = _normalize_tool_name(raw_name)
        if not tool_name:
            continue
        tool_input = getattr(action, "tool_input", {})
        if not isinstance(tool_input, dict):
            try:
                tool_input = json.loads(tool_input) if isinstance(tool_input, str) else {}
            except (json.JSONDecodeError, TypeError):
                tool_input = {}

        api_result = _parse_observation(observation)
        if "error" not in api_result:
            return tool_name, tool_input, api_result
    return None


def _extract_tool_call_from_text(text: str, loose: bool = True):
    """从模型自由文本中兜底提取工具调用 JSON。

    背景：SiliconFlow 的 Qwen 偶发不返回标准 tool_calls，而是把工具调用写进
    回复文本（如 '{"name": "profit_difference", "args": {...}}' 或
    'Action: profit_difference\\nAction Input: {...}'）。
    此函数用正则从文本中提取 (tool_name, tool_args)，供提取层兜底。
    """
    if not text:
        return None
    import re as _re
    # 模式1: {"name": "xxx", "args": {...}} 或 {"name": "xxx", "arguments": {...}}
    # 注意匹配 arguments 用 "args?(?:uments)?"（args / argument / arguments）
    m = _re.search(r'"name"\s*:\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*,\s*"args?(?:uments)?"\s*:\s*(\{.*?\})',
                   text, _re.DOTALL)
    # 模式2: Action: xxx / Action Input: {...}（ReAct 风格）
    if not m:
        m = _re.search(r'Action\s*:\s*([A-Za-z_][A-Za-z0-9_]*)[\s\S]{0,200}?Action\s*Input\s*:\s*(\{.*?\})',
                       text, _re.DOTALL)
    if m:
        tool_name = _normalize_tool_name(m.group(1))
        if not tool_name:
            return None
        try:
            args = json.loads(m.group(2))
            if not isinstance(args, dict):
                args = {}
        except (json.JSONDecodeError, ValueError):
            args = {}
        return tool_name, args
    # 模式3: 带参数调用形式，如 “调用 profit_difference(dimension=...)”
    m = _re.search(r'([A-Za-z_][A-Za-z0-9_]*)\s*\(', text)
    if m:
        tool_name = _normalize_tool_name(m.group(1))
        if tool_name:
            return tool_name, {}
    # 模式4: 文本中直接出现合法工具名（SiliconFlow 乱码时模型常写
    # “使用 profit_difference 工具查询”这类自然句），最长匹配优先
    # 仅 loose 模式启用：原生 tool-calling 场景下此模式易误触发（拒答文本出现工具名）
    if loose:
        for name in sorted(_VALID_TOOL_NAMES, key=len, reverse=True):
            if name in text:
                return name, {}
    return None


# 带拒答守卫的自然语言工具名识别（原生 tool-calling 路径用）。
# 背景：SiliconFlow 的模型偶发不在 tool_calls 返回调用，而只在 content 里写
# "可以调用 top_diagnoses 工具查询" 这类自然语言。此函数作为最后兜底，
# 仅当文本含「调用/使用/查询/分析/用 + 合法工具名」且无明显拒答语义时命中，
# 既抓住"模型理解了但没走标准格式"的情况，又避免拒答文本误触发工具调用。
_REFUSAL_MARKERS = ("不支持", "暂不支持", "无法", "不能", "不提供",
                    "不是数据分析", "不属于", "医学咨询", "诊疗建议",
                    "无法回答", "没有对应工具", "无法为您提供")


def _extract_tool_call_from_text_guarded(text: str):
    """先走严格 JSON/Action/`x()` 解析；再走带守卫的自然语言兜底。

    用于原生 tool-calling 路径：当模型返回 200 但 tool_calls 为空、只在
    文本里用自然语言提到工具名时，仍能抓住意图，避免无意义的重试空转。
    """
    parsed = _extract_tool_call_from_text(text, loose=False)
    if parsed:
        return parsed
    if not text:
        return None
    # 拒答语义明显时不强行解析工具名（保护 out_of_scope 判定）
    if any(marker in text for marker in _REFUSAL_MARKERS):
        return None
    import re as _re
    m = _re.search(
        r'(?:调用|使用|查询|分析|选用|用)\s*[“"\']?'
        r'([A-Za-z_][A-Za-z0-9_]*)\s*[”"\']?', text)
    if m:
        name = _normalize_tool_name(m.group(1))
        if name:
            return name, {}
    return None


def _invoke_tool_by_name(tool_name: str, tool_args: dict):
    """按名称在 _TOOLS 中查找并执行工具（文本兜底用），返回 api_result 或 None。

    StructuredTool.invoke 会走 Pydantic 参数校验；args 不完整时先按原参试一次，
    失败则退化为默认参数再试，仍失败返回 None（调用方继续降级）。
    """
    for t in _TOOLS:
        if getattr(t, "name", None) != tool_name:
            continue
        try:
            result = t.invoke(tool_args or {})
        except Exception:
            try:
                result = t.invoke({})
            except Exception as e:
                logger.warning("[Agent] 文本兜底工具 %s 执行失败：%s", tool_name, e)
                return None
        return result if isinstance(result, dict) else None
    return None


def _extract_tool_call_from_messages(messages: list) -> tuple[str, dict, dict] | None:
    """从 langchain 1.x create_agent 的 messages 列表中提取最后一次有效工具调用。

    1.x 的结果格式: {"messages": [HumanMessage, AIMessage(tool_calls), ToolMessage, AIMessage(final)]}
    返回 (tool_name, tool_args, api_result) 或 None。
    """
    _init_valid_tool_names()

    # 第一步：从后往前找最后一个有 tool_calls 的 AIMessage
    last_tool_name = None
    last_tool_args = {}
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                tc_name = tc.get("name", "") if isinstance(tc, dict) else ""
                norm = _normalize_tool_name(tc_name)
                if norm:
                    last_tool_name = norm
                    last_tool_args = tc.get("args", {}) if isinstance(tc, dict) else {}
                    break
            if last_tool_name:
                break

    if not last_tool_name:
        # 第二步兜底：模型把工具调用写进了文本而非标准 tool_calls
        # （SiliconFlow Qwen 常见），从 AIMessage 文本里提取并真实执行工具。
        for msg in reversed(messages):
            if not isinstance(msg, AIMessage):
                continue
            content = str(getattr(msg, "content", "") or "")
            parsed = _extract_tool_call_from_text(content)
            if parsed is None:
                continue
            tname, targs = parsed
            api_result = _invoke_tool_by_name(tname, targs)
            if api_result is not None and "error" not in api_result:
                logger.info("[Agent] 文本兜底解析到工具调用 %s（args=%s）",
                            tname, json.dumps(targs, ensure_ascii=False)[:200])
                return tname, targs, api_result
        return None

    # 第三步：从后往前找对应的 ToolMessage（工具输出）
    for msg in reversed(messages):
        msg_type = getattr(msg, "type", "")
        if msg_type == "tool" or isinstance(msg, ToolMessage):
            api_result = _parse_observation(getattr(msg, "content", ""))
            if "error" not in api_result:
                return last_tool_name, last_tool_args, api_result

    return None


def _reconstruct_intent(tool_name: str, args: dict) -> dict:
    """从工具名和参数重建 intent dict（供下游 generate_text_summary /
    generate_chart_config 使用，确保与旧 pipeline 产出格式一致）。"""
    # intent 基础模板（包含所有 _parse_intent_by_rules 产出的字段）
    base = {
        "chart_hint": None, "dimension": None, "metric": None,
        "filters": args.get("filters") or {}, "top": None,
        "by": None, "dim1": None, "dim2": None,
        "group": None, "levels": None, "level": None, "mode": None,
    }

    if tool_name in ROUTE_TABLE:
        # chart_hint 工具：把工具参数映射回 intent 字段
        base["chart_hint"] = tool_name
        # 通用字段透传
        for k in ("metric", "top", "filters", "by", "dim1", "dim2",
                  "group", "levels", "level", "mode", "dimension", "min_cases"):
            if k in args:
                base[k] = args[k]
        # population_diff 的 dimension → by（_build_population_diff_params 用 by）
        if "dimension" in args and tool_name == "population_diff":
            base["by"] = args["dimension"]
        # oop_burden 的 dimension 保留
        if "dimension" in args and tool_name == "oop_burden":
            base["dimension"] = args["dimension"]
        # region_diff 的 level 保留
        if tool_name == "region_diff":
            base["level"] = args.get("level")
        # sankey 的 top_disease 保留（非 intent 标准字段，但无害）
    elif tool_name == "general_aggregate":
        base["dimension"] = args.get("dimension", "ccsr_diagnosis")
        base["metric"] = args.get("metric", "count")
        base["top"] = args.get("top", 10)
    elif tool_name == "payment_mix":
        base["dimension"] = "payment_typology"
        base["metric"] = "payment_mix"
        base["top"] = 10
    elif tool_name == "trend":
        base["dimension"] = "discharge_year"
        base["metric"] = "trend"
        base["top"] = 10

    return base


# --- Section H: Agent 驱动的 handle_question ---

# 原生 tool-calling LLM（版本无关：直接 ChatOpenAI.bind_tools + 解析 resp.tool_calls）
# 规避 langchain 1.x create_agent 的 ReAct 提示词对 Qwen2.5-72B 的干扰。
_TOOL_CALLING_LLM = None


def _get_tool_calling_llm():
    """懒加载原生 tool-calling LLM（ChatOpenAI.bind_tools(_TOOLS)）。

    返回绑定了工具的 ChatOpenAI 实例；不可用时返回 None（调用方回退到
    langchain agent 封装 / 旧 pipeline）。temperature 固定为 0，最大化工具
    调用确定性（工具调用不应带随机性）。
    """
    global _TOOL_CALLING_LLM
    if _TOOL_CALLING_LLM is not None:
        return _TOOL_CALLING_LLM
    if not _LANGCHAIN_AVAILABLE or not LLM_ENABLED or not _TOOLS:
        return None
    try:
        llm = ChatOpenAI(
            model=LLM_MODEL_ID_AGENT,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            temperature=float(os.getenv("LLM_TEMPERATURE_TOOL", "0")),
            timeout=LLM_TIMEOUT,
        )
        _TOOL_CALLING_LLM = llm.bind_tools(_TOOLS)
        logger.info("[Agent] 原生 tool-calling LLM 就绪（model=%s, tools=%d, temperature=0）",
                    LLM_MODEL_ID_AGENT, len(_TOOLS))
        return _TOOL_CALLING_LLM
    except Exception as e:
        logger.warning("[Agent] 创建原生 tool-calling LLM 失败，将回退到 langchain agent 封装：%s", e)
        return None


def _build_agent_chat_history(history) -> list:
    """把会话历史拼成 LangChain 消息列表（Human/AIMessage 交替）。

    只取最近 AGENT_HISTORY_TURNS 轮：历史过长会淹没工具选择判断
    （实测多轮后模型开始 no-tool 误判 out_of_scope）；追问补参由规则引擎负责。
    """
    chat_history = []
    if history:
        for turn in history[-AGENT_HISTORY_TURNS:]:
            chat_history.append(HumanMessage(content=turn.get("question", "")))
            chat_history.append(AIMessage(content=(turn.get("answer") or "")[:300]))
    return chat_history


def _assemble_agent_result(tool_name, tool_args, api_result, agent_text_output,
                           question, with_report, conversation_id, history,
                           stream_callback=None):
    """从(工具名, 参数, 工具结果)组装最终 result dict（executor 与原生路径共用）。"""
    _log_event("agent_invoked", tool=tool_name,
               args_keys=list(tool_args.keys()) if isinstance(tool_args, dict) else None)
    # 重建 intent（供下游 generate_text_summary / generate_chart_config 使用）
    intent = _reconstruct_intent(tool_name, tool_args)
    intent["_source"] = "langchain_agent"
    intent["_reasoning"] = (
        f"LangChain agent selected tool: {tool_name}"
        + (f" with args: {json.dumps(tool_args, ensure_ascii=False)[:200]}"
           if tool_args else ""))
    # 收尾（摘要/图表/组装/warnings/会话历史/报告）与旧 pipeline 共用，保证输出一致
    return _finalize_result(
        question, intent, api_result,
        with_report=with_report,
        conversation_id=conversation_id,
        history=history,
        extra_meta={"agent_output": agent_text_output},
        stream_callback=stream_callback,
    )


def _run_native_tool_calling(question, with_report, conversation_id, llm,
                             stream_callback=None):
    """版本无关的原生 tool-calling 循环。

    直接 llm.bind_tools 调用 → 解析 resp.tool_calls → 执行工具 → 组装。
    仅「硬异常(invoke 失败)」返回 None（调用方降级旧 pipeline）；
    「未提取到有效工具调用」视为非数据分析问题 → 返回 out_of_scope result。
    """
    history = MEMORY.get_history(conversation_id)
    chat_history = _build_agent_chat_history(history)
    messages = [SystemMessage(content=_AGENT_SYSTEM_PROMPT)] + chat_history + [
        HumanMessage(content=question)]
    agent_text_output = ""

    # 重试策略：仅对「硬异常(invoke 失败)」重试（瞬时的 429/超时/网络抖动可能恢复）；
    # 「未提取到有效工具调用」是确定性决策（temperature=0 下重复调用结果一致），
    # 不重试，立即判定为非数据分析问题，避免白白烧钱 + 拖慢响应。
    last_exc = None
    for attempt in range(1 + AGENT_TOOL_RETRIES):
        try:
            resp = llm.invoke(messages)
        except Exception as e:
            last_exc = e
            logger.warning("[Agent] 原生 tool-calling 第 %d/%d 次调用异常，重试：%s",
                           attempt + 1, 1 + AGENT_TOOL_RETRIES, e)
            continue  # 硬异常 → 重试

        # 1) 标准 tool_calls（OpenAI 格式，SiliconFlow Qwen2.5 支持）
        tool_calls = getattr(resp, "tool_calls", None) or []
        picked = None
        for tc in tool_calls:
            raw_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            name = _normalize_tool_name(raw_name)
            if name:
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}) or {}
                if not isinstance(args, dict):
                    args = {}
                picked = (name, args)
                break
        if picked:
            name, args = picked
            _emit_stage(stream_callback, "querying")
            api_result = _invoke_tool_by_name(name, args)
            agent_text_output = str(getattr(resp, "content", "") or "")[:500]
            return _assemble_agent_result(name, args, api_result, agent_text_output,
                                          question, with_report, conversation_id, history,
                                          stream_callback=stream_callback)

        # 2) 文本兜底（SiliconFlow 模型偶发把调用写进 content，而非标准 tool_calls）
        text = str(getattr(resp, "content", "") or "")
        parsed = _extract_tool_call_from_text_guarded(text)  # 带拒答守卫的自然语言兜底
        if parsed:
            tname, targs = parsed
            _emit_stage(stream_callback, "querying")
            api_result = _invoke_tool_by_name(tname, targs)
            if api_result is not None and "error" not in api_result:
                logger.info("[Agent] 文本兜底解析到工具调用 %s", tname)
                return _assemble_agent_result(tname, targs, api_result, text[:500],
                                              question, with_report, conversation_id, history,
                                              stream_callback=stream_callback)

        # 3) 未提取到任何有效工具调用 → 确定性决策：直接判 out_of_scope，不重试
        agent_text_output = text[:500]
        logger.info("[Agent] 未调用任何工具，判定为非数据分析问题 → 返回暂不支持此服务")
        _obs_inc("out_of_scope_total")
        _obs_inc("agent_no_tool_total")
        _log_event("agent_no_tool", reason="no_tool_call")
        return _build_out_of_scope_result(question, agent_text_output)

    # 所有重试均因硬异常失败 → 降级旧 pipeline
    logger.warning("[Agent] 原生 tool-calling 执行失败，降级到旧 pipeline：%s", last_exc)
    _log_event("agent_fallback", reason="invoke_exception", err=str(last_exc)[:200])
    return None


def _handle_question_via_agent(question: str, with_report: bool | str = False,
                               conversation_id: str | None = None,
                               stream_callback=None) -> dict | None:
    """用 LangChain Agent 替换 parse_intent + call_analysis_api 的手工分发。

    成功返回 result dict（格式与 handle_question 一致）；
    失败返回 None，调用方降级到旧 pipeline。
    stream_callback：SSE 进度/token 回调（透传给 _run_native_tool_calling / 组装）。
    """
    # 优先：原生 tool-calling 循环（版本无关，最稳）
    # 直接 ChatOpenAI.bind_tools + 解析 resp.tool_calls，规避 langchain 1.x
    # create_agent 的 ReAct 提示词对 Qwen2.5-72B 的干扰（该路径下模型常不在
    # tool_calls 返回调用，导致误判 out_of_scope）。
    llm = _get_tool_calling_llm()
    if llm is not None:
        result = _run_native_tool_calling(question, with_report, conversation_id, llm,
                                          stream_callback=stream_callback)
        if result is not None:
            return result
        # 仅硬异常(invoke 失败)返回 None → 旧 pipeline 降级
        _obs_inc("agent_fallback_total")
        _obs_nested_inc("agent_fallback_reasons", "native_invoke_exception")
        _log_event("agent_fallback", reason="native_invoke_exception")
        return None

    # 回退：langchain agent 封装（0.2.x create_tool_calling_agent / 1.x create_agent）
    executor = _get_agent_executor()
    if executor is None:
        _obs_inc("agent_fallback_total")
        _obs_nested_inc("agent_fallback_reasons", "executor_unavailable")
        _log_event("agent_fallback", reason="executor_unavailable")
        return None

    # 构造多轮对话历史（LangChain 消息格式）
    history = MEMORY.get_history(conversation_id)
    chat_history = _build_agent_chat_history(history)

    # 调用 agent（0.2.x 和 1.x 调用格式不同）
    if _LC_AGENT_API == "v1x":
        # langchain 1.x: create_agent 返回 CompiledStateGraph，用 messages 格式
        invoke_input = {
            "messages": chat_history + [HumanMessage(content=question)],
        }
    else:
        # langchain 0.2.x: AgentExecutor 用 input + chat_history
        invoke_input = {
            "input": question,
            "chat_history": chat_history,
        }

    # 重试策略：仅对「硬异常(invoke 失败)」重试；「未提取到有效工具调用」是确定性
    # 决策（temperature=0 下重复调用结果一致），不重试，立即判 out_of_scope，避免烧钱。
    extracted = None
    agent_text_output = ""
    last_exc = None
    for attempt in range(1 + AGENT_TOOL_RETRIES):
        try:
            agent_result = executor.invoke(invoke_input)
        except Exception as e:
            last_exc = e
            logger.warning("[Agent] 执行失败(第 %d/%d 次)，重试：%s",
                           attempt + 1, 1 + AGENT_TOOL_RETRIES, e)
            _obs_inc("agent_fallback_total")
            _obs_nested_inc("agent_fallback_reasons", "invoke_exception_retry")
            continue  # 硬异常 → 重试

        # 提取工具调用信息（0.2.x 从 intermediate_steps，1.x 从 messages）
        if _LC_AGENT_API == "v1x":
            messages_list = agent_result.get("messages", [])
            extracted = _extract_tool_call_from_messages(messages_list)
            agent_text_output = ""
            # 获取最后一条 AIMessage 的内容作为 agent 输出
            for msg in reversed(messages_list):
                if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                    agent_text_output = str(msg.content or "")[:500]
                    break
        else:
            steps = agent_result.get("intermediate_steps", [])
            extracted = _extract_tool_call_from_steps(steps)
            agent_text_output = agent_result.get("output", "")[:500]

        if extracted is not None:
            break
        # 未提取到工具调用 → 确定性决策，直接判 out_of_scope，不重试
        logger.info("[Agent] 未调用任何工具，判定为非数据分析问题 → 返回暂不支持此服务")
        _obs_inc("out_of_scope_total")
        _obs_inc("agent_no_tool_total")
        _log_event("agent_no_tool", reason="no_tool_call")
        return _build_out_of_scope_result(question, agent_text_output)

    if extracted is None:
        # 所有重试均因硬异常失败 → 降级旧 pipeline
        logger.warning("[Agent] 执行失败，降级到旧 pipeline：%s", last_exc)
        _obs_inc("agent_fallback_total")
        _obs_nested_inc("agent_fallback_reasons", "invoke_exception")
        _log_event("agent_fallback", reason="invoke_exception", err=str(last_exc)[:200])
        return None

    tool_name, tool_args, api_result = extracted
    _emit_stage(stream_callback, "querying")
    return _assemble_agent_result(tool_name, tool_args, api_result, agent_text_output,
                                  question, with_report, conversation_id, history,
                                  stream_callback=stream_callback)


# ------------------------------------------------------------
# 数据取值中文化（英文源数据 → 中文展示）
# P3 返回的维度取值全是英文（性别 F/M/U、年龄组 "70 or Older"、严重程度 Minor、
# 支付方式 Medicare、出院去向 Home or Self Care 等）。在 _finalize_result 入口
# 对 api_result 递归做「值本地化」：命中映射表才替换，未命中（诊断/手术/医院名等
# 开放集合）保留英文——由 LLM 摘要/report 翻译 + 可选 translate_dimensions.py
# 生成的 dim_zh_cache.json 补充覆盖。
# ------------------------------------------------------------
_EN_ZH_MAP = {
    # 性别
    "F": "女", "M": "男", "U": "未知",
    # 年龄组（pyramid / severity_profile.group / payment_cross.dim2）
    "0 to 17": "0-17岁", "18 to 29": "18-29岁", "30 to 49": "30-49岁",
    "50 to 69": "50-69岁", "70 or Older": "70岁及以上",
    # 严重程度（Minor/Moderate/Major/Extreme 无歧义时默认严重程度语义）
    "Minor": "轻度", "Moderate": "中度", "Major": "重度", "Extreme": "极重度",
    # 支付方式（payment_typology_1/2/3）
    "Medicare": "联邦医疗保险", "Medicaid": "医疗补助",
    "Private Health Insurance": "商业医疗保险", "Blue Cross/Blue Shield": "蓝十字蓝盾保险",
    "Self-Pay": "自费", "Miscellaneous/Other": "其他/杂项",
    "Managed Care, Unspecified": "管理式医疗(未细分)",
    "Federal/State/Local/VA": "联邦/州/地方/退伍军人医保",
    "Department of Corrections": "惩戒机构",
    # 种族 / 族裔
    "White": "白人", "Black/African American": "黑人/非裔美国人",
    "Other Race": "其他种族", "Multi-racial": "多种族",
    "Not Span/Hispanic": "非西语裔", "Spanish/Hispanic": "西语裔",
    "Unknown": "未知", "Multi-ethnic": "多族裔",
    # 入院类型 / 内外科
    "Emergency": "急诊", "Elective": "择期", "Newborn": "新生儿",
    "Urgent": "紧急", "Trauma": "创伤", "Not Available": "未知",
    "Medical": "内科", "Surgical": "外科", "Not Applicable": "不适用",
    # 出院去向（patient_disposition）
    "Home or Self Care": "回家自行照护",
    "Home w/ Home Health Services": "回家(家庭健康服务)",
    "Skilled Nursing Home": "专业护理机构", "Expired": "死亡",
    "Left Against Medical Advice": "违反医嘱离院",
    "Short-term Hospital": "短期住院医院",
    "Inpatient Rehabilitation Facility": "住院康复机构",
    "Hospice - Home": "临终关怀(居家)",
    "Psychiatric Hospital or Unit of Hosp": "精神病医院/病房",
    "Hospice - Medical Facility": "临终关怀(医疗机构)",
    "Facility w/ Custodial/Supportive Care": "看护/支持性护理机构",
    "Another Type Not Listed": "其他未列出类型",
    "Court/Law Enforcement": "法院/执法部门",
    "Medicare Cert Long Term Care Hospital": "医保认证长期护理医院",
    "Cancer Center or Children's Hospital": "癌症中心/儿童医院",
    "Hosp Basd Medicare Approved Swing Bed": "医保认证轮换病床",
    "Medicaid Cert Nursing Facility": "医疗补助认证护理机构",
    # 地区
    "OOS": "州外",
}

# 可选扩展映射：由 translate_dimensions.py 批量翻译诊断/手术/医院名生成的
# dim_zh_cache.json（{英文名: 中文名}），启动时合并进 _EN_ZH_MAP（见 _load_dim_zh_cache）
_DIM_ZH_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "dim_zh_cache.json")


def _load_dim_zh_cache():
    """启动时加载可选的中文扩展映射（诊断/手术/医院名等开放集合）。
    translate_dimensions.py 生成；文件不存在时静默跳过（保留英文，不影响主流程）。"""
    try:
        with open(_DIM_ZH_CACHE_PATH, "r", encoding="utf-8") as f:
            ext = json.load(f)
        if isinstance(ext, dict):
            _EN_ZH_MAP.update({k: v for k, v in ext.items() if isinstance(k, str) and isinstance(v, str)})
            logger.info("[localize] 已加载中文扩展映射 %d 条（%s）", len(ext), _DIM_ZH_CACHE_PATH)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("[localize] 中文扩展映射加载失败（忽略）：%s", e)


def _localize_value(v):
    """单个值中文化：字符串命中映射表才替换，其余原样返回。"""
    if isinstance(v, str):
        return _EN_ZH_MAP.get(v, v)
    return v


def _localize_api_result(api_result):
    """递归把 api_result 里所有展示用字符串值本地化（命中映射表才替换）。
    覆盖 data 行中的 key/name/group/severity/dim2_name/age_group 等任意字段，
    一处调用让图表类目 / report 提取 / 模板摘要 / LLM 输入全部中文化。"""
    if isinstance(api_result, dict):
        return {k: _localize_api_result(v) for k, v in api_result.items()}
    if isinstance(api_result, list):
        return [_localize_api_result(x) for x in api_result]
    return _localize_value(api_result)


_load_dim_zh_cache()


def _finalize_result(question: str, intent: dict, api_result: dict,
                     with_report: bool | str = False,
                     conversation_id: str | None = None,
                     history: list = None,
                     extra_meta: dict = None,
                     stream_callback=None) -> dict:
    """Agent 路径与旧 pipeline 共用的结果收尾：生成摘要+图表、组装结果、
    提取 warnings、写会话历史、生成报告（同步/异步）。两条路径输出格式完全一致。

    extra_meta：附加到 result["meta"] 的额外字段（如 agent 路径写入 agent_output 调试信息）。
    stream_callback：SSE 真流式进度/token 回调（{"type":"stage"|"token","..."}），None 为普通请求。
    """
    history = history or []
    # 数据取值中文化：英文源数据（F/M/U、Minor、Medicare、Home or Self Care…）在进入
    # 摘要/图表/report 前统一翻译成中文，保证展示层全链路中文。错误体保持原样。
    if not (isinstance(api_result, dict) and api_result.get("error")):
        api_result = _localize_api_result(api_result)
    _emit_stage(stream_callback, "summarizing")
    summary = generate_text_summary(question, intent, api_result,
                                    history=history, stream_callback=stream_callback)
    # 容错：P3 数据层失败时不生成图表——避免空图误导前端，且省一次 LLM 图表标题调用
    # （generate_text_summary 的错误分支不注入 _llm_chart_suggestion，generate_chart_config
    #  会独立再调一次 _suggest_chart_by_llm，纯属浪费）。错误详情见 meta.error / error_detail。
    has_p3_error = bool(isinstance(api_result, dict) and api_result.get("error"))
    if has_p3_error:
        chart = None
    else:
        _emit_stage(stream_callback, "charting")
        chart = generate_chart_config(intent, api_result)

    result = {
        "question": question,
        "intent": intent,
        "answer": summary,
        "chart": chart,
        "meta": dict(api_result.get("meta", {})),  # 复制一份，避免后续 update 污染 api_result
    }
    if extra_meta:
        result["meta"].update(extra_meta)

    # 提取 warnings 到顶层（call_analysis_api / _dispatch_chart_hint 写入的降级提示）
    meta_warnings = (result["meta"] or {}).get("warnings")
    if meta_warnings:
        result["warnings"] = meta_warnings

    # 记录本轮到会话历史（多轮对话 + 历史详情回看）
    if conversation_id:
        clean_intent = {k: v for k, v in intent.items() if not k.startswith("_")}
        MEMORY.add_turn(conversation_id, question, clean_intent,
                        answer=summary, chart=chart)
        result["conversation_id"] = conversation_id
        result["conversation_turn"] = len(MEMORY.get_history(conversation_id))

    # 报告生成（同步 / 异步）
    async_mode = (isinstance(with_report, str)
                  and with_report.lower() == "async")
    if with_report and not async_mode:
        # 必须把 intent 传给报告生成器：_build_section_findings 按 chart_hint 提取
        # key/value（pyramid/heatmap/payment_cross 等结构依赖它，缺了会显示「-」/0）
        result["report"] = generate_insight_report(single_result={
            "api_result": api_result, "chart": chart, "intent": intent})
    elif async_mode:
        report_id = _submit_async_report(api_result=api_result, chart=chart,
                                         intent=intent)
        result["report_pending"] = True
        result["report_id"] = report_id
        result["report"] = None

    return result


# ------------------------------------------------------------
# 4. 分析结果文本生成（LLM + 模板兜底，失败自动降级）
# ------------------------------------------------------------
def _intent_year(intent: dict) -> str | None:
    """从 intent.filters 提取年份（用于摘要口径说明），无则 None。"""
    f = intent.get("filters") or {}
    y = f.get("year")
    return str(y) if y else None


def _summary_topn_named(question, api_result, metric_zh, record_word: str,
                        item_label: str, year=None) -> str:
    """top-diagnoses / top-procedures 共用的 Top-N 排行摘要模板。

    record_word：记录类型（"住院" / "手术"）；item_label：条目名（"诊断" / "术式"）。
    year：带年份过滤时传入（如 "2021"），文案写明年份口径，避免用户误以为数据缺失
    （全表多年份合计可达百万级，而单年可能只有几千条——2026-08-23 数据口径优化）。
    """
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    scope_zh = f"{year} 年" if year else ""
    lines = [f"📋 针对您的问题「{question}」，{scope_zh}共分析 **{total:,}** 条{record_word}记录。",
             f"📊 按{record_word}{metric_zh}排名，前 {len(data)} 种{item_label}如下："]
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


def _summary_top_diagnoses(question, intent, api_result, dim_zh, metric_zh):
    """4.1 top-diagnoses 摘要：用 name（人类可读名）而不是 code。"""
    return _summary_topn_named(question, api_result, metric_zh, "住院", "诊断",
                               year=_intent_year(intent))


def _summary_top_procedures(question, intent, api_result, dim_zh, metric_zh):
    """4.2 top-procedures 摘要：结构同 top-diagnoses。"""
    return _summary_topn_named(question, api_result, metric_zh, "手术", "术式",
                               year=_intent_year(intent))


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
        key = r.get("name") or r.get("key") or "-"
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
        lines.append(f"💡 「{top.get('name') or top.get('key','-')}」自付负担最重；建议关注该人群的医保覆盖与减免政策。")
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
def _summary_cost(question, intent, api_result, dim_zh, metric_zh):
    """费用成本分析 5 个端点的通用 Top-N 摘要（profit_difference/profit_margin/
    efficiency_ranking/composition/cost_trend 共用）。数据形状均为 {key,value/pct,count}。"""
    chart_hint = intent.get("chart_hint")
    title = CHART_HINT_TITLE_ZH.get(chart_hint, "费用成本分析")
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})
    total = meta.get("total_records", 0) or 0
    lines = [f"📋 针对您的问题「{question}」，共分析 **{total:,}** 条住院记录。",
             f"📊 {title}，结果如下："]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(data[:5]):
        key = r.get("key") or r.get("year") or "-"
        value = r.get("value")
        if value is None:
            value = r.get("pct") or r.get("count") or 0
        count = r.get("count") or 0
        v_str = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
        extra = f"（{count:,} 例）" if count else ""
        medal = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"  {medal} 「{key}」：{v_str}{extra}")
    lines.append(f"⏱️ 本次查询耗时 {meta.get('query_ms', 0)} ms。")
    return "\n".join(lines)


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
    # —— 费用成本分析（对接 /cost/*）——
    "profit_difference":   _summary_cost,
    "profit_margin":       _summary_cost,
    "efficiency_ranking":  _summary_cost,
    "composition":         _summary_cost,
    "cost_trend":          _summary_cost,
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
            logger.error("SUMMARY BUILDER ERROR %s: %s，降级到通用模板", chart_hint, e, exc_info=True)
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


# ------------------------------------------------------------
# 摘要缓存（单轮场景：相同问题+意图在 TTL 内直接复用，省一次 14B 摘要调用）
#   键 = md5(question + chart_hint + intent 关键字段 + filters)
#   仅缓存「非错误、非空结果」；多轮对话（history 非空）不缓存（历史影响内容）。
# ------------------------------------------------------------
_SUMMARY_CACHE: dict[str, dict] = {}
_SUMMARY_CACHE_LOCK = threading.Lock()
SUMMARY_CACHE_TTL = int(os.getenv("SUMMARY_CACHE_TTL", str(10 * 60)))   # 默认 10 分钟
SUMMARY_CACHE_MAX = int(os.getenv("SUMMARY_CACHE_MAX", "500"))


def _summary_cache_key(question: str, intent: dict) -> str:
    """构造摘要缓存键（只依赖问题 + 意图，不含数据，TTL 兜底数据刷新）。"""
    parts = [question, str(intent.get("chart_hint") or "")]
    for k in ("dimension", "metric", "top", "by", "dim1", "dim2", "group",
              "levels", "level", "mode", "min_cases"):
        v = intent.get(k)
        if v is not None:
            parts.append(f"{k}={v}")
    filters = intent.get("filters") or {}
    if filters:
        parts.append("filters=" + json.dumps(filters, sort_keys=True, ensure_ascii=False))
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def _summary_cache_get(key: str) -> dict | None:
    """取缓存（过期即删并返回 None）。"""
    with _SUMMARY_CACHE_LOCK:
        entry = _SUMMARY_CACHE.get(key)
        if not entry:
            return None
        if time.time() - entry["ts"] >= SUMMARY_CACHE_TTL:
            _SUMMARY_CACHE.pop(key, None)
            return None
        return entry


def _summary_cache_put(key: str, summary: str, chart_suggestion: dict | None) -> None:
    """写缓存；超容量时淘汰最旧条目（粗粒度 LRU）。"""
    with _SUMMARY_CACHE_LOCK:
        if len(_SUMMARY_CACHE) >= SUMMARY_CACHE_MAX:
            oldest = min(_SUMMARY_CACHE, key=lambda k: _SUMMARY_CACHE[k]["ts"])
            _SUMMARY_CACHE.pop(oldest, None)
        _SUMMARY_CACHE[key] = {
            "summary": summary,
            "chart_suggestion": chart_suggestion,
            "ts": time.time(),
        }


def generate_text_summary(question, intent, api_result, history=None, stream_callback=None):
    """将结构化分析结果转化为通俗易懂的医疗摘要。

    优先级（生产环境稳定优先）：
    1) 若配置了 LLM_API_KEY → 先尝试调用 LLM 生成高质量摘要
    2) LLM 调用任何环节失败 → 立刻降级用规则模板兜底
    history 不为空时，告诉 LLM 这是多轮对话，让回答更连贯。

    stream_callback：SSE 真流式时传入，摘要 token 以 {"type":"token","data":piece} 逐段回调。
    """
    _obs_inc("summary_calls_total")
    _t0 = time.time()
    # 缓存：仅单轮（无历史）+ 非 P3 错误场景；命中直接复用并恢复图表建议
    cacheable = (not history) and not (isinstance(api_result, dict) and api_result.get("error"))
    key = _summary_cache_key(question, intent) if cacheable else None
    if key:
        hit = _summary_cache_get(key)
        if hit is not None:
            _obs_inc("summary_cache_hits")
            if hit.get("chart_suggestion"):
                intent["_llm_chart_suggestion"] = hit["chart_suggestion"]
            _obs_latency("summary_latency_ms_total", (time.time() - _t0) * 1000)
            return hit["summary"]
    try:
        text = _generate_text_summary_impl(question, intent, api_result,
                                           history, stream_callback)
    except Exception as e:
        _obs_inc("summary_errors")
        logger.error("SUMMARY BUILDER ERROR %s: %s，降级到通用模板",
                     intent.get("chart_hint"), e, exc_info=True)
        text = "❌ 摘要生成失败，请稍后重试。"
    finally:
        _obs_latency("summary_latency_ms_total", (time.time() - _t0) * 1000)
    # 写缓存：仅缓存非错误、非空结果（错误/空数据结果没有复用价值）
    if key and text and not text.startswith("❌"):
        _summary_cache_put(key, text, intent.get("_llm_chart_suggestion"))
    return text


def _generate_text_summary_impl(question, intent, api_result, history=None,
                                stream_callback=None):
    """generate_text_summary 的实现体（异常已被外层捕获并计错误，这里专注业务逻辑）。

    stream_callback：可选回调，摘要 LLM 走流式调用时每个增量 token 以
    {"type":"token","data":piece} 回调（SSE 真流式用）；None 时走一次性调用。
    """
    logger.debug("LLM_ENABLED = %s", LLM_ENABLED)
    chart_hint = intent.get("chart_hint")

    # —— 容错加固：P3 调用失败，返回明确提示而非"未查询到结果" ——
    if isinstance(api_result, dict) and api_result.get("error"):
        err = api_result["error"]
        if err == "timeout":
            return "❌ 数据服务响应超时，请稍后重试。"
        if err == "connection_failed":
            return "❌ 无法连接数据服务，请确认服务已启动后重试。"
        return "❌ 数据服务暂时不可用，请稍后重试或联系管理员。"

    meta = api_result.get("meta", {}) if api_result else {}
    metric_zh = METRIC_ZH.get(meta.get("metric", ""), meta.get("metric", "指标"))
    dim_zh = DIMENSION_ZH.get(intent.get("dimension", ""), "维度")
    total = meta.get("total_records", 0) or 0

    # payment_summary 的 data 是单个 dict（KPI 大屏），不是 list —— 用专用 LLM 提示
    if chart_hint == "payment_summary":
        raw = api_result.get("data") if api_result else None
        if not isinstance(raw, dict) or not raw:
            return "❌ 未查询到 KPI 总览数据。"
        # 路径1：LLM 生成（启用了就尝试，失败降级到模板）
        if LLM_ENABLED:
            messages = _build_llm_messages_for_kpi(question, intent, raw, meta)
            # 多轮上下文（与主路径一致，传答案摘要而非只传问题）
            if history:
                messages[1]["content"] += _build_multiturn_context(history)
            _obs_inc("summary_llm_calls")
            if stream_callback:
                ok, text_or_reason = _call_llm_stream(
                    messages, lambda p: stream_callback({"type": "token", "data": p}))
            else:
                ok, text_or_reason = _call_llm_safely(messages)
            if ok:
                # KPI 路径目前是纯文本输出，直接返回
                return text_or_reason
            logger.warning("LLM 调用失败（payment_summary）：%s", text_or_reason)
        # 路径2：模板兜底
        return _fallback_template_summary(question, intent, api_result, "总览", "KPI")

    data = []
    if api_result and isinstance(api_result, dict):
        data = api_result.get("data", [])
        # sankey 的 data 是 dict（nodes/links），不是 list
        if isinstance(data, dict):
            data = data.get("nodes", []) or data.get("links", [])
    logger.debug("data length = %s", len(data) if isinstance(data, list) else "non-list")
    if not data:
        return "❌ 未查询到符合条件的分析结果，请调整查询条件后重试。"

    # —— 路径1：LLM 生成（如果启用了）——
    # 注意：此块必须与函数体同级缩进（曾有 8 格缩进被误嵌进 `if not data:` 成为死代码，
    # 导致主路径摘要从未真正调用 LLM、一直走模板兜底——2026-08-23 修复）。
    if LLM_ENABLED:
        messages = _build_llm_messages(question, intent, data, meta, dim_zh, metric_zh, total)
        # 多轮上下文：传上一轮问题 + 答案摘要（前 200 字），不只传问题
        if history:
            messages[1]["content"] += _build_multiturn_context(history)
        _obs_inc("summary_llm_calls")
        if stream_callback:
            # 流式：LLM 输出是 {summary, chart_suggestion} JSON，只把 summary 值转发前端
            _tok_cb = _SummaryStreamFilter(
                lambda p: stream_callback({"type": "token", "data": p}))
            ok, text_or_reason = _call_llm_stream(messages, _tok_cb)
        else:
            ok, text_or_reason = _call_llm_safely(messages)
        if ok:
            # 优化 2：LLM 现在输出严格 JSON {summary, chart_suggestion}
            # 解析出 summary 文本返回，chart_suggestion 挂到 intent 供下游 generate_chart_config 复用
            summary_text, chart_sugg = _parse_summary_json(text_or_reason)
            if chart_sugg:
                intent["_llm_chart_suggestion"] = chart_sugg
            if summary_text:
                return summary_text
            # JSON 解析失败但 LLM 返回了内容：降级用原始文本（向后兼容老 prompt）
            logger.warning("摘要 JSON 解析失败，使用原始文本作为兜底")
            return text_or_reason
        else:
            # 打印错误到控制台（便于调试）
            logger.warning("LLM 调用失败：%s", text_or_reason)
            # 继续执行模板兜底
    # —— 路径2：模板兜底（LLM 没启用 / 调用失败都会走这）——
    return _fallback_template_summary(question, intent, api_result, dim_zh, metric_zh)


def _parse_summary_json(raw_text: str) -> tuple[str, dict]:
    """解析 LLM 输出的 {summary, chart_suggestion} JSON。

    返回 (summary_text, chart_suggestion_dict)。
    解析失败返回 ("", {})，调用方降级处理。
    """
    if not raw_text:
        return "", {}
    ok_json, obj, _reason = _extract_json_from_llm_output(raw_text)
    if not ok_json or not isinstance(obj, dict):
        return "", {}
    summary_text = obj.get("summary", "")
    if not isinstance(summary_text, str):
        summary_text = str(summary_text)
    chart_sugg = obj.get("chart_suggestion") or {}
    if not isinstance(chart_sugg, dict):
        chart_sugg = {}
    # 字段长度约束（与原 _suggest_chart_by_llm 一致）
    chart_sugg = {
        "title": str(chart_sugg.get("title", ""))[:20],
        "subtitle": str(chart_sugg.get("subtitle", ""))[:30],
    }
    return summary_text, chart_sugg


# ------------------------------------------------------------
# 流式摘要过滤器：把 LLM 流式输出的 JSON {summary, chart_suggestion} 中
# 的 summary 字段值逐段转发给前端（丢弃 JSON 结构），实现"打字机"式干净输出。
# ------------------------------------------------------------
import re as _re_summary
_SUMMARY_VALUE_RE = _re_summary.compile(r'"summary"\s*:\s*"')


def _unescape_summary_fragment(s: str) -> str:
    """轻量反转义 JSON 字符串片段（\n \t \" \\）。顺序：先 \\\\ 再其余，避免 \\n 误转。"""
    return (s.replace("\\\\", "\u0000")
             .replace('\\"', '"')
             .replace("\\n", "\n")
             .replace("\\t", "\t")
             .replace("\\r", "\r")
             .replace("\u0000", "\\"))


class _SummaryStreamFilter:
    """增量解析 LLM 流式 JSON，仅把 "summary" 字段的值（反转义后）转给 on_text。

    状态机：
      - 未进入值：累积字符定位 "summary": " 开引号（模式可跨 chunk）
      - 值内：逐段转发，直到未转义闭合引号（"\" 前缀的引号不算）
      - 结束：忽略后续（chart_suggestion 等）
    末尾以奇数个反斜杠结尾时，可能是跨 chunk 的转义前缀（如反斜杠与 n 被切开），
    把最后一个反斜杠留给下一段再处理，保证反转义正确。
    """

    def __init__(self, on_text):
        self._on_text = on_text
        self._buf = ""
        self._in_value = False
        self._done = False

    def __call__(self, piece: str) -> None:
        if self._done:
            return
        self._buf += piece
        if not self._in_value:
            idx = _SUMMARY_VALUE_RE.search(self._buf)
            if idx is None:
                # 只保留末尾可能跨边界的部分，防无界增长
                if len(self._buf) > 128:
                    self._buf = self._buf[-128:]
                return
            self._in_value = True
            self._buf = self._buf[idx.end():]

        # 找未转义闭合引号（前一个字符不是反斜杠）
        cut = -1
        i = 0
        n = len(self._buf)
        while i < n:
            if self._buf[i] == '"' and (i == 0 or self._buf[i - 1] != "\\"):
                cut = i
                break
            i += 1
        if cut >= 0:
            val = self._buf[:cut]
            self._done = True
            self._buf = ""
        else:
            val = self._buf
            self._buf = ""

        # 跨段转义处理：末尾奇数个反斜杠 → 保留最后一个给下一段
        trail = 0
        j = len(val) - 1
        while j >= 0 and val[j] == "\\":
            trail += 1
            j -= 1
        if trail % 2 == 1 and val:
            self._buf = val[-1] + self._buf
            val = val[:-1]
        if val:
            self._on_text(_unescape_summary_fragment(val))


# ------------------------------------------------------------
# 5. 生成 ECharts 图表配置（供前端渲染，更美观）
# 策略：规则引擎生成稳定结构，LLM 辅助"图表类型建议 + 个性化标题 + 数据描述"
# ------------------------------------------------------------
def _suggest_chart_by_llm(intent: dict, dim_zh: str, metric_zh: str,
                           data_sample: list[dict]) -> dict:
    """让 LLM 建议：用什么图表类型、取什么好标题、一句话描述（JSON 输出）。
    返回建议 dict，任何环节失败都返回空 dict，调用方用规则默认值。

    优化 4：扩展 chart_type 白名单，新增 13 种 P3 专用图表类型，让 LLM 在
    chart_hint 命中场景也能给出合理建议（虽然专用构造器不取 chart_type，
    但 title/subtitle 仍可用，且白名单扩展后 LLM 不会因非法值返回空）。
    """
    if not LLM_ENABLED:
        return {}
    chart_hint = intent.get("chart_hint") or ""
    # 优化 4：扩展白名单，覆盖 P3 新版 13 种 chart_hint 对应的图表类型
    allowed_chart_types = {
        # 旧版
        "bar", "pie", "line",
        # P3 新版专用（仅用于 LLM 理解上下文，专用构造器会忽略 chart_type）
        "stacked_bar", "grouped_bar", "pyramid", "heatmap", "sankey",
        "scatter", "kpi", "horizontal_bar", "funnel",
    }
    system_prompt = (
        "你是可视化工程师。请根据医疗分析任务，推荐合适的 ECharts 图表配置。\n"
        f"合法 chart_type：{', '.join(sorted(allowed_chart_types))}（不在此列表的会被忽略）。\n"
        "选择规则：\n"
        "- pie：仅限占比类问题（如支付方式构成）\n"
        "- line：仅限时间趋势类问题\n"
        "- bar：默认，排名/对比/计数\n"
        "- stacked_bar：堆叠柱状图，交叉分析（如支付×年龄段）\n"
        "- grouped_bar：分组柱状图，多系列对比\n"
        "- pyramid：人口金字塔，双向条形图\n"
        "- heatmap：热力图，二维交叉密度\n"
        "- sankey：桑基图，流向/链路\n"
        "- scatter：散点图，二维数值关系\n"
        "- kpi：KPI 卡片，关键指标总览\n"
        "- horizontal_bar：横向柱状图，长名称排名\n"
        "- funnel：漏斗图，转化漏斗\n"
        "严格合法 JSON 输出：\n"
        "{\"chart_type\": \"类型\", \"title\": \"好标题（10字以内，具体而非泛化）\", \"subtitle\": \"15字内的副标题\"}\n"
        "不要加任何其他文字或代码块。"
    )
    user_prompt = (
        f"维度：{dim_zh}，指标：{metric_zh}\n"
        f"用户问题关联: dimension={intent.get('dimension')}, metric={intent.get('metric')}"
        f"{', chart_hint=' + chart_hint if chart_hint else ''}\n"
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
    ok_json, suggestion, _reason = _extract_json_from_llm_output(content)
    if not ok_json or not isinstance(suggestion, dict):
        return {}

    # 字段校验 + 约束（优化 4：扩展白名单到 11 种）
    ct = suggestion.get("chart_type")
    if ct not in allowed_chart_types:
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
def _base_title(suggestion: dict | None, default_text: str) -> dict:
    """构造 ECharts title 对象，优先用 LLM 建议的标题（suggestion 可为 None）。"""
    suggestion = suggestion or {}
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
    # 类目优先用人类可读 name（P3 返回 {key, name, self_pay_*...}），无 name 才回退 key
    cats = [(str(r.get("name") or r.get("key") or "-"))[:name_limit] for r in data]
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
            "name": (str(r.get("name") or r.get("key") or "-"))[:name_limit],
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
def _build_cost_option(intent, api_result, suggestion):
    """费用成本分析 5 个端点的通用柱状图（profit_difference/profit_margin/
    efficiency_ranking/composition/cost_trend 共用）。数据形状 {key,value/pct,count}。"""
    data = api_result.get("data", [])
    chart_hint = intent.get("chart_hint")
    title = CHART_HINT_TITLE_ZH.get(chart_hint, "费用成本分析")
    x = [str(r.get("key") or r.get("year") or "-") for r in data]
    y = []
    for r in data:
        v = r.get("value")
        if v is None:
            v = r.get("pct") or r.get("count") or 0
        try:
            y.append(float(v))
        except (TypeError, ValueError):
            y.append(0)
    title_obj = _base_title(suggestion, title)
    option = {
        "title": title_obj,
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 80, "right": 30, "bottom": 80, "top": 50},
        "xAxis": {"type": "category", "data": x,
                  "axisLabel": {"interval": 0, "rotate": 30}},
        "yAxis": {"type": "value", "name": "数值"},
        "series": [{"type": "bar", "data": y,
                    "itemStyle": {"color": "#5470c6"},
                    "label": {"show": True, "position": "top"}}],
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_quality_overview_option(intent, api_result, suggestion):
    """4.1 quality-overview 质量 KPI 大屏：数字卡片 + 各质量比率柱状图。"""
    raw = api_result.get("data") or {}
    if isinstance(raw, list):  # 容错
        raw = {}
    kpi_data = {
        "total_records": raw.get("total_records", 0),
        "deaths": raw.get("deaths", 0),
        "mortality_rate": raw.get("mortality_rate", 0),
        "avg_los": raw.get("avg_los", 0),
        "ed_rate": raw.get("ed_rate", 0),
        "ama_rate": raw.get("ama_rate", 0),
        "transfer_rate": raw.get("transfer_rate", 0),
        "newborns": raw.get("newborns", 0),
        "lbw_rate": raw.get("lbw_rate"),
        "avg_charges": raw.get("avg_charges", 0),
        "avg_costs": raw.get("avg_costs", 0),
    }
    title_obj = _base_title(suggestion, "医疗质量 KPI 总览")
    sub_lines = [
        f"总出院 {kpi_data['total_records']:,} 条 · 死亡 {kpi_data['deaths']:,} 人",
        f"死亡率 {kpi_data['mortality_rate']}% · 平均住院 {kpi_data['avg_los']} 天",
        f"急诊率 {kpi_data['ed_rate']}% · 转院率 {kpi_data['transfer_rate']}%",
        f"次均费用 {kpi_data['avg_charges']:,.2f} 元 / 成本 {kpi_data['avg_costs']:,.2f} 元",
    ]
    title_obj["subtext"] = "\n".join(sub_lines)
    title_obj["subtextStyle"] = {"fontSize": 11, "lineHeight": 16}
    # 主图：各质量比率柱状图（大屏直观可视化）
    rate_items = [
        ("死亡率", kpi_data["mortality_rate"] or 0),
        ("急诊率", kpi_data["ed_rate"] or 0),
        ("AMA率", kpi_data["ama_rate"] or 0),
        ("转院率", kpi_data["transfer_rate"] or 0),
    ]
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}: {c}%"},
        "grid": {"left": 70, "right": 30, "bottom": 50, "top": 120},
        "xAxis": {"type": "category", "data": [k for k, _ in rate_items]},
        "yAxis": {"type": "value", "name": "比率（%）"},
        "series": [{
            "type": "bar", "name": "比率", "barMaxWidth": 60,
            "data": [v for _, v in rate_items],
            "itemStyle": {"borderRadius": [4, 4, 0, 0]},
            "label": {"show": True, "position": "top", "formatter": "{c}%"},
        }],
    }
    return {"chart_type": "kpi", "option": option, "kpi": kpi_data,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_quality_mortality_option(intent, api_result, suggestion):
    """4.2 quality-mortality 死亡率排行柱状图：X=name，Y=mortality_rate（%）。"""
    data = api_result.get("data", [])
    cats = [r.get("name") or r.get("key") or "-" for r in data]
    vals = [r.get("mortality_rate") or 0 for r in data]
    title_obj = _base_title(suggestion, "死亡率排行 Top N")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}<br/>死亡率: {c}%"},
        "grid": {"left": 70, "right": 30, "bottom": 110, "top": 50},
        "xAxis": {"type": "category", "data": cats,
                  "axisLabel": {"rotate": 35, "interval": 0, "fontSize": 11},
                  "name": "维度"},
        "yAxis": {"type": "value", "name": "死亡率（%）"},
        "series": [{
            "type": "bar", "name": "死亡率", "data": vals, "barMaxWidth": 50,
            "itemStyle": {"borderRadius": [4, 4, 0, 0], "color": "#ff4d4f"},
            "label": {"show": True, "position": "top", "fontSize": 10, "formatter": "{c}%"},
        }],
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_quality_los_option(intent, api_result, suggestion):
    """4.3 quality-length-of-stay 平均住院日排行柱状图：X=name，Y=avg_los。"""
    data = api_result.get("data", [])
    cats = [r.get("name") or r.get("key") or "-" for r in data]
    vals = [r.get("avg_los") or 0 for r in data]
    title_obj = _base_title(suggestion, "平均住院日排行 Top N")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}<br/>平均住院日: {c} 天"},
        "grid": {"left": 70, "right": 30, "bottom": 110, "top": 50},
        "xAxis": {"type": "category", "data": cats,
                  "axisLabel": {"rotate": 35, "interval": 0, "fontSize": 11},
                  "name": "维度"},
        "yAxis": {"type": "value", "name": "平均住院日（天）"},
        "series": [{
            "type": "bar", "name": "平均住院日", "data": vals, "barMaxWidth": 50,
            "itemStyle": {"borderRadius": [4, 4, 0, 0], "color": "#1e6fd9"},
            "label": {"show": True, "position": "top", "fontSize": 10, "formatter": "{c}天"},
        }],
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_quality_facility_option(intent, api_result, suggestion):
    """4.4 quality-facility-ranking 医院死亡率对比柱状图（按死亡率降序）。"""
    data = api_result.get("data", [])
    # API 原返回按出院量降序，这里按死亡率降序重排，突出"质量对比"视角
    rows = sorted(data, key=lambda r: r.get("mortality_rate") or 0, reverse=True)
    cats = [r.get("name") or r.get("key") or "-" for r in rows]
    vals = [r.get("mortality_rate") or 0 for r in rows]
    title_obj = _base_title(suggestion, "医院死亡率对比")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                    "formatter": "{b}<br/>死亡率: {c}%"},
        "grid": {"left": 70, "right": 30, "bottom": 110, "top": 50},
        "xAxis": {"type": "category", "data": cats,
                  "axisLabel": {"rotate": 40, "interval": 0, "fontSize": 10},
                  "name": "医院"},
        "yAxis": {"type": "value", "name": "死亡率（%）"},
        "series": [{
            "type": "bar", "name": "死亡率", "data": vals, "barMaxWidth": 50,
            "itemStyle": {"borderRadius": [4, 4, 0, 0], "color": "#ff4d4f"},
            "label": {"show": True, "position": "top", "fontSize": 10, "formatter": "{c}%"},
        }],
    }
    return {"chart_type": "bar", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


def _build_quality_disposition_option(intent, api_result, suggestion):
    """4.5 quality-disposition 离院去向构成饼图。"""
    data = api_result.get("data", [])
    pie_data = [{"name": r.get("key") or "-", "value": r.get("count") or 0}
                for r in data]
    title_obj = _base_title(suggestion, "离院去向构成")
    option = {
        "color": COLORS,
        "title": title_obj,
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"orient": "vertical", "left": "left", "top": "middle"},
        "series": [{
            "type": "pie", "radius": ["35%", "65%"], "center": ["65%", "55%"],
            "label": {"formatter": "{b}\n{d}%"},
            "data": pie_data,
            "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2},
        }],
    }
    return {"chart_type": "pie", "option": option,
            "_suggestion_source": "llm" if suggestion else "rules"}


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
    # —— 费用成本分析（对接 /cost/*）——
    "profit_difference":   _build_cost_option,
    "profit_margin":       _build_cost_option,
    "efficiency_ranking":  _build_cost_option,
    "composition":         _build_cost_option,
    "cost_trend":          _build_cost_option,
    "quality_overview":    _build_quality_overview_option,
    "quality_mortality":   _build_quality_mortality_option,
    "quality_los":         _build_quality_los_option,
    "quality_facility":    _build_quality_facility_option,
    "quality_disposition": _build_quality_disposition_option,
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
        # 优化 2：优先复用 generate_text_summary 已产出的 _llm_chart_suggestion，
        # 没有才回退到独立调用 _suggest_chart_by_llm
        suggestion = {}
        if use_llm and LLM_ENABLED:
            cached_sugg = intent.get("_llm_chart_suggestion")
            if isinstance(cached_sugg, dict) and cached_sugg.get("title"):
                suggestion = cached_sugg
            else:
                try:
                    p3_dim_zh = (P3_DIM_ZH.get(chart_hint, "")
                                 or DIMENSION_ZH.get(intent.get("dimension", ""), "维度"))
                    p3_metric_zh = METRIC_ZH.get(intent.get("metric", ""), intent.get("metric", ""))
                    sample = (api_result.get("data", []) or [])[:3]
                    suggestion = _suggest_chart_by_llm(intent, p3_dim_zh, p3_metric_zh, sample)
                except Exception:
                    suggestion = {}
        try:
            return CHART_BUILDERS[chart_hint](intent, api_result, suggestion)
        except Exception as e:
            # 兜底：专用构造器异常时降级到旧版 metric 路由（保证总有图出）
            logger.error("CHART BUILDER ERROR %s: %s，降级到旧版 metric 路由",
                         chart_hint, e, exc_info=True)

    # —— 路由2：旧版 metric 路由（pie/line/bar）—— 向后兼容
    data = api_result.get("data", [])
    metric = intent["metric"]
    metric_zh = METRIC_ZH.get(metric, metric)
    dim_zh = DIMENSION_ZH.get(intent.get("dimension", ""), "维度")
    default_title = f"{dim_zh} × {metric_zh}"

    # —— LLM 辅助：先问 LLM 有什么好的建议（不阻塞核心逻辑，超时/乱码直接忽略）——
    # 优化 2：同样优先复用 generate_text_summary 产出的 _llm_chart_suggestion
    suggestion = {}
    if use_llm and LLM_ENABLED and data:
        cached_sugg = intent.get("_llm_chart_suggestion")
        if isinstance(cached_sugg, dict) and cached_sugg.get("title"):
            suggestion = cached_sugg
        else:
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
7. 数据中若出现英文维度取值（性别 F/M、支付方式 Medicare、严重程度 Minor、疾病名、
   出院去向等），在报告中一律用中文表达（如「女」「联邦医疗保险」「轻度」「活产儿」），
   不要原样保留英文缩写或代码。

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

    # 解析 JSON（公共函数统一容错）
    ok_json, data, reason = _extract_json_from_llm_output(content)
    if not ok_json or not isinstance(data, dict):
        return False, {}, f"LLM 返回非合法 JSON: {reason}"

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
    # —— 费用成本分析（对接 /cost/*）——
    "profit_difference":  "费用成本差",
    "profit_margin":      "利润率",
    "efficiency_ranking": "成本效益排行",
    "composition":        "费用构成",
    "cost_trend":         "费用年度趋势",
    "quality_overview":   "医疗质量总览",
    "quality_mortality":  "死亡率排行",
    "quality_los":        "平均住院日排行",
    "quality_facility":   "医院质量对比",
    "quality_disposition": "离院去向构成",
}

# chart_hint → 常见图表类型（给 /api/meta/dimensions 的能力目录做静态提示；
# 实际渲染以响应里 chart.chart_type 为准，这里是前端"预计图形"的辅助信息）。
_CHART_TYPE_HINT = {
    "top_diagnoses":       ["bar"],
    "top_procedures":      ["bar"],
    "severity_profile":    ["bar"],
    "population_diff":     ["bar"],
    "pyramid":             ["pyramid"],
    "region_diff":         ["bar"],
    "heatmap":             ["heatmap"],
    "payment_composition": ["pie"],
    "payment_cross":       ["bar"],
    "sankey":              ["sankey"],
    "cost_relation":       ["scatter"],
    "oop_burden":          ["bar"],
    "payment_summary":     ["bar"],
    "profit_difference":   ["bar"],
    "profit_margin":       ["bar"],
    "efficiency_ranking":  ["bar"],
    "composition":         ["bar"],
    "cost_trend":          ["line"],
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
        key = item.get("name") or item.get("key") or "-"
        value = item.get("self_pay_count") or 0
    elif chart_hint == "quality_mortality":
        key = item.get("name") or item.get("key") or "-"
        value = item.get("mortality_rate") or 0
    elif chart_hint == "quality_los":
        key = item.get("name") or item.get("key") or "-"
        value = item.get("avg_los") or 0
    elif chart_hint == "quality_facility":
        key = item.get("name") or item.get("key") or "-"
        value = item.get("count") or 0
    elif chart_hint == "quality_disposition":
        key = item.get("key") or "-"
        value = item.get("count") or 0
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

    # —— 特殊 3：quality_overview 的 data 是 dict（质量 KPI 大屏）——
    if chart_hint == "quality_overview":
        if not isinstance(data, dict) or not data:
            return findings
        findings.append(f"总出院 {data.get('total_records', 0):,} 条 · "
                        f"院内死亡 {data.get('deaths', 0):,} 人")
        findings.append(f"死亡率 {data.get('mortality_rate', 0)}% / "
                        f"平均住院 {data.get('avg_los', 0)} 天")
        findings.append(f"急诊率 {data.get('ed_rate', 0)}% / "
                        f"非医嘱离院率 {data.get('ama_rate', 0)}% / "
                        f"转院率 {data.get('transfer_rate', 0)}%")
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

        # sankey / payment_summary / quality_overview 的 data 是 dict（不是 list），
        # 既不是空也不能按 list 走 Top3 逻辑，统一交给 _build_section_findings 处理
        is_dict_data = chart_hint in ("sankey", "payment_summary", "quality_overview")
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
# ------------------------------------------------------------
# 5.0 范围外判定（依赖 LangChain Agent，不再使用正则规则）
# 平台定位：住院大数据分析，仅回答可映射到分析工具的数据查询。
# 判定权完全交给 LangChain Agent：若本次问答 Agent 未选择 / 调用任何工具
#（即它判断该问题无法映射到数据分析），则视为「非数据分析问题」，
# 直接返回「暂不支持此服务」的优雅说明，完全不调用 P3，也不降级到旧 pipeline。
# 相比正则规则，这种方式不会误伤正常数据查询（false positive），
# 也消除了旧 pipeline 默认 dimension 造成的「答非所问」误路由。
# ------------------------------------------------------------

def _build_out_of_scope_result(question: str, agent_text: str = "") -> dict:
    """Agent 未调用任何工具时构建「暂不支持此服务」结果。

    - agent_text：Agent 自行生成的拒答文本（系统提示词已引导其礼貌拒答，优先采用更自然）；
      为空或过短则回退到平台统一文案。
    - 完全不调用 P3；返回结构化标记供前端区分「数据卡片」与「范围外卡片」。
    """
    suggestions = [
        "2021 年呼吸道疾病住院量前 10",
        "某疾病的住院费用趋势",
        "不同年龄段 / 性别 / 地区的疾病分布",
        "各类支付方式的占比与自付负担",
        "医疗质量指标（死亡率、平均住院日、再入院风险）",
    ]
    if agent_text and len(agent_text.strip()) >= 8:
        answer = agent_text.strip()
    else:
        answer = (
            "🩺 您好，本平台是「智慧医疗大数据与 AI 大模型分析平台」，"
            "聚焦于医院住院患者出院数据的统计与分析（疾病、手术、费用、支付方式、"
            "医疗质量等多维度聚合）。\n\n"
            "您的问题暂不在本平台服务范围内（本平台不提供疾病诊疗建议、用药指导、"
            "个人健康咨询、医保政策或挂号流程等服务）。\n\n"
            "💡 您可以把问题转化为「住院数据分析」类查询，例如：\n"
            "1) 「2021 年呼吸道疾病住院量前 10」\n"
            "2) 「某疾病的住院费用趋势」\n"
            "3) 不同年龄段 / 性别 / 地区的疾病分布\n"
            "4) 各类支付方式的占比与自付负担\n"
            "5) 医疗质量指标（死亡率、平均住院日、再入院风险）"
        )
    intent = {
        "_source": "out_of_scope",
        "scope": "out_of_scope",
        "scope_class": "langchain_no_tool",
        "original_question": question,
    }
    return {
        "question": question,
        "intent": intent,
        "answer": answer,
        "chart": None,
        "scope": "out_of_scope",   # 顶层标记，便于前端区分卡片类型
        "meta": {
            "out_of_scope": True,
            "scope_class": "langchain_no_tool",
            "suggestions": suggestions,
        },
    }


def handle_question(question: str, with_report: bool | str = False,
                    conversation_id: str | None = None,
                    use_llm_intent: bool = True,
                    stream_callback=None) -> dict:
    """AI 智能交互完整闭环。

    with_report 支持三种形式：
      - False：不生成报告（最快）
      - True：同步生成报告（默认方式，慢，但一次性返回全量）
      - "async"：异步生成报告，先返回摘要+图表，报告写入 ASYNC_REPORT_STORE，
                 前端轮询 /api/report/status?report_id=xxx 取结果
    conversation_id 不为空时，启用多轮对话：读取历史上下文 + 记录本轮到历史
    use_llm_intent=True 时，优先用 LangChain Agent（StructuredTool +
    create_tool_calling_agent）做意图识别 + 工具调用；Agent 不可用或失败时
    自动降级到旧 pipeline（parse_intent + call_analysis_api）
    stream_callback：SSE 真流式回调——阶段事件 {"type":"stage","stage":...}
    与摘要 token 事件 {"type":"token","data":piece}；None 为普通 /api/chat。
    """
    _obs_inc("requests_total")
    _t0 = time.time()
    _log_event("request_received", q_len=len(question),
               has_conv=bool(conversation_id))
    _emit_stage(stream_callback, "routing")

    # 0.5 范围外判定已下沉到 LangChain Agent 路径：
    # _handle_question_via_agent 在「Agent 未选择任何工具」时直接返回
    # 「暂不支持此服务」结果（不调用 P3、不降级旧 pipeline）。
    # 因此这里不再做任何前置正则拦截，完全由 Agent 的 tool-calling 决策决定。

    # 0. 优先尝试 LangChain Agent 路径（StructuredTool + create_tool_calling_agent）
    path = "legacy"
    if use_llm_intent and _LANGCHAIN_AVAILABLE and LLM_ENABLED:
        agent_result = _handle_question_via_agent(
            question, with_report=with_report,
            conversation_id=conversation_id,
            stream_callback=stream_callback)
        if agent_result is not None:
            path = "agent"
            _obs_inc("agent_path_total")
            result = agent_result
        else:
            # Agent 失败 → 降级到旧 pipeline（下方继续执行）
            path = "legacy"
            _obs_inc("legacy_path_total")
            logger.info("[handle_question] Agent 降级到旧 pipeline")
    else:
        _obs_inc("legacy_path_total")

    if path == "legacy":
        # —— 旧 pipeline（parse_intent + call_analysis_api，向后兼容）——
        # 1. 意图解析（LLM 优先，带上下文）
        intent = parse_intent(question, conversation_id=conversation_id,
                              use_llm=use_llm_intent)

        # 2. 调用后端分析 API（规则路由，LLM 审查写入 meta，不改变路由）
        api_result = call_analysis_api(intent, question=question)

        # 收尾（摘要/图表/组装/warnings/会话历史/报告）与 Agent 路径共用
        history = MEMORY.get_history(conversation_id)
        result = _finalize_result(
            question, intent, api_result,
            with_report=with_report,
            conversation_id=conversation_id,
            history=history,
            stream_callback=stream_callback,
        )

    _obs_nested_inc("intent_sources", result["intent"].get("_source", "unknown"))
    _log_event("request_done", path=path,
               intent_source=result["intent"].get("_source"),
               chart_hint=result["intent"].get("chart_hint"),
               p3_error=(result.get("meta") or {}).get("error"),
               latency_ms=round((time.time() - _t0) * 1000, 1))
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


def _submit_async_report(api_result: dict, chart: dict, intent: dict = None) -> str:
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
                "intent": intent,
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
            "langchain_agent": {
                "available": _LANGCHAIN_AVAILABLE,
                "tools_count": len(_TOOLS),
                "mode": "native_tool_calling(bind_tools)" if _LANGCHAIN_AVAILABLE else "legacy_pipeline",
            },
            "cors_origins_count": len(CORS_ORIGINS),
            "flask_debug": FLASK_DEBUG,
            # 可观测运行态统计（累计计数器 + 派生指标，见 _get_runtime_stats）
            "runtime": _get_runtime_stats(),
            "dotenv": {
                "loaded_from": _DOTENV_LOADED_FROM,  # None 表示没从文件加载
                "hint": _DOTENV_HINT,  # 有值时表示 python-dotenv 未安装或加载失败
            },
        },
        "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    })


def _parse_chat_body() -> dict:
    """解析 /api/chat（与 /api/chat/stream 共用）请求体，返回统一参数字典。

    返回键：question / with_report / conversation_id / use_llm_intent，
    校验失败时额外带 _error（完整错误 payload，调用方直接 jsonify 返回即可）。
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
    with_report: bool | str = False
    if isinstance(_wr_raw, str):
        _w = _wr_raw.strip().lower()
        if _w == "async":
            with_report = "async"
        elif _w in ("true", "1", "yes", "on"):
            with_report = True
        elif _w in ("false", "0", "no", "off", "", "none", "null"):
            with_report = False
        else:
            return {"question": "", "with_report": False,
                    "conversation_id": None, "use_llm_intent": True,
                    "_error": {
                        "code": 400,
                        "message": (
                            "with_report 参数非法：仅接受 true/false/async"
                            "（字符串大小写不敏感），"
                            f"实际收到 with_report={_wr_raw!r}。"
                            "如需异步生成报告，请传 \"async\"；同步生成传 true；"
                            "不生成传 false 或省略。"),
                        "question": "", "answer": None, "chart": None,
                        "report": None, "meta": {},
                    }}
    else:
        with_report = bool(_wr_raw)

    conversation_id = (body.get("conversation_id") or "").strip() or None
    use_llm_intent = body.get("use_llm_intent", True)  # 默认用 LLM 意图解析

    if not question:
        return {"question": "", "with_report": with_report,
                "conversation_id": conversation_id,
                "use_llm_intent": use_llm_intent,
                "_error": {
                    "code": 400, "message": "请输入问题（question 字段不能为空）",
                    "question": "", "answer": "⚠️ 请先输入您的问题哦~",
                    "chart": None, "report": None, "meta": {},
                }}

    # 编码自检：如果 question 全是 ASCII 问号/数字/标点（没中文也没英文单词），
    # 极可能是 PowerShell 5.1 把中文 ConvertTo-Json 编码成了 "???"
    import re as _re_enc
    has_cjk = bool(_re_enc.search(r"[\u4e00-\u9fff]", question))
    has_english_word = bool(_re_enc.search(r"[A-Za-z]{3,}", question))
    looks_like_lost_encoding = (
        not has_cjk and not has_english_word
        and "?" in question
        and len(question.replace("?", "").strip()) < 5
    )
    if looks_like_lost_encoding:
        return {"question": question, "with_report": with_report,
                "conversation_id": conversation_id,
                "use_llm_intent": use_llm_intent,
                "_error": {
                    "code": 400,
                    "message": (
                        "question 字段疑似编码丢失（收到全是 '?' 的字符串，"
                        "没有中文字符）。通常是 PowerShell 5.1 的 "
                        "ConvertTo-Json 把中文转成了 '?'。请改用 PowerShell 7+、"
                        "curl -d UTF-8 body 或 Postman。"),
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
                        '   curl -X POST http://127.0.0.1:5001/api/chat '
                        '-H "Content-Type: application/json" '
                        '-d "{\\"question\\":\\"不同支付方式的费用占比如何？\\"}"'),
                    "chart": None, "report": None, "meta": {},
                }}

    return {"question": question, "with_report": with_report,
            "conversation_id": conversation_id,
            "use_llm_intent": use_llm_intent}


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
    body = _parse_chat_body()
    question = body.get("question", "")
    with_report = body.get("with_report", False)
    conversation_id = body.get("conversation_id")
    use_llm_intent = body.get("use_llm_intent", True)
    error_payload = body.get("_error")

    if error_payload:
        return jsonify(error_payload), 200

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
    except requests.exceptions.Timeout as e:
        # P3 超时：504 单独提示（区别于 502 连不上）
        logger.warning("P3 分析服务超时：%s", e)
        return jsonify({
            "code": 504,
            "message": f"分析服务（P3）响应超时：{str(e)}，请稍后重试或简化查询条件",
            "question": question,
            "answer": (
                f"⏱️ 后端分析服务响应超时（{ANALYSIS_API}）。\n"
                "可能是查询数据量过大或 P3 服务繁忙，请稍后重试，或换一个范围更小的问题。"
            ),
            "chart": None,
            "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
        }), 200
    except requests.exceptions.ConnectionError as e:
        # P3 连不上：502
        logger.warning("P3 分析服务连接失败：%s", e)
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
    except requests.exceptions.RequestException as e:
        # 其他 requests 异常（如 HTTPError）：502 兜底
        logger.warning("P3 分析服务请求异常：%s: %s", type(e).__name__, e)
        return jsonify({
            "code": 502,
            "message": f"分析服务（P3）请求异常：{type(e).__name__}: {str(e)}",
            "question": question,
            "answer": (
                f"⚠️ 后端分析服务请求异常（{type(e).__name__}）。\n"
                f"请检查 P3 服务状态：{ANALYSIS_API}"
            ),
            "chart": None,
            "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
        }), 200
    except (KeyError, ValueError, TypeError) as e:
        # 业务异常：意图解析错误/参数缺失/数据结构不符 → 400 友好提示
        # 这些通常是用户问题无法理解或 P3 返回结构异常，不算系统故障
        logger.warning("业务异常（意图/参数/数据结构）：%s: %s", type(e).__name__, e, exc_info=True)
        return jsonify({
            "code": 400,
            "message": (
                f"无法解析您的问题或分析结果异常：{type(e).__name__}: {str(e)}。"
                "请尝试换一种问法，或检查查询条件是否合理。"
            ),
            "question": question,
            "answer": (
                "🤔 您的问题暂时无法解析或分析结果异常。\n"
                "建议：\n"
                "1) 换一种更明确的问法（如「2021年前3种常见疾病是什么」）；\n"
                "2) 检查查询条件是否冲突（如同时筛选矛盾的年龄段）；\n"
                "3) 稍后重试，可能是后端正在维护。"
            ),
            "chart": None,
            "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
        }), 200
    except Exception as e:
        # 未预期异常：500，必须写 ERROR 级日志（含 traceback）便于排查
        logger.error("handle_question 未预期异常：%s: %s", type(e).__name__, e, exc_info=True)
        return jsonify({
            "code": 500,
            "message": f"分析失败：{type(e).__name__}: {str(e)}",
            "question": question,
            "answer": "⚠️ 抱歉，分析过程中出现异常，请检查日志或换个问题再试。",
            "chart": None,
            "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
        }), 200


def _sse_event(event: str, data) -> str:
    """把事件名 + 数据格式化为 SSE 文本块（data 序列化为 JSON，ensure_ascii=False 保留中文）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _emit_stage(stream_callback, stage: str) -> None:
    """向 SSE 流推一个阶段事件（routing/querying/summarizing/charting）。

    前端据此显示"正在分析/查询/生成摘要/生成图表"等进度提示。
    stream_callback 为 None 或回调抛异常时静默忽略（普通 /api/chat 与断连场景）。
    """
    if stream_callback:
        try:
            stream_callback({"type": "stage", "stage": stage})
        except Exception:
            pass


def _sse_ping() -> str:
    """SSE 心跳注释行（以冒号开头的行是注释，客户端忽略），防代理/网关断连。"""
    return ": ping\n\n"


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """SSE 流式版主入口（请求体与 /api/chat 完全一致）。

    事件流（text/event-stream）——SSE 真流式：
      event: start      → data: {"question": ..., "ts": ...}  收到请求，立即推送
      event: stage      → data: {"stage": "routing"|"querying"|"summarizing"|"charting"}
                           阶段进度（前端可显示"正在分析/查询/生成摘要/生成图表"）
      event: token      → data: {"text": "..."}              摘要 LLM 增量 token（逐段）
      event: result     → data: {完整 result（同 /api/chat 成功响应）}
      event: error      → data: {code, message, answer, ...} 校验失败 / 业务异常
      心跳：每 15s 一行 ": ping"（注释行），防连接被代理断开

    前端用法（fetch + ReadableStream 逐行解析，见 P4前端接口契约.md）：
      POST /api/chat/stream  body 同 /api/chat
      Content-Type: text/event-stream
    """
    body = _parse_chat_body()
    question = body.get("question", "")
    with_report = body.get("with_report", False)
    conversation_id = body.get("conversation_id")
    use_llm_intent = body.get("use_llm_intent", True)
    error_payload = body.get("_error")

    t0 = time.time()

    def generate():
        # 0) 立即推 start（前端可立刻显示"正在分析"）
        yield _sse_event("start", {
            "question": question,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

        # 1) 校验失败：直接 error，不走 handle_question
        if error_payload:
            yield _sse_event("error", error_payload)
            return

        # 2) 后台线程执行 handle_question，通过队列实时转发 阶段/摘要 token 事件；
        #    主生成器从队列取事件并 yield，空闲时发心跳保活（SSE 真流式）。
        ev_queue = queue.Queue()

        def runner():
            try:
                result = handle_question(
                    question,
                    with_report=with_report,
                    conversation_id=conversation_id,
                    use_llm_intent=use_llm_intent,
                    stream_callback=ev_queue.put,  # {"type":"stage"|"token","data":...}
                )
                ev_queue.put({"type": "result", "data": result})
            except requests.exceptions.Timeout as e:
                ev_queue.put({"type": "error", "data": {
                    "code": 504,
                    "message": f"分析服务（P3）响应超时：{str(e)}，请稍后重试或简化查询条件",
                    "question": question,
                    "answer": "⏱️ 后端分析服务响应超时，可能是查询数据量过大或 P3 服务繁忙，请稍后重试。",
                    "chart": None,
                    "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
                }})
            except requests.exceptions.ConnectionError as e:
                ev_queue.put({"type": "error", "data": {
                    "code": 502,
                    "message": f"分析服务（P3）连接失败：{str(e)}",
                    "question": question,
                    "answer": "⚠️ 后端分析服务暂时连不上，请确认 P3 是否已启动。",
                    "chart": None,
                    "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
                }})
            except requests.exceptions.RequestException as e:
                ev_queue.put({"type": "error", "data": {
                    "code": 502,
                    "message": f"分析服务（P3）请求异常：{type(e).__name__}: {str(e)}",
                    "question": question,
                    "answer": "⚠️ 后端分析服务请求异常，请检查 P3 状态。",
                    "chart": None,
                    "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
                }})
            except (KeyError, ValueError, TypeError) as e:
                ev_queue.put({"type": "error", "data": {
                    "code": 400,
                    "message": f"无法解析您的问题或分析结果异常：{type(e).__name__}: {str(e)}",
                    "question": question,
                    "answer": "🤔 您的问题暂时无法解析或分析结果异常，建议换一种更明确的问法。",
                    "chart": None,
                    "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
                }})
            except Exception as e:
                logger.error("handle_question(SSE) 未预期异常：%s: %s",
                             type(e).__name__, e, exc_info=True)
                ev_queue.put({"type": "error", "data": {
                    "code": 500,
                    "message": f"分析失败：{type(e).__name__}: {str(e)}",
                    "question": question,
                    "answer": "⚠️ 抱歉，分析过程中出现异常，请检查日志或换个问题再试。",
                    "chart": None,
                    "meta": {"p4_total_ms": int((time.time() - t0) * 1000)},
                }})

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        last_beat = time.time()
        while True:
            try:
                ev = ev_queue.get(timeout=1)
            except queue.Empty:
                if not t.is_alive():
                    break  # 线程已结束且无待取事件（异常已在 runner 内入队）
                if time.time() - last_beat >= 15:
                    yield _sse_ping()
                    last_beat = time.time()
                continue
            ev_type = ev.get("type")
            if ev_type == "stage":
                yield _sse_event("stage", {"stage": ev.get("stage")})
            elif ev_type == "token":
                yield _sse_event("token", {"text": ev.get("data", "")})
            elif ev_type == "result":
                result = ev["data"]
                result["code"] = 0
                result["message"] = "success"
                result["meta"] = dict(result.get("meta", {}))
                result["meta"]["p4_total_ms"] = int((time.time() - t0) * 1000)
                yield _sse_event("result", result)
                return
            elif ev_type == "error":
                yield _sse_event("error", ev["data"])
                return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 关 nginx 缓冲，让事件即时到前端
            "Connection": "keep-alive",
        },
    )


@app.route("/api/suggested-questions", methods=["GET"])
def suggested_questions():
    """P5 前端『推荐问题』数据源：覆盖全部 21 个分析工具，单一来源。

    返回按 category 分组的推荐问法，前端可用于『猜你想问』按钮。
    数据与 Agent 系统提示词 few-shot 共用 SUGGESTED_QUESTIONS，保证前后端一致。
    """
    cats: dict[str, list] = {}
    for item in SUGGESTED_QUESTIONS:
        cats.setdefault(item["category"], []).append(
            {"tool": item["tool"], "question": item["question"]})
    return jsonify({
        "code": 0,
        "message": "success",
        "total": len(SUGGESTED_QUESTIONS),
        "categories": [
            {"name": name, "items": items}
            for name, items in cats.items()
        ],
    }), 200


def _safe_args_schema(tool) -> dict:
    """安全提取 LangChain StructuredTool 的 args_schema（JSON Schema 兼容 dict）。

    StructuredTool.args 是 Pydantic 模型生成的 JSON Schema（含 properties/required/
    $defs 等），前端可据此自动渲染参数表单。个别工具 schema 可能含不可 JSON 序列化
    的对象（如特殊 Field），这里 try/except 兜底返回空。
    """
    try:
        schema = tool.args if hasattr(tool, "args") else {}
        if not isinstance(schema, dict):
            schema = {}
        # 兼容 pydantic v1/v2 生成的 schema 顶层结构
        if "properties" not in schema and hasattr(tool, "args_schema"):
            try:
                schema = tool.args_schema.model_json_schema()
            except Exception:
                schema = {}
        return schema
    except Exception:
        return {}


@app.route("/api/meta/dimensions", methods=["GET"])
def meta_dimensions():
    """P5 前端『分析能力元信息』数据源（与 P3 的 /api/v1/meta/dimensions 互补）。

    P3 的 meta/dimensions 返回维度枚举值（诊断/术式/支付方式等实际取值），
    本端点返回 P4 的「能力目录 + 参数 schema + 中英字典」：
      - capabilities：每个 chart_hint 的 endpoint / 中文标题 / 图表类型 / 超时
      - tools：每个 LangChain 工具的 args_schema（前端可自动渲染参数表单）
      - dictionaries：指标/维度/严重程度的中英文映射、调色板
      - sources：当前路由来源（langchain_agent / rules 等，供前端展示能力状态）

    全部从 agent.py 现有注册表自动聚合，无重复维护；新增接口后自动出现。
    """
    # 1) 能力目录：ROUTE_TABLE（endpoint/build/timeout）∪ CHART_BUILDERS（图表类型）
    capabilities = []
    for hint, route in sorted(ROUTE_TABLE.items()):
        chart_types = []
        builder = CHART_BUILDERS.get(hint)
        if builder is not None:
            # 无法静态拿到 chart_type（要跑数据），这里给出常见类型提示由前端兜底；
            # 实际渲染以响应里 chart.chart_type 为准。
            chart_types = _CHART_TYPE_HINT.get(hint, [])
        capabilities.append({
            "chart_hint": hint,
            "title_zh": CHART_HINT_TITLE_ZH.get(hint, hint),
            "endpoint": route["endpoint"],
            "timeout": route["timeout"],
            "chart_types": chart_types or ["bar"],
        })

    # 2) 工具参数 schema（前端自动渲染表单用）
    tools = []
    for t in _TOOLS:
        name = getattr(t, "name", "")
        tools.append({
            "tool": name,
            "description": getattr(t, "description", ""),
            "args_schema": _safe_args_schema(t),
        })

    # 3) 中英字典 + 调色板 + 严重程度
    dictionaries = {
        "metrics": METRIC_ZH,
        "dimensions": DIMENSION_ZH,
        "p3_dimensions": P3_DIM_ZH,
        "severity": SEVERITY_ZH,
        "severity_order": SEVERITY_ORDER,
        "colors": COLORS,
    }

    return jsonify({
        "code": 0,
        "message": "success",
        "data": {
            "capabilities": capabilities,
            "tools": tools,
            "dictionaries": dictionaries,
            "sources": {
                "langchain_agent": bool(_LANGCHAIN_AVAILABLE and LLM_ENABLED),
                "llm_enabled": bool(LLM_ENABLED),
                "tools_count": len(_TOOLS),
            },
        },
        "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
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
        logger.warning("%s", _DOTENV_HINT)
    if _DOTENV_LOADED_FROM:
        logger.info("[dotenv] ✅ 配置已从文件加载：%s", _DOTENV_LOADED_FROM)
    elif not _DOTENV_HINT:
        logger.info("[dotenv] ℹ️ 未找到 .env 文件，全部配置从系统环境变量读取")
    if "--selftest" in sys.argv:
        # 综合离线自测：路由表 + 图表 + 摘要 + 报告 4 套测试一起跑
        # 用样例数据，不依赖 LLM/P3，适合 CI 和本地健康检查
        import subprocess as _sp
        logger.info("=" * 70)
        logger.info("[本地自测] 综合离线测试套件（不依赖 LLM/P3）")
        logger.info("  INTENT_CACHE_VERSION = %r（旧缓存将自动失效）", INTENT_CACHE_VERSION)
        logger.info("  LLM_ENABLED = %s", LLM_ENABLED)
        logger.info("=" * 70)
        _test_files = [
            "test_route_table.py",      # 19 例：13 chart_hint 路由 + 2 多轮 + 3 反例
            "test_chart_builders.py",   # 13 例：13 种 chart_hint 的 ECharts option 构造
            "test_summary_builders.py", # 13 例：13 种 chart_hint 的中文摘要
            "test_report_builders.py",  # 15 例：13 种 chart_hint + 2 旧用例的报告 section
            "test_extract_json.py",     # 14 例：_extract_json_from_llm_output 公共函数
        ]
        _all_passed = True
        for _t in _test_files:
            logger.info(">>> 运行 %s", _t)
            logger.info("-" * 70)
            try:
                _r = _sp.run(
                    [sys.executable, _t],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                if _r.returncode != 0:
                    _all_passed = False
                    logger.error("  ❌ %s 退出码 %s", _t, _r.returncode)
                else:
                    logger.info("  ✅ %s 通过", _t)
            except FileNotFoundError:
                logger.warning("  ⚠️  %s 不存在，跳过", _t)
            except Exception as _e:
                _all_passed = False
                logger.error("  ❌ %s 执行异常：%s: %s", _t, type(_e).__name__, _e, exc_info=True)
        logger.info("=" * 70)
        if _all_passed:
            logger.info("[自测] ✅ 全部 %s 套测试通过", len(_test_files))
            logger.info("[自测] ✅ INTENT_CACHE_VERSION=%r 已就绪，旧缓存会自动失效", INTENT_CACHE_VERSION)
        else:
            logger.error("[自测] ❌ 有失败用例，请查看上方输出")
            sys.exit(1)
    elif "--selftest-e2e" in sys.argv:
        # 端到端自测：走真实 LLM + P3，需要服务可用
        q = "2021年哪类疾病的平均住院时长最长？前5名"
        logger.info("=" * 60)
        logger.info("[端到端自测] 问题：%s", q)
        logger.info("  LLM_ENABLED = %s  LLM_MODEL_ID = %s", LLM_ENABLED, LLM_MODEL_ID)
        logger.info("  ANALYSIS_API = %s", ANALYSIS_API)
        logger.info("=" * 60)
        result = handle_question(q, with_report=True)
        # 端到端结果用 print 输出 JSON（避免 logger 把 \n 当多行渲染）
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        port = int(os.getenv("P4_PORT", "5001"))
        logger.info("🚀 P4 AI 交互服务启动中...")
        logger.info("   监听地址：http://127.0.0.1:%s", port)
        logger.info("   主入口接口：POST http://127.0.0.1:%s/api/chat", port)
        logger.info("   健康检查：GET  http://127.0.0.1:%s/api/health", port)
        logger.info("   会话列表：GET  http://127.0.0.1:%s/api/conversations", port)
        logger.info("   历史详情：GET  http://127.0.0.1:%s/api/conversation/history?conversation_id=xxx", port)
        logger.info("   依赖 P3 服务：%s", ANALYSIS_API)
        logger.info("   本地自测命令：python agent.py --selftest（离线）/ --selftest-e2e（端到端）")
        logger.info("   CORS 白名单：%s", CORS_ORIGINS)
        logger.info("   会话存储：%s", SESSION_BACKEND)
        logger.info("   会话历史轮数：MAX_HISTORY_TURNS=%s（环境变量可调，Redis 后端零成本）", MAX_HISTORY_TURNS)
        logger.info("   LLM 多轮上下文轮数：MULTITURN_HISTORY_TURNS=%s（传给 LLM/Agent 的历史轮数，环境变量可调）", MULTITURN_HISTORY_TURNS)
        logger.info("   意图缓存版本：%s（升级路由表后旧缓存自动失效）", INTENT_CACHE_VERSION)
        llm_status = "✅ 已启用" if LLM_ENABLED else "❌ 未启用（请检查 LLM_API_KEY 环境变量）"
        logger.info("   LLM 状态：%s", llm_status)
        if LLM_ENABLED:
            logger.info("   LLM 模型：%s", LLM_MODEL_ID)
            if LLM_MODEL_ID_SMALL:
                logger.info("   LLM 小模型：%s", LLM_MODEL_ID_SMALL)
            logger.info("   LLM Base URL：%s", LLM_BASE_URL)
            # LangChain Agent 状态
            agent_status = "✅ 已启用（原生 tool-calling：ChatOpenAI.bind_tools，%d 个 StructuredTool）" % len(_TOOLS) \
                if _LANGCHAIN_AVAILABLE else \
                "⚠️ 未安装 langchain（pip install langchain langchain-openai），将使用旧 pipeline"
            logger.info("   LangChain Agent：%s", agent_status)
        if _DOTENV_LOADED_FROM:
            logger.info("   .env 文件：%s", _DOTENV_LOADED_FROM)
        else:
            logger.info("   .env 文件：未使用（所有配置来自环境变量）")
        app.run(host="0.0.0.0", port=port, debug=FLASK_DEBUG)
