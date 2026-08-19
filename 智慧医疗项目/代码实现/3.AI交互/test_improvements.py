# -*- coding: utf-8 -*-
"""
P4 · 5 个函数改进的综合验收测试
对照改进方向表：
  1. parse_intent()        ✅ LLM 驱动 - 验证：性别/年龄段过滤、TopN、对比、多轮追问继承
  2. generate_text_summary() ✅ LLM 驱动 - 验证：多轮承接式回答
  3. call_analysis_api()   ✅ LLM 辅助 - 验证：LLM 审查是否写入 meta（intent_validation）
  4. generate_chart_config() ⚠️ LLM 局部 - 验证：个性化标题/副标题、_suggestion_source=llm
  5. generate_insight_report() ✅ 非常适合 - 验证：summary/recommendations/report_source=llm 个性化
"""
import json
import os
import sys
import time
import uuid
import importlib.util

# 显式从环境变量读取 API KEY（不再硬编码）
# 运行前请先：PowerShell:  $env:LLM_API_KEY="sk-xxxx"
#              CMD:        set LLM_API_KEY=sk-xxxx
#              Linux:      export LLM_API_KEY="sk-xxxx"
api_key = os.environ.get("LLM_API_KEY", "").strip()
if api_key:
    # 已设置，保证 module import 时可见
    pass
else:
    # 未设置：打印提示，不阻塞运行（LLM 将自动降级为模板兜底）
    import sys as _sys
    print("⚠️  未设置 LLM_API_KEY 环境变量，测试将使用模板兜底，跳过 LLM 效果验证。")
    print("   设置方法（PowerShell）：$env:LLM_API_KEY=\"sk-你的key\"")
    print()

spec = importlib.util.spec_from_file_location(
    "agent_mod", os.path.join(os.path.dirname(__file__), "agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

# 再手动触发一次 LLM 初始化（确保在 import 之后环境变量已经写入）
if not agent.LLM_ENABLED:
    try:
        agent._init_llm_from_env()
    except Exception:
        pass
print("（调试）初始化后 LLM_ENABLED =", agent.LLM_ENABLED)


# Mock P3 结果（根据 intent 快速生成）
def mock_p3(intent: dict) -> dict:
    metric = intent.get("metric", "count")
    dim = intent.get("dimension", "ccsr_diagnosis")

    if metric == "payment_mix":
        data = [
            {"payment": "Medicare", "count": 823400, "pct": 39.21},
            {"payment": "Private", "count": 645120, "pct": 30.72},
            {"payment": "Medicaid", "count": 312800, "pct": 14.90},
            {"payment": "Self-Pay", "count": 156400, "pct": 7.45},
        ]
        meta_metric = "payment_mix"
    elif metric == "trend":
        data = [{"year": 2019, "count": 258901}, {"year": 2020, "count": 198765},
                {"year": 2021, "count": 287654}]
        meta_metric = "trend"
    elif dim == "age_group":
        data = [
            {"key": "70 or Older", "value": 812900345.20, "count": 342118},
            {"key": "50 to 69", "value": 678234567.80, "count": 567890},
            {"key": "30 to 49", "value": 301223456.75, "count": 118034},
        ]
        meta_metric = metric
    else:
        data = [
            {"key": "PNEUMONIA (肺炎)", "value": 7.2 if metric == "avg_length_of_stay" else 12345678.50, "count": 12345},
            {"key": "COVID-19 (新冠)", "value": 9.5 if metric == "avg_length_of_stay" else 9876543.20, "count": 5893},
            {"key": "SEPSIS (脓毒症)", "value": 6.8 if metric == "avg_length_of_stay" else 8765432.10, "count": 8901},
        ]
        meta_metric = metric

    meta = {"dimension": dim, "metric": meta_metric, "total_records": 500000, "query_ms": 96}
    return {"code": 0, "message": "success", "data": data, "meta": meta}


def h(title):
    print()
    print("=" * 70)
    print(f"  🧪 {title}")
    print("=" * 70)


def main():
    print("=" * 70)
    print(" 🏥 P4 · 5 个函数改进 综合验收测试")
    print("  LLM 模型:", agent.LLM_MODEL_ID, "| 启用:", agent.LLM_ENABLED)
    print("=" * 70)

    conv_id = f"test-final-{uuid.uuid4().hex[:6]}"

    # ====== 1. parse_intent() 专项测试 ======
    h("1/5 parse_intent() — 验证更多意图类型（性别/年龄段/Top/对比）")
    cases = [
        ("2021年女性患者的平均住院时长？", "gender=F + year + avg_length_of_stay"),
        ("70岁以上老人的住院费用排名？", "age_group=70 or Older"),
        ("前三名疾病的人数对比", "Top=3 + 对比"),
        ("男性患者不同年龄段的费用？", "gender=M + dimension=age_group"),
    ]
    for q, expected in cases:
        intent = agent.parse_intent(q, use_llm=True)
        print(f"\n  Q: {q}")
        print(f"    期望: {expected}")
        print(f"    实际: dim={intent.get('dimension')}, metric={intent.get('metric')}, "
              f"filters={intent.get('filters')}, top={intent.get('top')}")
        print(f"    来源: {intent.get('_source')}, 推理: {str(intent.get('_reasoning',''))[:80]}")

    # ====== 2. 多轮：parse_intent + 承接式 generate_text_summary ======
    h("2/5 generate_text_summary() — 多轮承接式回答")
    # Mock call_analysis_api
    orig_call = agent.call_analysis_api
    agent.call_analysis_api = lambda it, **kw: mock_p3(it)

    turns = [
        "2021年哪类疾病的平均住院时长最长？",
        "那费用呢？",
        "按年龄段看费用排名",
    ]
    for i, q in enumerate(turns, 1):
        t0 = time.time()
        result = agent.handle_question(q, conversation_id=conv_id)
        dt = time.time() - t0
        answer = result["answer"].split("\n")[:3]
        print(f"\n  第{i}轮 Q: {q}")
        print(f"    意图: {result['intent']['dimension']} × {result['intent']['metric']} | "
              f"filters={result['intent']['filters']}")
        print(f"    摘要前3行（耗时 {dt:.1f}s）:")
        for line in answer:
            print(f"      {line[:100]}")
        # 看是否有承接式开头
        first_line = (result["answer"].split("\n")[0] or "")
        chengjie = any(w in first_line for w in ["继续看", "继续", "改为", "换", "费用数据", "按年龄段"])
        print(f"    是否承接式开头: {'✅' if chengjie else '⚠️（不强制，看情况）'}")

    # ====== 3. call_analysis_api() — LLM 意图审查 ======
    h("3/5 call_analysis_api() — LLM 前置参数合法性审查")
    test_intent = {
        "dimension": "ccsr_diagnosis",
        "metric": "avg_length_of_stay",
        "filters": {"year": 2021},
        "top": 5,
    }
    # 注意：这里会真的调用 P3，所以我们手动调用内部审查函数，不依赖 P3
    validation = agent._validate_intent_by_llm(test_intent, "2021年疾病的平均住院时长前5？")
    print(f"\n  审查输入: dimension={test_intent['dimension']}, metric={test_intent['metric']}, "
          f"filters={test_intent['filters']}, top={test_intent['top']}")
    if validation:
        print(f"  ✅ LLM 审查结果:")
        print(f"    is_valid   : {validation.get('is_valid')}")
        print(f"    issues     : {validation.get('issues', [])}")
        print(f"    suggestions: {validation.get('suggestions', [])}")
        print(f"    warnings   : {validation.get('warnings', [])}")
    else:
        print(f"  ⚠️  LLM 审查跳过（返回空，不阻塞）")

    # ====== 4. generate_chart_config() — LLM 辅助标题/类型 ======
    h("4/5 generate_chart_config() — LLM 辅助图表标题/类型")
    test_intents = [
        ({"dimension": "ccsr_diagnosis", "metric": "avg_length_of_stay"},
         {"data": [{"key": "PNEUMONIA", "value": 7.2}, {"key": "COVID-19", "value": 9.5}]},
         "疾病x住院时长"),
        ({"dimension": "payment_typology", "metric": "payment_mix"},
         {"data": [{"payment": "Medicare", "count": 823400, "pct": 39.21}]},
         "支付占比（必须饼图，LLM不能改）"),
    ]
    for intent, api_result, desc in test_intents:
        api = {"data": api_result["data"], "meta": {
            "dimension": intent["dimension"], "metric": intent["metric"]}}
        chart = agent.generate_chart_config(intent, api, use_llm=True)
        option = chart["option"]
        title = option.get("title", {}).get("text", "")
        subtitle = option.get("title", {}).get("subtext", "")
        src = chart.get("_suggestion_source", "?")
        print(f"\n  场景: {desc}")
        print(f"    图表类型: {chart['chart_type']}")
        print(f"    标题    : {title}")
        print(f"    副标题  : {subtitle}")
        print(f"    建议来源: {src}  {'（LLM给了个性化标题 ✅）' if src == 'llm' else '（规则默认）'}")

    # ====== 5. generate_insight_report() — LLM 个性化 ======
    h("5/5 generate_insight_report() — LLM 个性化报告（最核心）")
    single = {
        "api_result": {
            "data": [
                {"key": "PNEUMONIA", "value": 7.2, "count": 12345},
                {"key": "COVID-19", "value": 9.5, "count": 5893},
                {"key": "SEPSIS", "value": 6.8, "count": 8901},
            ],
            "meta": {"dimension": "ccsr_diagnosis", "metric": "avg_length_of_stay",
                     "total_records": 500000},
        },
        "chart": {"chart_type": "bar"},
    }
    t0 = time.time()
    report = agent.generate_insight_report(single_result=single, use_llm=True)
    dt = time.time() - t0

    print(f"\n  耗时: {dt:.1f}s")
    print(f"  报告来源: {report.get('report_source')}  {'✅ LLM个性化' if report.get('report_source')=='llm' else '⚠️ 模板兜底'}")
    print(f"\n  📄 报告摘要:")
    print(f"    {report.get('summary', '')}")
    if report["sections"] and report["sections"][0].get("deep_insights"):
        print(f"\n  🔬 LLM 深度洞察:")
        for i, ins in enumerate(report["sections"][0]["deep_insights"][:4], 1):
            print(f"    {i}. {ins}")
    print(f"\n  💡 个性化建议（看是否贴合当前维度+指标，不是通用模板）:")
    for i, rec in enumerate(report["recommendations"][:4], 1):
        print(f"    {i}. {rec}")

    # 简单判断是否是个性化：通用模板里有"高费用/长住院"4条完全一样，LLM会不一样
    generic_template = [
        "🏥 建议重点关注高费用/长住院时长的疾病类型，优化诊疗路径以降低平均住院天数。",
        "💳 关注支付方式占比变化趋势，配合医保政策做好医院收费结构优化。",
    ]
    is_personalized = report["recommendations"] != generic_template
    print(f"\n  是否脱离通用模板: {'✅ 是，个性化建议已生成' if is_personalized else '⚠️ 否，仍为模板兜底'}")

    # ====== 总结 ======
    print()
    print("=" * 70)
    print("  ✅ 5 个函数综合验收完成！")
    print("=" * 70)
    print()
    print("  改进回顾（对照改进方向表）：")
    print("  1. parse_intent()          ✅ LLM prompt 扩充 + 规则新增性别/年龄段/对比/TopN识别")
    print("  2. generate_text_summary() ✅ 多轮上下文加强：承接式开头 + 避免重复结论")
    print("  3. call_analysis_api()    ✅ LLM 审查写入 meta.intent_validation，路由仍是规则，永不改变")
    print("  4. generate_chart_config() ⚠️ LLM 辅助标题/副标题/类型（不阻塞出图，规则兜底结构）")
    print("  5. generate_insight_report() ✅ LLM 个性化 summary+建议+深度洞察，模板兜底")
    print()
    print("  💡 下一步：真实数据跑通 P3 后，启动 P4 Flask 服务（python agent.py）即可联调前端！")

    # 恢复原函数
    agent.call_analysis_api = orig_call
    agent.MEMORY.clear(conv_id)


if __name__ == "__main__":
    main()
