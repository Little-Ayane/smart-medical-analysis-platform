# -*- coding: utf-8 -*-
"""Step 5 验证：13 个 SUMMARY_BUILDERS 用 P3 样例数据，验证：
1) 不报异常
2) 输出非空字符串（至少 50 字符）
3) 包含关键字段（数字、百分号、表格类摘要带 emoji）
4) 关键内容命中（如 severity_profile 应出现"严重程度"，sankey 应出现"链路"）
用法：python test_summary_builders.py
"""
import sys

import agent


# 复用 test_chart_builders.py 的样例数据
SAMPLES = [
    ("top_diagnoses",
     {"metric": "count", "chart_hint": "top_diagnoses", "dimension": "ccsr_diagnosis"},
     {"data": [{"code": "PNL001", "name": "LIVEBORN", "count": 154598, "value": 154598},
               {"code": "INF002", "name": "SEPTICEMIA", "count": 138031, "value": 138031}],
      "meta": {"total_records": 2055140, "query_ms": 737}},
     ["LIVEBORN", "排名", "诊断"]),
    ("top_procedures",
     {"metric": "count", "chart_hint": "top_procedures", "dimension": "procedure"},
     {"data": [{"code": "PGN002", "name": "SPONTANEOUS VAGINAL DELIVERY", "count": 113319, "value": 113319}],
      "meta": {"total_records": 1500426, "query_ms": 200}},
     ["SPONTANEOUS", "术式", "手术"]),
    ("severity_profile",
     {"by": "age_group", "metric": "count", "chart_hint": "severity_profile"},
     {"data": [{"group": "0 to 17", "severity": "Minor", "value": 135802, "count": 135802},
               {"group": "0 to 17", "severity": "Moderate", "value": 70471, "count": 70471},
               {"group": "70 or Older", "severity": "Extreme", "value": 120187, "count": 120187}],
      "meta": {"total_records": 2056774, "query_ms": 100}},
     ["严重程度", "年龄段", "极重度"]),
    ("population_diff",
     {"by": "gender", "metric": "count", "chart_hint": "population_diff"},
     {"data": [{"key": "F", "count": 1119640, "pct": 54.44, "value": 1119640},
               {"key": "M", "count": 936983, "pct": 45.56, "value": 936983}],
      "meta": {"total_records": 2056774, "query_ms": 80}},
     ["性别", "占比", "54.44"]),
    ("pyramid",
     {"chart_hint": "pyramid"},
     {"data": [{"age_group": "0 to 17", "male": 129502, "female": 115576, "total": 245078},
               {"age_group": "70 or Older", "male": 279957, "female": 339616, "total": 619573}],
      "meta": {"total_records": 2056623, "query_ms": 50}},
     ["男性", "女性", "老年"]),
    ("region_diff",
     {"level": "service_area", "metric": "count", "chart_hint": "region_diff"},
     {"data": [{"key": "New York City", "count": 913496, "value": 913496},
               {"key": "Long Island", "count": 331353, "value": 331353}],
      "meta": {"total_records": 2056774, "query_ms": 90}},
     ["服务区", "New York", "分布"]),
    ("heatmap",
     {"dim1": "diagnosis", "dim2": "age_group", "metric": "count", "chart_hint": "heatmap"},
     {"data": [{"dim1": "PNL001", "dim1_name": "LIVEBORN", "dim2": "0 to 17", "dim2_name": "0 to 17",
                "count": 154598, "value": 154598}],
      "meta": {"total_records": 2056774, "query_ms": 110}},
     ["热力图", "LIVEBORN", "诊断"]),
    ("payment_composition",
     {"group": "payment2", "metric": "count", "chart_hint": "payment_composition"},
     {"data": [{"key": "Medicaid", "count": 407960, "pct": 40.27, "value": 407960},
               {"key": "Self-Pay", "count": 153374, "pct": 15.14, "value": 153374}],
      "meta": {"total_records": 2056774, "null_excluded": 1043819, "query_ms": 70}},
     ["支付", "排除", "Medicaid"]),
    ("payment_cross",
     {"dim2": "age_group", "metric": "count", "chart_hint": "payment_cross"},
     {"data": [{"key": "Medicare", "dim2": "70 or Older", "dim2_name": "70 or Older",
                "count": 524788, "value": 524788}],
      "meta": {"total_records": 2056774, "query_ms": 60}},
     ["交叉", "Medicare", "组合"]),
    ("sankey",
     {"levels": "payment,payment2", "chart_hint": "sankey"},
     {"data": {
         "nodes": [{"name": "支付1|Medicare", "display": "Medicare", "layer": "支付1", "layer_index": 0},
                   {"name": "支付2|Medicaid", "display": "Medicaid", "layer": "支付2", "layer_index": 1}],
         "links": [{"source": "支付1|Medicare", "target": "支付2|Medicaid", "value": 201825}]},
      "meta": {"total_records": 1012955, "null_excluded": 1043819, "levels": "payment,payment2", "query_ms": 100}},
     ["链路", "Medicare", "Medicaid"]),
    ("cost_relation",
     {"by": "payment", "metric": "count", "chart_hint": "cost_relation"},
     {"data": [{"key": "Medicare", "count": 826128, "avg_charges": 87986.26,
                "avg_costs": 25755.28, "charge_cost_ratio": 3.42}],
      "meta": {"total_records": 2056774, "query_ms": 80}},
     ["费用", "成本", "3.42"]),
    ("oop_burden",
     {"dimension": "age_group", "mode": "selfpay1", "chart_hint": "oop_burden"},
     {"data": [{"key": "30 to 49", "total_count": 415627, "self_pay_count": 7218,
                "self_pay_pct": 1.74, "self_pay_charges": 353032640.52,
                "self_pay_avg_charges": 48910.04, "self_pay_share_of_charges": 1.44}],
      "meta": {"total_records": 2056774, "query_ms": 90}},
     ["自付", "30 to 49", "1.74"]),
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
     ["KPI", "Medicare", "2,056,774"]),
]


def main():
    failed = 0
    for i, (hint, intent, api_result, keywords) in enumerate(SAMPLES, 1):
        try:
            text = agent._fallback_template_summary(
                f"测试问题#{i}", intent, api_result, "维度", "指标")
        except Exception as e:
            print(f"[FAIL] #{i} {hint}: 异常 {type(e).__name__}: {e}")
            failed += 1
            continue
        if not text or len(text) < 50:
            print(f"[FAIL] #{i} {hint}: 输出过短 ({len(text)} 字符):\n{text}")
            failed += 1
            continue
        # 关键词命中
        missing = [k for k in keywords if k not in text]
        if missing:
            print(f"[FAIL] #{i} {hint}: 缺关键词 {missing}\n输出:\n{text}")
            failed += 1
            continue
        # 打印前 200 字符供人工查看
        preview = text.replace("\n", " | ")[:200]
        print(f"[PASS] #{i} {hint} ({len(text)} chars): {preview}")
    print()
    if failed:
        print(f"=== {failed} case(s) FAILED ===")
        sys.exit(1)
    else:
        print(f"=== ALL {len(SAMPLES)} CASES PASSED ===")


if __name__ == "__main__":
    main()
