# -*- coding: utf-8 -*-
"""Step 6 验证：generate_insight_report 对 13 种新 chart_hint + 2 旧用例回归。

每个用例构造 {intent, api_result, chart} 三元组，调用 generate_insight_report，
验证：
  1) 不报异常
  2) 至少 1 个 section
  3) key_findings 非空
  4) section_title / chart_type 符合预期
  5) sankey/payment_summary 的 data 是 dict（不能被 list 切片）
  6) 旧用例（chart_hint=None）行为不变

用法：python test_report_builders.py
"""
import sys
import json

import agent


# 复用 test_chart_builders.py 的样例数据，扩展为 (chart_hint, intent, api_result, chart, title_keyword)
SAMPLES = [
    # 1. top_diagnoses
    ("top_diagnoses",
     {"metric": "count", "chart_hint": "top_diagnoses", "dimension": "ccsr_diagnosis"},
     {"data": [{"code": "PNL001", "name": "LIVEBORN", "count": 154598, "value": 154598},
               {"code": "INF002", "name": "SEPTICEMIA", "count": 138031, "value": 138031},
               {"code": "INF012", "name": "COVID-19", "count": 82591, "value": 82591}],
      "meta": {"dimension": "ccsr_diagnosis", "metric": "count",
               "total_records": 2055140, "query_ms": 737}},
     {"chart_type": "bar"},
     "Top 诊断"),
    # 2. top_procedures
    ("top_procedures",
     {"metric": "count", "chart_hint": "top_procedures", "dimension": "procedure"},
     {"data": [{"code": "PGN002", "name": "VAGINAL DELIVERY", "count": 113319, "value": 113319},
               {"code": "PGN003", "name": "CESAREAN SECTION", "count": 50000, "value": 50000}],
      "meta": {"dimension": "procedure", "metric": "count",
               "total_records": 1500426, "query_ms": 200}},
     {"chart_type": "bar"},
     "Top 手术"),
    # 3. severity_profile
    ("severity_profile",
     {"by": "age_group", "metric": "count", "chart_hint": "severity_profile"},
     {"data": [{"group": "0 to 17", "severity": "Minor", "value": 135802, "count": 135802},
               {"group": "0 to 17", "severity": "Moderate", "value": 70471, "count": 70471},
               {"group": "70 or Older", "severity": "Extreme", "value": 120187, "count": 120187}],
      "meta": {"total_records": 2056774, "query_ms": 100}},
     {"chart_type": "bar"},
     "病重"),
    # 4. population_diff
    ("population_diff",
     {"by": "gender", "metric": "count", "chart_hint": "population_diff"},
     {"data": [{"key": "F", "count": 1119640, "pct": 54.44, "value": 1119640},
               {"key": "M", "count": 936983, "pct": 45.56, "value": 936983}],
      "meta": {"total_records": 2056774, "query_ms": 80}},
     {"chart_type": "bar"},
     "人群"),
    # 5. pyramid
    ("pyramid",
     {"chart_hint": "pyramid"},
     {"data": [{"age_group": "0 to 17", "male": 129502, "female": 115576, "total": 245078},
               {"age_group": "70 or Older", "male": 279957, "female": 339616, "total": 619573}],
      "meta": {"total_records": 2056623, "query_ms": 50}},
     {"chart_type": "bar"},
     "金字塔"),
    # 6. region_diff
    ("region_diff",
     {"level": "service_area", "metric": "count", "chart_hint": "region_diff"},
     {"data": [{"key": "New York City", "count": 913496, "value": 913496},
               {"key": "Long Island", "count": 331353, "value": 331353}],
      "meta": {"total_records": 2056774, "query_ms": 90}},
     {"chart_type": "bar"},
     "地区"),
    # 7. heatmap
    ("heatmap",
     {"dim1": "diagnosis", "dim2": "age_group", "metric": "count", "chart_hint": "heatmap"},
     {"data": [{"dim1": "PNL001", "dim1_name": "LIVEBORN", "dim2": "0 to 17", "dim2_name": "0 to 17",
                "count": 154598, "value": 154598},
               {"dim1": "INF002", "dim1_name": "SEPTICEMIA", "dim2": "18 to 29", "dim2_name": "18 to 29",
                "count": 50000, "value": 50000}],
      "meta": {"total_records": 2056774, "query_ms": 110}},
     {"chart_type": "heatmap"},
     "热力"),
    # 8. payment_composition
    ("payment_composition",
     {"group": "payment2", "metric": "count", "chart_hint": "payment_composition"},
     {"data": [{"key": "Medicaid", "count": 407960, "pct": 40.27, "value": 407960},
               {"key": "Self-Pay", "count": 153374, "pct": 15.14, "value": 153374}],
      "meta": {"total_records": 2056774, "null_excluded": 1043819, "query_ms": 70}},
     {"chart_type": "pie"},
     "支付"),
    # 9. payment_cross
    ("payment_cross",
     {"dim2": "age_group", "metric": "count", "chart_hint": "payment_cross"},
     {"data": [{"key": "Medicare", "dim2": "70 or Older", "dim2_name": "70 or Older",
                "count": 524788, "value": 524788},
               {"key": "Medicaid", "dim2": "0 to 17", "dim2_name": "0 to 17",
                "count": 200000, "value": 200000}],
      "meta": {"total_records": 2056774, "query_ms": 60}},
     {"chart_type": "bar"},
     "交叉"),
    # 10. sankey
    ("sankey",
     {"levels": "payment,payment2", "chart_hint": "sankey"},
     {"data": {
         "nodes": [{"name": "支付1|Medicare", "display": "Medicare", "layer": "支付1", "layer_index": 0},
                   {"name": "支付2|Medicaid", "display": "Medicaid", "layer": "支付2", "layer_index": 1}],
         "links": [{"source": "支付1|Medicare", "target": "支付2|Medicaid", "value": 201825}]},
      "meta": {"total_records": 1012955, "null_excluded": 1043819,
               "levels": "payment,payment2", "query_ms": 100}},
     {"chart_type": "sankey"},
     "桑葚"),
    # 11. cost_relation
    ("cost_relation",
     {"by": "payment", "metric": "count", "chart_hint": "cost_relation"},
     {"data": [{"key": "Medicare", "count": 826128, "avg_charges": 87986.26,
                "avg_costs": 25755.28, "charge_cost_ratio": 3.42},
               {"key": "Medicaid", "count": 407960, "avg_charges": 35200.50,
                "avg_costs": 15200.00, "charge_cost_ratio": 2.32}],
      "meta": {"total_records": 2056774, "query_ms": 80}},
     {"chart_type": "scatter"},
     "费用"),
    # 12. oop_burden
    ("oop_burden",
     {"dimension": "age_group", "mode": "selfpay1", "chart_hint": "oop_burden"},
     {"data": [{"key": "30 to 49", "total_count": 415627, "self_pay_count": 7218,
                "self_pay_pct": 1.74, "self_pay_avg_charges": 48910.04},
               {"key": "50 to 69", "total_count": 500000, "self_pay_count": 5000,
                "self_pay_pct": 1.00, "self_pay_avg_charges": 40000.00}],
      "meta": {"total_records": 2056774, "query_ms": 90}},
     {"chart_type": "bar"},
     "自付"),
    # 13. payment_summary
    ("payment_summary",
     {"chart_hint": "payment_summary"},
     {"data": {
         "total_records": 2056774, "total_charges": 153555627951.47, "total_costs": 46095406196.02,
         "avg_charges": 74658.48, "avg_costs": 22411.51, "avg_los": 5.83,
         "self_pay_count": 26310, "self_pay_pct": 1.28,
         "top_payment": {"key": "Medicare", "count": 826128, "pct": 40.17},
         "severity_distribution": {"Minor": 598786, "Moderate": 755709,
                                   "Major": 498975, "Extreme": 200761, "Unknown": 2543},
         "ed_count": 1316133},
      "meta": {"total_records": 2056774, "query_ms": 50}},
     {"chart_type": "kpi"},
     "KPI"),
    # 14. 旧用例回归：chart_hint=None
    ("(legacy) aggregate",
     {"metric": "avg_length_of_stay", "dimension": "ccsr_diagnosis", "filters": {}, "top": 5},
     {"data": [{"key": "SEPTICEMIA", "value": 12.5, "count": 138031},
               {"key": "COVID-19", "value": 10.2, "count": 82591}],
      "meta": {"dimension": "ccsr_diagnosis", "metric": "avg_length_of_stay",
               "total_records": 2055140, "query_ms": 80}},
     {"chart_type": "bar"},
     "分析维度"),
    # 15. 旧用例回归：payment_mix
    ("(legacy) payment_mix",
     {"metric": "payment_mix", "dimension": "payment_typology", "filters": {}},
     {"data": [{"key": "Medicare", "value": 40.17, "pct": 40.17, "count": 826128},
               {"key": "Medicaid", "value": 30.50, "pct": 30.50, "count": 628000}],
      "meta": {"dimension": "payment_typology", "metric": "payment_mix",
               "total_records": 2056774, "query_ms": 60}},
     {"chart_type": "pie"},
     "分析维度"),
]


def main():
    failed = 0
    for i, (hint, intent, api_result, chart, title_keyword) in enumerate(SAMPLES, 1):
        try:
            report = agent.generate_insight_report(
                single_result={"api_result": api_result, "chart": chart, "intent": intent},
                use_llm=False,
            )
        except Exception as e:
            print(f"[FAIL] #{i} {hint}: 异常 {type(e).__name__}: {e}")
            failed += 1
            continue

        # 至少 1 个 section
        sections = report.get("sections", [])
        if not sections:
            print(f"[FAIL] #{i} {hint}: sections 为空")
            failed += 1
            continue
        sec = sections[0]
        title = sec.get("section_title", "")
        findings = sec.get("key_findings", [])
        ct = sec.get("chart_type", "-")
        data_sample = sec.get("data")

        # key_findings 非空
        if not findings:
            print(f"[FAIL] #{i} {hint}: key_findings 为空 (title={title!r})")
            failed += 1
            continue

        # section_title 包含关键词
        if title_keyword not in title:
            print(f"[FAIL] #{i} {hint}: title={title!r} 缺关键词 {title_keyword!r}")
            failed += 1
            continue

        # chart_type 必须等于 chart.chart_type
        if ct != chart.get("chart_type"):
            print(f"[FAIL] #{i} {hint}: chart_type={ct!r}，期望 {chart.get('chart_type')!r}")
            failed += 1
            continue

        # sankey/payment_summary 的 data 必须是 dict（不能被 list 切片切坏）
        if hint == "sankey" or hint == "payment_summary":
            if not isinstance(data_sample, dict):
                print(f"[FAIL] #{i} {hint}: data 应为 dict，实际 {type(data_sample).__name__}")
                failed += 1
                continue
        # 旧用例回归：data 必须是 list，且切片保留前 10 项
        elif hint.startswith("(legacy)"):
            if not isinstance(data_sample, list):
                print(f"[FAIL] #{i} {hint}: data 应为 list，实际 {type(data_sample).__name__}")
                failed += 1
                continue

        # meta.chart_hint 应正确回填
        sec_chart_hint = sec.get("meta", {}).get("chart_hint")
        expected_hint = None if hint.startswith("(legacy)") else hint
        if sec_chart_hint != expected_hint:
            print(f"[FAIL] #{i} {hint}: meta.chart_hint={sec_chart_hint!r}，期望 {expected_hint!r}")
            failed += 1
            continue

        # report_source 在 use_llm=False 时应为 template
        rs = report.get("report_source", "")
        if rs != "template":
            print(f"[FAIL] #{i} {hint}: report_source={rs!r}，期望 'template'")
            failed += 1
            continue

        # 打印第一行 findings 作为预览
        preview = (findings[0][:80] + "...") if len(findings[0]) > 80 else findings[0]
        print(f"[PASS] #{i:2d} {hint:25s}  title={title!r}  findings={len(findings)}  {preview}")

    print()
    if failed:
        print(f"=== {failed} case(s) FAILED ===")
        sys.exit(1)
    else:
        print(f"=== ALL {len(SAMPLES)} CASES PASSED ===")


if __name__ == "__main__":
    main()
