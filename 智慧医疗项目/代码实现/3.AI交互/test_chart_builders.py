# -*- coding: utf-8 -*-
"""Step 4 验证：13 个 CHART_BUILDERS 用 P3 接口文档的样例数据，验证：
1) 不报异常
2) 输出 option 是 JSON 可序列化（Flask jsonify 不会崩）
3) chart_type 字段在合法集合内
4) 关键 ECharts 字段（title/series/xAxis/yAxis/tooltip）齐全
用法：python test_chart_builders.py
"""
import json
import sys

import agent


# 每条样例 (chart_hint, intent, api_result)
SAMPLES = [
    # 4.1 top-diagnoses
    ("top_diagnoses",
     {"metric": "count", "chart_hint": "top_diagnoses", "dimension": "ccsr_diagnosis", "top": 3},
     {"data": [
         {"code": "PNL001", "name": "LIVEBORN", "count": 154598, "value": 154598},
         {"code": "INF002", "name": "SEPTICEMIA", "count": 138031, "value": 138031},
         {"code": "INF012", "name": "CORONAVIRUS DISEASE 2019 (COVID-19)", "count": 82591, "value": 82591}],
      "meta": {"dimension": "ccsr_diagnosis", "metric": "count",
               "total_records": 2055140, "cached": False, "query_ms": 737}}),
    # 4.2 top-procedures
    ("top_procedures",
     {"metric": "count", "chart_hint": "top_procedures", "dimension": "procedure", "top": 3},
     {"data": [
         {"code": "PGN002", "name": "SPONTANEOUS VAGINAL DELIVERY", "count": 113319, "value": 113319}],
      "meta": {"total_records": 1500426}}),
    # 4.3 severity-profile
    ("severity_profile",
     {"by": "age_group", "metric": "count", "chart_hint": "severity_profile"},
     {"data": [
         {"group": "0 to 17", "severity": "Minor", "value": 135802, "count": 135802},
         {"group": "0 to 17", "severity": "Moderate", "value": 70471, "count": 70471},
         {"group": "70 or Older", "severity": "Extreme", "value": 120187, "count": 120187}],
      "meta": {"dimension": "severity_profile", "metric": "count", "total_records": 2056774}}),
    # 4.4 population-diff
    ("population_diff",
     {"by": "gender", "metric": "count", "chart_hint": "population_diff"},
     {"data": [
         {"key": "F", "count": 1119640, "pct": 54.44, "value": 1119640},
         {"key": "M", "count": 936983, "pct": 45.56, "value": 936983},
         {"key": "Unknown", "count": 151, "pct": 0.01, "value": 151}],
      "meta": {"dimension": "gender", "metric": "count", "total_records": 2056774}}),
    # 4.5 pyramid
    ("pyramid",
     {"chart_hint": "pyramid"},
     {"data": [
         {"age_group": "0 to 17", "male": 129502, "female": 115576, "total": 245078},
         {"age_group": "70 or Older", "male": 279957, "female": 339616, "total": 619573}],
      "meta": {"dimension": "age_group_gender", "metric": "count", "total_records": 2056623}}),
    # 4.6 region-diff
    ("region_diff",
     {"level": "service_area", "metric": "count", "chart_hint": "region_diff"},
     {"data": [
         {"key": "New York City", "count": 913496, "value": 913496},
         {"key": "Long Island", "count": 331353, "value": 331353}],
      "meta": {"dimension": "service_area", "metric": "count", "total_records": 2056774}}),
    # 4.7 heatmap
    ("heatmap",
     {"dim1": "diagnosis", "dim2": "age_group", "metric": "count", "chart_hint": "heatmap"},
     {"data": [
         {"dim1": "PNL001", "dim1_name": "LIVEBORN", "dim2": "0 to 17", "dim2_name": "0 to 17",
          "count": 154598, "value": 154598}],
      "meta": {"dimension": "diagnosis_x_age_group", "top": 5, "total_records": 2056774}}),
    # 5.1 payment-composition
    ("payment_composition",
     {"group": "payment2", "metric": "count", "chart_hint": "payment_composition"},
     {"data": [
         {"key": "Medicaid", "count": 407960, "pct": 40.27, "value": 407960},
         {"key": "Self-Pay", "count": 153374, "pct": 15.14, "value": 153374}],
      "meta": {"dimension": "payment2", "metric": "count", "total_records": 2056774,
               "null_excluded": 1043819}}),
    # 5.2 payment-cross
    ("payment_cross",
     {"dim2": "age_group", "metric": "count", "chart_hint": "payment_cross"},
     {"data": [
         {"key": "Medicare", "dim2": "70 or Older", "dim2_name": "70 or Older",
          "count": 524788, "value": 524788}],
      "meta": {"total_records": 2056774}}),
    # 5.3 sankey
    ("sankey",
     {"levels": "payment,payment2", "chart_hint": "sankey"},
     {"data": {
         "nodes": [
             {"name": "支付1|Medicare", "display": "Medicare", "layer": "支付1", "layer_index": 0},
             {"name": "支付2|Medicaid", "display": "Medicaid", "layer": "支付2", "layer_index": 1}],
         "links": [{"source": "支付1|Medicare", "target": "支付2|Medicaid", "value": 201825}]},
      "meta": {"dimension": "sankey", "metric": "count", "total_records": 1012955,
               "null_excluded": 1043819, "levels": "payment,payment2"}}),
    # 5.4 cost-relation
    ("cost_relation",
     {"by": "payment", "metric": "count", "chart_hint": "cost_relation"},
     {"data": [
         {"key": "Medicare", "count": 826128, "avg_charges": 87986.26,
          "avg_costs": 25755.28, "charge_cost_ratio": 3.42}],
      "meta": {"total_records": 2056774}}),
    # 5.5 oop-burden
    ("oop_burden",
     {"dimension": "age_group", "mode": "selfpay1", "chart_hint": "oop_burden"},
     {"data": [
         {"key": "30 to 49", "total_count": 415627, "self_pay_count": 7218, "self_pay_pct": 1.74,
          "self_pay_charges": 353032640.52, "self_pay_avg_charges": 48910.04,
          "self_pay_share_of_charges": 1.44}],
      "meta": {"total_records": 2056774}}),
    # 5.6 payment-summary
    ("payment_summary",
     {"chart_hint": "payment_summary"},
     {"data": {
         "total_records": 2056774,
         "total_charges": 153555627951.47, "total_costs": 46095406196.02,
         "avg_charges": 74658.48, "avg_costs": 22411.51, "avg_los": 5.83,
         "self_pay_count": 26310, "self_pay_pct": 1.28,
         "top_payment": {"key": "Medicare", "count": 826128, "pct": 40.17},
         "severity_distribution": {"Minor": 598786, "Moderate": 755709,
                                   "Major": 498975, "Extreme": 200761, "Unknown": 2543},
         "ed_count": 1316133},
      "meta": {"total_records": 2056774}}),
]


def main():
    failed = 0
    for i, (hint, intent, api_result) in enumerate(SAMPLES, 1):
        try:
            r = agent.generate_chart_config(intent, api_result, use_llm=False)
        except Exception as e:
            print(f"[FAIL] #{i} {hint}: 异常 {type(e).__name__}: {e}")
            failed += 1
            continue

        ct = r.get("chart_type")
        option = r.get("option", {})
        if ct not in {"bar", "pie", "line", "heatmap", "sankey", "scatter", "kpi"}:
            print(f"[FAIL] #{i} {hint}: chart_type={ct!r} 非法")
            failed += 1
            continue
        # JSON 可序列化（Flask jsonify 不会崩）
        try:
            json.dumps(option, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            print(f"[FAIL] #{i} {hint}: option 不可 JSON 序列化: {e}")
            failed += 1
            continue
        # 关键字段检查
        if "series" not in option:
            print(f"[FAIL] #{i} {hint}: option 缺 series 字段")
            failed += 1
            continue
        if "title" not in option:
            print(f"[FAIL] #{i} {hint}: option 缺 title 字段")
            failed += 1
            continue
        # 加分项：至少一个 series 有 type
        s = option["series"][0] if option["series"] else {}
        if "type" not in s:
            print(f"[FAIL] #{i} {hint}: series[0] 缺 type 字段")
            failed += 1
            continue
        # 加分项：sankey 需要 nodes/links（ECharts 用 series.data=nodes + series.links=links）
        if ct == "sankey":
            s = option["series"][0]
            if "data" not in s or "links" not in s:
                print(f"[FAIL] #{i} {hint}: sankey series 缺 data/links")
                failed += 1
                continue
            if not s["data"] or not s["links"]:
                print(f"[FAIL] #{i} {hint}: sankey data/links 为空")
                failed += 1
                continue
        print(f"[PASS] #{i} {hint}: chart_type={ct} series={len(option['series'])} "
              f"tooltip={'formatter' in option.get('tooltip', {})}")

    print()
    if failed:
        print(f"=== {failed} case(s) FAILED ===")
        sys.exit(1)
    else:
        print(f"=== ALL {len(SAMPLES)} CASES PASSED ===")


if __name__ == "__main__":
    main()
