# -*- coding: utf-8 -*-
"""
P4 · 多轮对话 + LLM 意图解析 专项测试脚本

模拟一个真实的连续对话场景，验证：
  1. 第一轮：独立问题，LLM 解析意图
  2. 第二轮：追问（"那费用呢"），LLM 应该继承上轮的维度和年份
  3. 第三轮：换维度（"按年龄段看"），LLM 应该只改维度，保留年份
  4. 第四轮：规则引擎兜底测试（use_llm_intent=False）

不依赖 MySQL/P3，用 mock 数据。
"""
import json
import os
import sys
import time
import uuid

import importlib.util
spec = importlib.util.spec_from_file_location("agent_mod", os.path.join(os.path.dirname(__file__), "agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


# 模拟 P3 的不同返回（根据 intent 动态生成）
def make_mock_api_result(intent: dict) -> dict:
    dim = intent.get("dimension", "ccsr_diagnosis")
    metric = intent.get("metric", "count")
    year = intent.get("filters", {}).get("year")

    if metric == "total_charges":
        data = [
            {"key": "PNEUMONIA (肺炎)", "value": 12345678.50, "count": 12345},
            {"key": "COVID-19 (新冠)", "value": 9876543.20, "count": 5893},
            {"key": "SEPSIS (脓毒症)", "value": 8765432.10, "count": 8901},
        ]
        meta_metric = "total_charges"
    elif metric == "avg_length_of_stay":
        data = [
            {"key": "PNEUMONIA (肺炎)", "value": 7.2, "count": 12345},
            {"key": "COVID-19 (新冠)", "value": 9.5, "count": 5893},
            {"key": "SEPSIS (脓毒症)", "value": 6.8, "count": 8901},
        ]
        meta_metric = "avg_length_of_stay"
    elif metric == "total_charges" and dim == "age_group":
        data = [
            {"key": "70 or Older", "value": 812900345.20, "count": 342118},
            {"key": "50 to 69", "value": 678234567.80, "count": 567890},
        ]
        meta_metric = "total_charges"
    else:
        data = [
            {"key": "PNEUMONIA (肺炎)", "value": 12345, "count": 12345},
            {"key": "COVID-19 (新冠)", "value": 5893, "count": 5893},
            {"key": "SEPSIS (脓毒症)", "value": 8901, "count": 8901},
        ]
        meta_metric = metric

    year_suffix = f"{year}年" if year else "全部年份"
    return {
        "code": 0,
        "message": "success",
        "data": data,
        "meta": {
            "dimension": dim,
            "metric": meta_metric,
            "total_records": 500000,
            "query_ms": 96,
            "year": year,
        },
    }


def main():
    print("=" * 70)
    print("🧪 P4 多轮对话 + LLM 意图解析 专项测试")
    print("=" * 70)
    print(f"  LLM 启用: {agent.LLM_ENABLED}")
    print(f"  LLM 模型: {agent.LLM_MODEL_ID}")
    print()

    # 临时替换 call_analysis_api，用 mock 数据
    original_call = agent.call_analysis_api
    def mock_call(intent):
        return make_mock_api_result(intent)
    agent.call_analysis_api = mock_call

    conversation_id = f"test-{uuid.uuid4().hex[:8]}"
    print(f"  会话 ID: {conversation_id}")
    print(f"  （所有对话共用这个 ID，实现上下文继承）")
    print()

    # 4 轮连续对话
    conversations = [
        {
            "question": "2021年哪类疾病的平均住院时长最长？",
            "use_llm_intent": True,
            "expect": "应该解析出 dimension=ccsr_diagnosis, metric=avg_length_of_stay, year=2021",
        },
        {
            "question": "那费用呢？",
            "use_llm_intent": True,
            "expect": "追问！应该继承 dimension=ccsr_diagnosis 和 year=2021，只改 metric=total_charges",
        },
        {
            "question": "按年龄段看看",
            "use_llm_intent": True,
            "expect": "换维度！dimension=age_group，但应该继承 year=2021 和 metric=total_charges",
        },
        {
            "question": "换成人数",
            "use_llm_intent": False,
            "expect": "规则引擎兜底（use_llm_intent=False），应该继承 dimension=age_group, year=2021，metric=count",
        },
    ]

    for i, conv in enumerate(conversations, 1):
        print("=" * 70)
        print(f"  【第 {i} 轮】")
        print(f"  用户问题: {conv['question']}")
        print(f"  LLM 意图解析: {'开启' if conv['use_llm_intent'] else '关闭（规则兜底）'}")
        print(f"  期望: {conv['expect']}")
        print("=" * 70)

        t0 = time.time()
        result = agent.handle_question(
            conv["question"],
            conversation_id=conversation_id,
            use_llm_intent=conv["use_llm_intent"],
        )
        elapsed = time.time() - t0

        intent = result["intent"]
        print(f"\n  ⏱️  耗时: {elapsed:.2f}s")
        print(f"  📋 解析出的意图:")
        print(f"     维度   : {intent.get('dimension')}")
        print(f"     指标   : {intent.get('metric')}")
        print(f"     过滤   : {intent.get('filters')}")
        print(f"     Top N  : {intent.get('top')}")
        print(f"     来源   : {intent.get('_source')} ← llm=大模型解析, rules=规则引擎, rules_fallback=LLM降级")
        print(f"     推理   : {intent.get('_reasoning', '')[:150]}")
        print(f"     对话轮数: {result.get('conversation_turn', '?')}")

        print(f"\n  📝 LLM 生成的回答:")
        for line in result["answer"].split("\n"):
            print(f"     {line}")

        print()

    # 查看完整会话历史
    print("=" * 70)
    print("  📚 完整会话历史")
    print("=" * 70)
    history = agent.MEMORY.get_history(conversation_id)
    print(f"  共 {len(history)} 轮:")
    for i, turn in enumerate(history, 1):
        print(f"  第{i}轮: Q={turn['question']}")
        print(f"        intent={turn['intent']}")
        print()

    # 清理
    agent.MEMORY.clear(conversation_id)
    agent.call_analysis_api = original_call

    print("=" * 70)
    print("✅ 多轮对话测试完成！")
    print("=" * 70)
    print()
    print("💡 验证要点:")
    print("  1. 第2轮「那费用呢」的 intent 应该继承第1轮的 dimension 和 year")
    print("  2. 第3轮「按年龄段看看」应该改 dimension 但保留 year")
    print("  3. 第4轮用规则引擎也能继承上下文（_source=rules）")
    print("  4. 每轮的 conversation_turn 应该递增: 1→2→3→4")


if __name__ == "__main__":
    main()
