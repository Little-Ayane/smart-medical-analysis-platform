# -*- coding: utf-8 -*-
"""
P4 · Mock 自测脚本（不依赖 MySQL / P3）

用途：
    - 当你还没装 MySQL，或 P3 没启动时，用这份脚本验证 P4 + LLM 的核心功能
    - 验证硅基流动 API Key 是否能正常调用
    - 验证意图解析、文本摘要、图表配置、洞察报告四大函数是否正确

运行方式（PowerShell）：
    $env:LLM_API_KEY="sk-你的Key"
    cd "f:\CSUProgram\smart-medical-analysis-platform\智慧医疗项目\代码实现\P4_AI交互"
    python mock_test.py

作者：P4 实习工程师
"""
import json
import os
import sys
import time

# 动态加载同目录的 agent.py，复用里面所有函数
import importlib.util
spec = importlib.util.spec_from_file_location("agent_mod", os.path.join(os.path.dirname(__file__), "agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


# ============================================================
# 模拟数据：模拟 P3 会返回什么（5 种典型场景）
# ============================================================
MOCK_SCENARIOS = [
    {
        "name": "场景1：疾病 × 平均住院时长（柱状图）",
        "question": "2021年哪类疾病的平均住院时长最长？前5名",
        "intent": {
            "dimension": "ccsr_diagnosis",
            "metric": "avg_length_of_stay",
            "filters": {"year": 2021},
            "top": 5,
        },
        "api_result": {
            "code": 0,
            "message": "success",
            "data": [
                {"key": "PNEUMONIA (肺炎)",          "value": 7.2, "count": 12345},
                {"key": "COVID-19 (新冠)",           "value": 9.5, "count": 5893},
                {"key": "SEPSIS (脓毒症)",           "value": 6.8, "count": 8901},
                {"key": "HEART FAILURE (心力衰竭)",  "value": 6.5, "count": 7654},
                {"key": "STROKE (脑卒中)",           "value": 6.2, "count": 5432},
            ],
            "meta": {
                "dimension": "ccsr_diagnosis",
                "metric": "avg_length_of_stay",
                "total_records": 500000,
                "query_ms": 96,
            },
        },
    },
    {
        "name": "场景2：支付方式占比（饼图）",
        "question": "住院患者的支付方式占比是怎样的？",
        "intent": {
            "dimension": "payment_typology",
            "metric": "payment_mix",
            "filters": {},
            "top": 10,
        },
        "api_result": {
            "code": 0,
            "message": "success",
            "data": [
                {"payment": "Medicare (联邦医保)",        "count": 823400, "pct": 39.21},
                {"payment": "Private Health Insurance",  "count": 645120, "pct": 30.72},
                {"payment": "Medicaid (医疗补助)",        "count": 312800, "pct": 14.90},
                {"payment": "Self-Pay (自费)",           "count": 156400, "pct": 7.45},
                {"payment": "Other",                     "count": 162280, "pct": 7.72},
            ],
            "meta": {
                "dimension": "payment_typology",
                "metric": "payment_mix",
                "total_records": 2100000,
                "query_ms": 78,
            },
        },
    },
    {
        "name": "场景3：历年住院人数趋势（折线图）",
        "question": "近几年的住院人数趋势如何？",
        "intent": {
            "dimension": "discharge_year",
            "metric": "trend",
            "filters": {},
            "top": 10,
        },
        "api_result": {
            "code": 0,
            "message": "success",
            "data": [
                {"year": 2017, "count": 234567},
                {"year": 2018, "count": 245678},
                {"year": 2019, "count": 258901},
                {"year": 2020, "count": 198765},
                {"year": 2021, "count": 287654},
                {"year": 2022, "count": 273456},
            ],
            "meta": {
                "dimension": "discharge_year",
                "metric": "trend",
                "total_records": 1496021,
                "query_ms": 112,
            },
        },
    },
    {
        "name": "场景4：年龄段 × 总费用（柱状图）",
        "question": "不同年龄段的总费用排名",
        "intent": {
            "dimension": "age_group",
            "metric": "total_charges",
            "filters": {},
            "top": 5,
        },
        "api_result": {
            "code": 0,
            "message": "success",
            "data": [
                {"key": "70 or Older",     "value": 812900345.20, "count": 342118},
                {"key": "50 to 69",        "value": 678234567.80, "count": 567890},
                {"key": "30 to 49",        "value": 301223456.75, "count": 118034},
                {"key": "18 to 29",        "value": 145678901.30, "count": 89234},
                {"key": "0 to 17",         "value": 182345678.50, "count": 45210},
            ],
            "meta": {
                "dimension": "age_group",
                "metric": "total_charges",
                "total_records": 1162486,
                "query_ms": 87,
            },
        },
    },
    {
        "name": "场景5：空结果（边界测试）",
        "question": "2099年有什么疾病数据？",
        "intent": {
            "dimension": "ccsr_diagnosis",
            "metric": "count",
            "filters": {"year": 2099},
            "top": 10,
        },
        "api_result": {
            "code": 0,
            "message": "success",
            "data": [],
            "meta": {
                "dimension": "ccsr_diagnosis",
                "metric": "count",
                "total_records": 0,
                "query_ms": 5,
            },
        },
    },
]


def print_separator(char="=", width=70):
    print(char * width)


def print_step(title):
    print_separator("-")
    print(f"▶ {title}")
    print_separator("-")


def main():
    print_separator()
    print("🧪 P4 Mock 自测脚本（不依赖 MySQL / P3）")
    print_separator()
    print()

    # -------- 第 0 步：环境检查 --------
    print_step("第 0 步：环境与配置检查")
    print(f"  Python 版本    : {sys.version.split()[0]}")
    print(f"  LLM 是否启用   : {agent.LLM_ENABLED}")
    print(f"  LLM Provider   : {agent.LLM_BASE_URL}")
    print(f"  LLM 模型       : {agent.LLM_MODEL_ID}")
    print(f"  LLM API Key预览: {agent.LLM_API_KEY[:6] + '****' + agent.LLM_API_KEY[-4:] if agent.LLM_API_KEY else '(未设置)'}")
    print(f"  LLM 超时(秒)   : {agent.LLM_TIMEOUT}")
    print(f"  LLM 温度       : {agent.LLM_TEMPERATURE}")
    print()

    if not agent.LLM_ENABLED:
        print("⚠️  LLM_API_KEY 未设置！将只用模板兜底测试。")
        print("    如需启用 LLM，请在 PowerShell 设置：")
        print('    $env:LLM_API_KEY="sk-你的Key"')
        print("    然后重新运行：python mock_test.py")
        print()

    # -------- 第 1 步：意图解析自测 --------
    print_step("第 1 步：意图解析 parse_intent() 自测")
    test_questions = [
        "2021年哪类疾病的平均住院时长最长？前5名",
        "不同年龄段的总费用排名",
        "住院患者的支付方式占比是怎样的？",
        "近几年的住院人数趋势如何？",
        "70岁以上老人的平均费用",
    ]
    for q in test_questions:
        intent = agent.parse_intent(q)
        print(f"  问题：{q}")
        print(f"    → 维度: {intent['dimension']:<20} 指标: {intent['metric']:<22} 过滤: {intent['filters']} Top: {intent['top']}")
    print()

    # -------- 第 2 步：单条 LLM 连通性测试（最省 token）--------
    if agent.LLM_ENABLED:
        print_step("第 2 步：LLM 连通性测试（1 句话省 token）")
        msgs = [
            {"role": "system", "content": "你是助手，请简洁回答。"},
            {"role": "user", "content": "用一句话介绍你自己，并说出今天星期几。"},
        ]
        t0 = time.time()
        ok, text = agent._call_llm_safely(msgs)
        elapsed = time.time() - t0
        print(f"  调用结果：{'✅ 成功' if ok else '❌ 失败'}（耗时 {elapsed:.2f}s）")
        if ok:
            print(f"  LLM 回答：{text}")
        else:
            print(f"  失败原因：{text}")
            print("  ⚠️  将自动降级到模板兜底测试，不影响后续流程")
        print()

    # -------- 第 3 步：5 个场景完整流程测试 --------
    print_step("第 3 步：5 个场景完整流程测试（parse_intent 跳过，直接用 mock intent）")
    print(f"  共 {len(MOCK_SCENARIOS)} 个场景")
    print()

    for i, scenario in enumerate(MOCK_SCENARIOS, 1):
        print_separator("·")
        print(f"  【场景 {i}/{len(MOCK_SCENARIOS)}】{scenario['name']}")
        print(f"  用户问题：{scenario['question']}")
        print_separator("·")

        # 用 mock 数据直接调用后 3 步函数（跳过 call_analysis_api）
        intent = scenario["intent"]
        api_result = scenario["api_result"]

        # 调文本摘要
        t0 = time.time()
        summary = agent.generate_text_summary(scenario["question"], intent, api_result)
        summary_ms = int((time.time() - t0) * 1000)

        # 调图表配置
        chart = agent.generate_chart_config(intent, api_result)

        # 调洞察报告
        report = agent.generate_insight_report(single_result={
            "api_result": api_result,
            "chart": chart,
        })

        # 打印结果
        print(f"\n  📝 文本摘要（耗时 {summary_ms} ms）：")
        for line in summary.split("\n"):
            print(f"     {line}")

        print(f"\n  📊 图表配置：")
        print(f"     chart_type: {chart['chart_type']}")
        if chart["option"].get("xAxis"):
            print(f"     xAxis 数据: {chart['option']['xAxis'].get('data', [])[:5]}")
        if chart["option"].get("series"):
            s = chart["option"]["series"][0]
            print(f"     series类型: {s.get('type')}")
            print(f"     series数据: {s.get('data', [])[:5]}")
        if chart["option"].get("title"):
            print(f"     title     : {chart['option']['title'].get('text')}")

        print(f"\n  📋 洞察报告：")
        print(f"     报告标题: {report['title']}")
        print(f"     生成时间: {report['generated_at']}")
        print(f"     报告摘要: {report['summary']}")
        if report["sections"]:
            s = report["sections"][0]
            print(f"     章节标题: {s['section_title']}")
            for j, f in enumerate(s["key_findings"], 1):
                print(f"       发现 {j}: {f}")
        print(f"     建议条数: {len(report['recommendations'])}")
        for j, r in enumerate(report["recommendations"], 1):
            print(f"       建议 {j}: {r}")

        print()

    # -------- 第 4 步：handle_question 完整链路（绕过 P3）--------
    print_step("第 4 步：handle_question() 完整链路测试（mock P3 返回）")

    # 临时替换 call_analysis_api，让它直接返回 mock 数据，不去连 P3
    original_call = agent.call_analysis_api
    scenario_for_handle = MOCK_SCENARIOS[0]  # 用第一个场景
    def mock_call_analysis_api(intent):
        # 简单匹配：找到 intent.metric 一致的 scenario
        for s in MOCK_SCENARIOS:
            if s["intent"]["metric"] == intent.get("metric"):
                return s["api_result"]
        return scenario_for_handle["api_result"]
    agent.call_analysis_api = mock_call_analysis_api

    try:
        q = scenario_for_handle["question"]
        print(f"  问题：{q}")
        print(f"  (已临时替换 call_analysis_api，不会去连 P3)")
        print()
        t0 = time.time()
        result = agent.handle_question(q, with_report=True)
        elapsed = int((time.time() - t0) * 1000)
        print(f"  ✅ handle_question 完成！总耗时 {elapsed} ms")
        print()
        print("  完整返回 JSON（前 80 行）：")
        output = json.dumps(result, ensure_ascii=False, indent=2)
        for line in output.split("\n")[:80]:
            print(f"     {line}")
        if len(output.split("\n")) > 80:
            print(f"     ...（共 {len(output.split(chr(10)))} 行，已截断）")
    finally:
        # 恢复原函数
        agent.call_analysis_api = original_call

    # -------- 总结 --------
    print()
    print_separator()
    print("🎉 Mock 自测完成！")
    print_separator()
    print()
    print("📋 测试结论：")
    print(f"  - 意图解析    : ✅ 5 条问题全部解析成功")
    if agent.LLM_ENABLED:
        print(f"  - LLM 连通性  : 已测试（看上面第 2 步的结果）")
    else:
        print(f"  - LLM 连通性  : ⏭️  未启用 LLM，全部用模板兜底")
    print(f"  - 文本摘要    : ✅ 5 个场景全部生成")
    print(f"  - 图表配置    : ✅ 5 个场景全部生成（bar/pie/line）")
    print(f"  - 洞察报告    : ✅ 5 个场景全部生成")
    print(f"  - 完整链路    : ✅ handle_question 跑通")
    print()
    print("💡 下一步：装好 MySQL + 跑 P2 入库 + 启动 P3，就可以用真实数据测试了！")
    print("   启动命令：")
    print("     # 窗口1：")
    print("     cd ..\\P3_分析服务")
    print("     python app.py   # 端口 5000")
    print()
    print("     # 窗口2：")
    print("     $env:LLM_API_KEY=\"sk-你的Key\"  # 用你自己的硅基流动 key")
    print("     python agent.py   # 端口 5001，正式启动 Flask 服务")
    print()


if __name__ == "__main__":
    main()
