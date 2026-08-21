# -*- coding: utf-8 -*-
"""LangChain Agent 重构的单元测试。

覆盖不依赖真实 LLM / P3 服务的纯逻辑，验证 StructuredTool 重构的关键组件：
  1. _parse_observation      —— 工具返回值解析（dict / JSON str / Python repr str）
  2. _reconstruct_intent     —— 工具名 + 参数 → intent 字段映射（13 chart_hint + 3 遗留路由）
  3. _extract_tool_call_from_steps —— 从 intermediate_steps 提取最后一次有效工具调用
  4. _execute_* 工具函数      —— mock requests.get 验证 URL 与参数构造

用法：python test_agent_tools.py
"""
import json
import sys
from unittest import mock

import agent


def _make_action(tool, tool_input):
    """构造一个简易 AgentAction 对象（模仿 langchain 0.2.x 的 AgentAction）。"""
    class FakeAction:
        pass

    a = FakeAction()
    a.tool = tool
    a.tool_input = tool_input
    return a


# ============ 1. _parse_observation ============
def test_parse_observation():
    failed = 0
    cases = [
        ({"data": [1, 2]}, {"data": [1, 2]}, "dict 直接返回"),
        ('{"data": [1, 2]}', {"data": [1, 2]}, "JSON 字符串"),
        ("{'data': [1, 2]}", {"data": [1, 2]}, "Python repr 字符串"),
        ("not json", {}, "非法字符串返回空 dict"),
        (None, {}, "None 返回空 dict"),
    ]
    for raw, expected, desc in cases:
        result = agent._parse_observation(raw)
        if result != expected:
            print(f"[FAIL] _parse_observation: {desc}")
            print(f"       expected={expected!r}, actual={result!r}")
            failed += 1
        else:
            print(f"[PASS] _parse_observation: {desc}")
    return failed


# ============ 2. _reconstruct_intent ============
def test_reconstruct_intent():
    failed = 0
    # (tool_name, args, 期望字段子集)
    cases = [
        # chart_hint 工具
        ("top_diagnoses",
         {"metric": "count", "top": 5, "filters": {"year": 2021}},
         {"chart_hint": "top_diagnoses", "metric": "count", "top": 5,
          "filters": {"year": 2021}}),
        ("top_procedures",
         {"metric": "total_charges", "top": 10},
         {"chart_hint": "top_procedures", "metric": "total_charges", "top": 10}),
        ("severity_profile",
         {"by": "payment", "metric": "count"},
         {"chart_hint": "severity_profile", "by": "payment"}),
        ("population_diff",
         {"dimension": "race", "metric": "count"},
         {"chart_hint": "population_diff", "by": "race"}),  # dimension → by
        ("pyramid", {}, {"chart_hint": "pyramid"}),
        ("heatmap",
         {"dim1": "diagnosis", "dim2": "gender", "metric": "count", "top": 10},
         {"chart_hint": "heatmap", "dim1": "diagnosis", "dim2": "gender"}),
        ("region_diff",
         {"level": "county", "metric": "count"},
         {"chart_hint": "region_diff", "level": "county"}),
        ("payment_composition",
         {"group": "payment2", "metric": "count"},
         {"chart_hint": "payment_composition", "group": "payment2"}),
        ("payment_cross",
         {"dim2": "age_group", "metric": "count"},
         {"chart_hint": "payment_cross", "dim2": "age_group"}),
        ("sankey",
         {"levels": "payment,disease", "top_disease": 5},
         {"chart_hint": "sankey", "levels": "payment,disease"}),
        ("cost_relation",
         {"by": "age_group", "top": 30},
         {"chart_hint": "cost_relation", "by": "age_group", "top": 30}),
        ("oop_burden",
         {"dimension": "age_group", "mode": "any_layer", "top": 15},
         {"chart_hint": "oop_burden", "dimension": "age_group", "mode": "any_layer"}),
        ("payment_summary", {}, {"chart_hint": "payment_summary"}),
        # 遗留路由
        ("general_aggregate",
         {"dimension": "gender", "metric": "count", "top": 10},
         {"chart_hint": None, "dimension": "gender", "metric": "count", "top": 10}),
        ("payment_mix", {},
         {"chart_hint": None, "metric": "payment_mix", "dimension": "payment_typology"}),
        ("trend", {},
         {"chart_hint": None, "metric": "trend", "dimension": "discharge_year"}),
    ]
    for tool_name, args, expected in cases:
        intent = agent._reconstruct_intent(tool_name, args)
        for k, v in expected.items():
            if intent.get(k) != v:
                print(f"[FAIL] _reconstruct_intent {tool_name}")
                print(f"       field {k}: expected={v!r}, actual={intent.get(k)!r}")
                print(f"       full intent={json.dumps(intent, ensure_ascii=False)}")
                failed += 1
                break
        else:
            print(f"[PASS] _reconstruct_intent {tool_name}")
    return failed


# ============ 3. _extract_tool_call_from_steps ============
def test_extract_tool_call_from_steps():
    failed = 0
    # 正常用例：取最后一次调用
    steps = [
        (_make_action("top_diagnoses", {"metric": "count"}), {"data": [1]}),
        (_make_action("sankey", {"levels": "payment,payment2"}), {"data": [2]}),
    ]
    result = agent._extract_tool_call_from_steps(steps)
    expected = ("sankey", {"levels": "payment,payment2"}, {"data": [2]})
    if result != expected:
        print("[FAIL] _extract_tool_call_from_steps 取最后一次调用")
        print(f"       expected={expected!r}, actual={result!r}")
        failed += 1
    else:
        print("[PASS] _extract_tool_call_from_steps 取最后一次调用")

    # 含 error 结果：应跳过并返回 None
    steps_err = [(_make_action("top_diagnoses", {}), {"error": "timeout"})]
    result = agent._extract_tool_call_from_steps(steps_err)
    if result is not None:
        print("[FAIL] _extract_tool_call_from_steps 应跳过 error 结果")
        print(f"       actual={result!r}")
        failed += 1
    else:
        print("[PASS] _extract_tool_call_from_steps 跳过 error 结果")

    # 未知工具名：应跳过并返回 None
    steps_bad = [(_make_action("unknown_tool", {}), {"data": [1]})]
    result = agent._extract_tool_call_from_steps(steps_bad)
    if result is not None:
        print("[FAIL] _extract_tool_call_from_steps 应跳过未知工具")
        print(f"       actual={result!r}")
        failed += 1
    else:
        print("[PASS] _extract_tool_call_from_steps 跳过未知工具")

    # 空列表：返回 None
    result = agent._extract_tool_call_from_steps([])
    if result is not None:
        print("[FAIL] _extract_tool_call_from_steps 空列表应返回 None")
        failed += 1
    else:
        print("[PASS] _extract_tool_call_from_steps 空列表返回 None")
    return failed


# ============ 4. _execute_* 工具函数（mock requests.get）============
def test_execute_tool_params():
    failed = 0
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params or {}
        captured["timeout"] = timeout
        resp = mock.MagicMock()
        resp.json.return_value = {"data": [], "meta": {}}
        resp.raise_for_status.return_value = None
        return resp

    with mock.patch.object(agent.requests, "get", side_effect=fake_get):
        # top_diagnoses：验证 URL + params + filters 透传
        result = agent._execute_top_diagnoses(metric="count", top=5, filters={"year": 2021})
        checks = [
            (result["meta"]["chart_hint"] == "top_diagnoses", "meta.chart_hint"),
            (captured["url"] == f"{agent.ANALYSIS_API}/disease/top-diagnoses", "URL"),
            (captured["params"].get("metric") == "count", "params.metric"),
            (captured["params"].get("top") == 5, "params.top"),
            (captured["params"].get("year") == 2021, "params.year(过滤透传)"),
        ]
        for ok, desc in checks:
            if not ok:
                print(f"[FAIL] _execute_top_diagnoses {desc}")
                print(f"       captured={captured!r}")
                failed += 1
                break
        else:
            print("[PASS] _execute_top_diagnoses URL + params + filters")

        # sankey：验证 timeout=20 与 levels 参数
        agent._execute_sankey(levels="payment,disease", top_disease=5)
        if (captured["url"] != f"{agent.ANALYSIS_API}/payment/sankey"
                or captured["timeout"] != 20
                or captured["params"].get("levels") != "payment,disease"):
            print("[FAIL] _execute_sankey URL/timeout/levels")
            print(f"       captured={captured!r}")
            failed += 1
        else:
            print("[PASS] _execute_sankey URL + timeout=20 + levels")

        # general_aggregate：遗留路由，URL 为 /analysis/aggregate
        agent._execute_general_aggregate(dimension="gender", metric="count", top=10)
        if (captured["url"] != f"{agent.ANALYSIS_API}/analysis/aggregate"
                or captured["params"].get("dimension") != "gender"):
            print("[FAIL] _execute_general_aggregate 遗留路由")
            print(f"       captured={captured!r}")
            failed += 1
        else:
            print("[PASS] _execute_general_aggregate 遗留路由 URL + dimension")

    return failed


def main():
    print("=== 1. _parse_observation ===")
    f1 = test_parse_observation()
    print("\n=== 2. _reconstruct_intent ===")
    f2 = test_reconstruct_intent()
    print("\n=== 3. _extract_tool_call_from_steps ===")
    f3 = test_extract_tool_call_from_steps()
    print("\n=== 4. _execute_* 工具函数 ===")
    f4 = test_execute_tool_params()
    failed = f1 + f2 + f3 + f4
    print()
    if failed:
        print(f"=== {failed} case(s) FAILED ===")
        sys.exit(1)
    else:
        print("=== ALL CASES PASSED ===")


if __name__ == "__main__":
    main()
