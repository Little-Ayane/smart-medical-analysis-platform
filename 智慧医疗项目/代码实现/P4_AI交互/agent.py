# -*- coding: utf-8 -*-
"""
P4 · AI 智能交互模块
功能：LangChain AI Agent —— 意图识别 -> 智能工具调用 -> 文本生成
技术：LangChain / LLM
说明：LLM 可切换云端模型或本地开源模型（Qwen/BaiChuan）
"""
import json
import os

import requests

# ------------------------------------------------------------
# 1. 工具定义：调用 P3 分析服务 API
# ------------------------------------------------------------
ANALYSIS_API = os.getenv("ANALYSIS_API", "http://127.0.0.1:5000/api/v1")

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
    "性别": "gender",
    "年份": "discharge_year", "年": "discharge_year",
    "疾病": "ccsr_diagnosis", "诊断": "ccsr_diagnosis",
    "医院": "facility", "机构": "facility",
    "支付": "payment_typology", "支付方式": "payment_typology",
    "严重程度": "severity", "病情": "severity",
}

METRIC_KEYWORDS = {
    "平均住院时长": "avg_length_of_stay", "住院时长": "avg_length_of_stay",
    "住院天数": "avg_length_of_stay",
    "总费用": "total_charges", "费用": "total_charges", "花费": "total_charges",
    "平均费用": "avg_charges",
    "人数": "count", "数量": "count", "多少": "count",
    "占比": "payment_mix", "支付方式": "payment_mix",
    "趋势": "trend", "变化": "trend",
}


# ------------------------------------------------------------
# 2. 意图解析（规则 + LLM 兜底）
# ------------------------------------------------------------
def parse_intent(question: str) -> dict:
    """从自然语言问题中解析出 维度 / 指标 / 过滤条件 / Top N。"""
    intent = {"dimension": None, "metric": None, "filters": {}, "top": 10}

    # 2.1 指标匹配（优先匹配更长关键词，避免误匹配）
    for kw in sorted(METRIC_KEYWORDS, key=len, reverse=True):
        if kw in question:
            intent["metric"] = METRIC_KEYWORDS[kw]
            break
    # 2.2 维度匹配
    for kw in sorted(DIMENSION_KEYWORDS, key=len, reverse=True):
        if kw in question:
            intent["dimension"] = DIMENSION_KEYWORDS[kw]
            break
    # 2.3 年份过滤（正则抽取 4 位年份）
    import re
    years = re.findall(r"(19|20)\d{2}", question)
    if years:
        intent["filters"]["year"] = int(years[0])
    # 2.4 Top N
    top = re.findall(r"前\s*(\d+)", question)
    if top:
        intent["top"] = int(top[0])

    # 兜底：默认维度
    if not intent["dimension"]:
        intent["dimension"] = "ccsr_diagnosis"
    if not intent["metric"]:
        intent["metric"] = "count"
    return intent


# ------------------------------------------------------------
# 3. 智能工具调用（调用 P3 的 API）
# ------------------------------------------------------------
def call_analysis_api(intent: dict) -> dict:
    """根据意图匹配并调用对应分析 API，返回结构化结果。"""
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

    params.update(intent.get("filters", {}))
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------
# 4. 分析结果文本生成（LLM）
# ------------------------------------------------------------
def generate_text_summary(question: str, intent: dict, api_result: dict) -> str:
    """将结构化分析结果转化为通俗易懂的医疗摘要。

    若配置了 LLM，用 LLM 生成；否则使用规则模板兜底。
    """
    data = api_result.get("data", [])
    meta = api_result.get("meta", {})

    # —— 模板兜底（未接 LLM 时也能输出可读摘要）——
    if not data:
        return "未查询到符合条件的分析结果，请调整查询条件后重试。"

    top_item = data[0]
    key = top_item.get("key") or top_item.get("payment") or top_item.get("year")
    value = top_item.get("value") or top_item.get("avg_los") or top_item.get("count")

    summary = (
        f"针对您的问题“{question}”，共分析 {meta.get('total_records', 0):,} 条住院记录。\n"
        f"其中「{key}」的{meta.get('metric')}指标为 {value}，位列第一。"
    )
    return summary


# ------------------------------------------------------------
# 5. 生成 ECharts 图表配置（供前端渲染）
# ------------------------------------------------------------
def generate_chart_config(intent: dict, api_result: dict) -> dict:
    """根据分析结果类型，生成 ECharts option 配置。"""
    data = api_result.get("data", [])
    metric = intent["metric"]

    # 支付方式/占比 -> 饼图；趋势 -> 折线图；其余 -> 柱状图
    if metric in ("payment_mix",):
        chart_type = "pie"
        option = {
            "title": {"text": "支付方式占比"},
            "series": [{"type": "pie", "radius": "60%",
                        "data": [{"name": r.get("payment"), "value": r.get("count")}
                                 for r in data]}],
        }
    elif metric == "trend":
        chart_type = "line"
        option = {
            "xAxis": {"type": "category", "data": [str(r.get("year")) for r in data]},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": [r.get("count") for r in data]}],
        }
    else:
        chart_type = "bar"
        option = {
            "xAxis": {"type": "category",
                      "data": [str(r.get("key")) for r in data], "axisLabel": {"rotate": 30}},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [r.get("value") for r in data]}],
        }
    return {"chart_type": chart_type, "option": option}


# ------------------------------------------------------------
# 6. 主流程：自然语言 -> 分析结果（文字 + 图表配置）
# ------------------------------------------------------------
def handle_question(question: str) -> dict:
    """AI 智能交互完整闭环。"""
    intent = parse_intent(question)               # 1. 意图解析
    api_result = call_analysis_api(intent)         # 2. 调用后端分析 API
    summary = generate_text_summary(question, intent, api_result)  # 3. 文本摘要
    chart = generate_chart_config(intent, api_result)             # 4. 图表配置
    return {
        "question": question,
        "intent": intent,
        "answer": summary,
        "chart": chart,
        "meta": api_result.get("meta", {}),
    }


if __name__ == "__main__":
    # 本地自测
    q = "2021年哪类疾病的平均住院时长最长？"
    result = handle_question(q)
    print(json.dumps(result, ensure_ascii=False, indent=2))
