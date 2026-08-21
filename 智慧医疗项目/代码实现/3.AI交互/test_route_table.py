# -*- coding: utf-8 -*-
"""Step 3 端到端验证：13 个 ROUTE_TABLE 路由的意图识别 + 参数构造。
不调真实 P3 服务（P3 可能没起），只验证 P4 自己的路由决策 + 参数构造是否正确。
用法：python test_route_table.py
"""
import json
import sys

import agent

# (问题, 期望 chart_hint, 期望包含的参数键值)
CASES = [
    # —— top_diagnoses ——
    ("2021年住院人数最多的前3种疾病是什么？",
     "top_diagnoses", {"metric": "count", "top": 3}),
    ("常见疾病有哪些",
     "top_diagnoses", {"metric": "count", "top": 20}),  # BUG 2.2 回归：默认 top=20
    # —— top_procedures ——
    ("前5种高频手术是什么",
     "top_procedures", {"metric": "count", "top": 5}),
    ("高频手术有哪些",
     "top_procedures", {"metric": "count", "top": 20}),  # BUG 2.2 回归：默认 top=20
    # —— severity_profile ——
    ("按年龄段看严重程度构成",
     "severity_profile", {"by": "age_group", "metric": "count"}),
    # —— population_diff（P3 POP_DIMS = gender/race/medical_surgical）——
    ("看一下性别差异",
     "population_diff", {"dimension": "gender", "metric": "count"}),
    ("种族差异如何",
     "population_diff", {"dimension": "race", "metric": "count"}),
    ("内科外科的人群差异",
     "population_diff", {"dimension": "medical_surgical", "metric": "count"}),
    # —— pyramid ——
    ("画个人口金字塔",
     "pyramid", {}),
    # —— region_diff ——
    ("各县住院人数对比",
     "region_diff", {"level": "county"}),  # "县" → county
    # —— heatmap ——
    ("诊断和年龄段的热力图",
     "heatmap", {"dim1": "diagnosis", "dim2": "age_group"}),
    # —— payment_composition ——
    ("看一下二级支付构成",
     "payment_composition", {"group": "payment2"}),
    # —— payment_cross ——
    ("支付方式与年龄段的交叉分析",
     "payment_cross", {"dim2": "age_group"}),
    # —— sankey ——
    ("支付流向桑葚图",
     "sankey", {"levels": "payment,payment2"}),
    # —— cost_relation ——
    ("支付方式的费用关系散点图",
     "cost_relation", {"by": "payment"}),
    # —— oop_burden ——
    ("按年龄段看自付负担",
     "oop_burden", {"dimension": "age_group", "mode": "selfpay1"}),
    # —— payment_summary ——
    ("给我一个KPI总览",
     "payment_summary", {}),
]

# 多轮上下文继承用例：第 2 轮"换成年龄段视角"应继承第 1 轮 chart_hint
MULTITURN_CASES = [
    # 第 1 轮：建立 chart_hint=severity_profile + by=age_group
    ("按年龄段看严重程度构成", None,
     {"chart_hint": "severity_profile", "by": "age_group"}),
    # 第 2 轮：换成支付方式视角（继承 chart_hint，新 by=payment）
    ("换成支付方式视角", "severity_profile",
     {"chart_hint": "severity_profile", "by": "payment"}),
]

# 反例：不该命中 chart_hint 的问句（应走旧 /analysis/* 路由）
NEGATIVE_CASES = [
    # 通用聚合问句，不应被 chart_hint 抢走
    "2021年总费用是多少",  # → metric=total_charges, dimension=discharge_year → 走旧 /analysis/aggregate
    "趋势分析",            # → metric=trend → 走旧 /analysis/trend
    "支付方式占比",        # → metric=payment_mix → 走旧 /analysis/payment-mix
]


def run_positive():
    failed = 0
    for i, (q, expected_hint, expected_params) in enumerate(CASES, 1):
        intent = agent._parse_intent_by_rules(q, history=[])
        actual_hint = intent.get("chart_hint")
        if actual_hint != expected_hint:
            print(f"[FAIL] #{i} {q!r}")
            print(f"       chart_hint: expected={expected_hint!r}, actual={actual_hint!r}")
            failed += 1
            continue
        if actual_hint not in agent.ROUTE_TABLE:
            print(f"[FAIL] #{i} {q!r}")
            print(f"       chart_hint={actual_hint!r} 不在 ROUTE_TABLE")
            failed += 1
            continue
        route = agent.ROUTE_TABLE[actual_hint]
        params = route["build"](intent)
        for k, v in expected_params.items():
            if params.get(k) != v:
                print(f"[FAIL] #{i} {q!r}")
                print(f"       params.{k}: expected={v!r}, actual={params.get(k)!r}")
                print(f"       full params: {params}")
                failed += 1
                break
        else:
            print(f"[PASS] #{i} {q!r}")
            print(f"       hint={actual_hint!r}  params={json.dumps(params, ensure_ascii=False)}")
    return failed


def run_multiturn():
    failed = 0
    history = []
    for i, (q, expected_hint_inherit, expected_fields) in enumerate(MULTITURN_CASES, 1):
        intent = agent._parse_intent_by_rules(q, history=history)
        history.append({"question": q, "intent": intent})
        print(f"[MT#{i}] {q!r}")
        print(f"        intent={json.dumps(intent, ensure_ascii=False)}")
        for k, v in expected_fields.items():
            if intent.get(k) != v:
                print(f"[FAIL]  field {k}: expected={v!r}, actual={intent.get(k)!r}")
                failed += 1
                break
        else:
            print(f"[PASS]  继承 OK：chart_hint={intent.get('chart_hint')!r} by={intent.get('by')!r}")
    return failed


def run_negative():
    failed = 0
    for i, q in enumerate(NEGATIVE_CASES, 1):
        intent = agent._parse_intent_by_rules(q, history=[])
        hint = intent.get("chart_hint")
        if hint is not None:
            print(f"[FAIL] #{i} {q!r}  不该命中 chart_hint，但命中了 {hint!r}")
            failed += 1
        else:
            print(f"[PASS] #{i} {q!r}  chart_hint=None (走旧路由 metric={intent.get('metric')!r})")
    return failed


def main():
    print("=== 正面用例（13 条 chart_hint 路由）===")
    f1 = run_positive()
    print("\n=== 多轮上下文继承（2 条）===")
    f2 = run_multiturn()
    print("\n=== 反例（不应命中 chart_hint）===")
    f3 = run_negative()
    total = len(CASES) + len(MULTITURN_CASES) + len(NEGATIVE_CASES)
    failed = f1 + f2 + f3
    print()
    if failed:
        print(f"=== {failed} case(s) FAILED ===")
        sys.exit(1)
    else:
        print(f"=== ALL {total} CASES PASSED ===")


if __name__ == "__main__":
    main()
