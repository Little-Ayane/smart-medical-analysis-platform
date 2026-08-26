# -*- coding: utf-8 -*-
"""
P3 · 病种手术与支付分析 API 自测脚本（断言式，非零退出码）
用法：python self_test.py [--server http://127.0.0.1:5000]
覆盖：14 个新端点成功用例、异常分支（400）、关键数据口径断言、
      缓存语义、过滤参数回归、旧接口兼容（P4 依赖）。
"""
import argparse
import sys

import requests

SERVER = "http://127.0.0.1:5000"
FAILED = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    line = f"[{status}] {name}"
    if detail and not cond:
        line += f"  <- {detail}"
    print(line)
    if not cond:
        FAILED.append(name)


def get(path, params=None):
    resp = requests.get(SERVER + path, params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------
# 通用约定
# ------------------------------------------------------------
def test_envelope():
    r = get("/api/v1/disease/top-diagnoses", {"top": 3})
    check("信封: code/message/data/meta 齐全",
          r["code"] == 0 and r["message"] == "success"
          and isinstance(r["data"], list) and isinstance(r["meta"], dict), str(r)[:200])
    for key in ("dimension", "metric", "total_records", "filters",
                "cached", "query_ms", "generated_at"):
        check(f"信封: meta.{key} 存在", key in r["meta"])


# ------------------------------------------------------------
# 模块一 病种与手术分析
# ------------------------------------------------------------
def test_top_diagnoses():
    r = get("/api/v1/disease/top-diagnoses", {"top": 3, "metric": "count"})
    check("top-diagnoses: 首行 LIVEBORN 154598",
          r["data"][0]["name"] == "LIVEBORN" and r["data"][0]["count"] == 154598,
          str(r["data"][0]))
    check("top-diagnoses: total_records=2055140", r["meta"]["total_records"] == 2055140,
          str(r["meta"]))

    r2 = get("/api/v1/disease/top-diagnoses", {"metric": "total_charges", "top": 3})
    check("top-diagnoses: metric=total_charges 返回 float value",
          all(isinstance(d["value"], float) for d in r2["data"]), str(r2["data"]))

    r3 = get("/api/v1/disease/top-diagnoses", {"metric": "evil"})
    check("top-diagnoses: 非法 metric -> 400", r3["code"] == 400, str(r3))

    r4 = get("/api/v1/disease/top-diagnoses", {"top": "abc"})
    check("top-diagnoses: 非法 top -> 400", r4["code"] == 400, str(r4))


def test_top_procedures():
    r = get("/api/v1/disease/top-procedures", {"top": 3})
    check("top-procedures: total_records=1500426（手术口径）",
          r["meta"]["total_records"] == 1500426, str(r["meta"]))
    check("top-procedures: 首行 SPONTANEOUS VAGINAL DELIVERY",
          r["data"][0]["name"] == "SPONTANEOUS VAGINAL DELIVERY",
          str(r["data"][0]))


def test_severity_profile():
    r = get("/api/v1/disease/severity-profile", {"by": "age_group"})
    groups = {d["group"] for d in r["data"]}
    sevs = {d["severity"] for d in r["data"]}
    check("severity-profile: 5 个年龄组", len(groups) == 5, str(groups))
    check("severity-profile: severity 取值合法",
          sevs <= {"Minor", "Moderate", "Major", "Extreme", "Unknown"}, str(sevs))

    r2 = get("/api/v1/disease/severity-profile", {"by": "discharge_year"})
    check("severity-profile: by=discharge_year -> 400（单年数据）",
          r2["code"] == 400, str(r2))


def test_population_diff():
    r = get("/api/v1/disease/population-diff", {"dimension": "gender"})
    keys = [d["key"] for d in r["data"]]
    check("population-diff: F/M/Unknown 三组", keys == ["F", "M", "Unknown"], str(keys))
    check("population-diff: pct 合计约 100",
          abs(sum(d["pct"] for d in r["data"]) - 100) < 0.05,
          str([d["pct"] for d in r["data"]]))


def test_pyramid():
    r = get("/api/v1/disease/pyramid")
    total = sum(d["male"] + d["female"] for d in r["data"])
    check("pyramid: total_records=2056623（排除 gender NULL 151）",
          r["meta"]["total_records"] == 2056623, str(r["meta"]))
    check("pyramid: male+female 求和 == total_records",
          total == r["meta"]["total_records"], str(total))
    check("pyramid: 5 行且顺序 0 to 17 起",
          len(r["data"]) == 5 and r["data"][0]["age_group"] == "0 to 17",
          str([d["age_group"] for d in r["data"]]))

    r2 = get("/api/v1/disease/pyramid", {"gender": "M"})
    check("pyramid: gender=M 过滤后 male 全占",
          all(d["female"] == 0 for d in r2["data"])
          and sum(d["male"] for d in r2["data"]) == r2["meta"]["total_records"],
          str(r2["data"]))


def test_region_diff():
    r = get("/api/v1/disease/region-diff", {"level": "facility"})
    check("region-diff: facility 层默认 15 家（key 为医院名）",
          len(r["data"]) <= 15 and r["data"][0]["key"], str(r["data"][0]))
    r2 = get("/api/v1/disease/region-diff", {"level": "service_area"})
    keys = [d["key"] for d in r2["data"]]
    check("region-diff: service_area 8 区 + Unknown 组（医院无归属）",
          len(keys) == 9 and "Unknown" in keys, str(keys))
    r3 = get("/api/v1/disease/region-diff", {"level": "city"})
    check("region-diff: 非法 level -> 400", r3["code"] == 400, str(r3))


def test_heatmap():
    r = get("/api/v1/disease/heatmap",
            {"dim1": "diagnosis", "dim2": "age_group", "top": 5})
    check("heatmap: 行数 <= 25（top5 x 5 组）", len(r["data"]) <= 25, str(len(r["data"])))
    check("heatmap: 三元组含名称列",
          all(k in r["data"][0] for k in ("dim1", "dim1_name", "dim2", "dim2_name",
                                          "count", "value")),
          str(r["data"][0]))
    r2 = get("/api/v1/disease/heatmap", {"dim1": "age_group", "dim2": "age_group"})
    check("heatmap: dim1==dim2 -> 400", r2["code"] == 400, str(r2))


# ------------------------------------------------------------
# 模块二 支付分析
# ------------------------------------------------------------
def test_composition():
    r = get("/api/v1/payment/composition", {"group": "payment2"})
    check("composition: payment2 null_excluded=1043819",
          r["meta"]["null_excluded"] == 1043819, str(r["meta"]))
    check("composition: pct 合计约 100",
          abs(sum(d["pct"] for d in r["data"]) - 100) < 0.05,
          str([d["pct"] for d in r["data"]]))
    r2 = get("/api/v1/payment/composition", {"group": "payment4"})
    check("composition: 非法 group -> 400", r2["code"] == 400, str(r2))


def test_cross():
    r = get("/api/v1/payment/cross", {"dim2": "age_group"})
    check("cross: 9 支付 x 5 年龄组（约 45 行）",
          40 <= len(r["data"]) <= 45, str(len(r["data"])))


def test_sankey():
    r = get("/api/v1/payment/sankey", {"levels": "payment,payment2"})
    names = [n["name"] for n in r["data"]["nodes"]]
    link_sum = sum(l["value"] for l in r["data"]["links"])
    check("sankey: 节点名带层前缀（跨层去重）",
          all("|" in n for n in names), str(names[:3]))
    check("sankey: 链路 value 合计 == total_records",
          link_sum == r["meta"]["total_records"], f"{link_sum} vs {r['meta']['total_records']}")
    check("sankey: 节点含 layer/layer_index 字段",
          all(k in r["data"]["nodes"][0] for k in ("layer", "layer_index", "display")),
          str(r["data"]["nodes"][0]))

    r2 = get("/api/v1/payment/sankey", {"levels": "payment,foo"})
    check("sankey: 非法 levels -> 400", r2["code"] == 400, str(r2))

    r3 = get("/api/v1/payment/sankey", {"levels": "payment,payment2,payment3"})
    check("sankey: 三级链 null_excluded 回显",
          r3["meta"]["null_excluded"] > 0 and r3["meta"]["total_records"] == 326038,
          str(r3["meta"]))


def test_cost_relation():
    r = get("/api/v1/payment/cost-relation", {"by": "payment"})
    check("cost-relation: 每行 ratio>0 且字段齐全",
          all(d["charge_cost_ratio"] > 0 for d in r["data"])
          and all(k in r["data"][0] for k in ("count", "avg_charges",
                                              "avg_costs", "charge_cost_ratio")),
          str(r["data"][0]))


def test_oop_burden():
    r = get("/api/v1/payment/oop-burden", {"dimension": "age_group", "mode": "selfpay1"})
    check("oop-burden: selfpay1 含金额字段",
          all(k in r["data"][0] for k in ("self_pay_charges",
                                          "self_pay_avg_charges",
                                          "self_pay_share_of_charges")),
          str(r["data"][0]))
    r2 = get("/api/v1/payment/oop-burden", {"dimension": "age_group", "mode": "any_layer"})
    check("oop-burden: any_layer 不含金额字段（口径边界）",
          "self_pay_charges" not in r2["data"][0], str(r2["data"][0]))
    r3 = get("/api/v1/payment/oop-burden", {"mode": "whatever"})
    check("oop-burden: 非法 mode -> 400", r3["code"] == 400, str(r3))


def test_summary():
    r = get("/api/v1/payment/summary")
    keys = ("total_records", "total_charges", "total_costs", "avg_charges",
            "avg_costs", "avg_los", "self_pay_count", "self_pay_pct",
            "top_payment", "severity_distribution", "ed_count")
    check("summary: 11 个 KPI 字段齐全", all(k in r["data"] for k in keys),
          str(r["data"].keys()))
    check("summary: 严重度分布 5 组（含 Unknown）",
          len(r["data"]["severity_distribution"]) == 5
          and r["data"]["severity_distribution"]["Unknown"] == 2543,
          str(r["data"]["severity_distribution"]))


# ------------------------------------------------------------
# 字典 / 过滤 / 缓存 / 兼容
# ------------------------------------------------------------
def test_meta():
    r = get("/api/v1/meta/dimensions")
    check("meta: diagnosis 477 项", len(r["data"]["diagnosis"]) == 477,
          str(len(r["data"]["diagnosis"])))
    check("meta: procedure 320 项", len(r["data"]["procedure"]) == 320,
          str(len(r["data"]["procedure"])))


def test_filters():
    r = get("/api/v1/disease/top-diagnoses", {"diagnosis": "NOPE"})
    check("过滤: diagnosis=NOPE -> code=0 且空数组",
          r["code"] == 0 and r["data"] == [], str(r))

    r2 = get("/api/v1/disease/top-diagnoses", {"severity": "Extreme", "top": 5})
    check("过滤: severity=Extreme 回显并生效",
          r2["meta"]["filters"].get("severity") == 4 and len(r2["data"]) == 5,
          str(r2["meta"]["filters"]))

    r3 = get("/api/v1/disease/top-diagnoses", {"year": "2022"})
    check("过滤: year=2022 -> 400", r3["code"] == 400, str(r3))


def test_cache():
    params = {"metric": "avg_charges", "top": 3}
    r1 = get("/api/v1/disease/top-diagnoses", params)
    r2 = get("/api/v1/disease/top-diagnoses", params)
    check("缓存: 第二次请求 cached=true 且 query_ms=0",
          r2["meta"]["cached"] is True and r2["meta"]["query_ms"] == 0,
          str(r2["meta"]))
    check("缓存: 两次结果一致",
          r1["data"] == r2["data"] and r1["meta"]["total_records"] == r2["meta"]["total_records"])


# ------------------------------------------------------------
# 模块四 医疗质量监测
# ------------------------------------------------------------
def test_quality():
    r = get("/api/v1/quality/overview")
    check("quality/overview: KPI 字段齐全",
          r["code"] == 0 and isinstance(r["data"], dict) and all(
              k in r["data"] for k in
              ("total_records", "deaths", "mortality_rate", "avg_los", "ed_rate",
               "ama_rate", "transfer_rate", "newborns", "lbw_rate",
               "avg_charges", "avg_costs")), str(r)[:200])
    check("quality/overview: 比率在 0-100 区间",
          all(0 <= r["data"][k] <= 100 for k in
              ("mortality_rate", "ed_rate", "ama_rate", "transfer_rate")),
          str(r["data"]))

    r2 = get("/api/v1/quality/mortality", {"dimension": "diagnosis", "top": 5})
    check("quality/mortality: 结构 {key,name,count,deaths,mortality_rate}",
          r2["code"] == 0 and r2["data"] and all(
              all(k in d for k in ("key", "name", "count", "deaths", "mortality_rate"))
              for d in r2["data"]), str(r2)[:200])
    check("quality/mortality: 按死亡率降序",
          r2["data"] == sorted(r2["data"], key=lambda d: -d["mortality_rate"]),
          str(r2["data"][:3]))

    r3 = get("/api/v1/quality/length-of-stay",
             {"dimension": "facility", "min_cases": 200})
    check("quality/length-of-stay: 结构 {key,name,count,avg_los}",
          r3["code"] == 0 and r3["data"] and all(
              all(k in d for k in ("key", "name", "count", "avg_los"))
              for d in r3["data"]), str(r3)[:200])
    check("quality/length-of-stay: 分母 >= min_cases",
          all(d["count"] >= 200 for d in r3["data"]), str(r3["data"]))

    r4 = get("/api/v1/quality/facility-ranking", {"top": 10, "min_cases": 100})
    check("quality/facility-ranking: 医院多指标齐全",
          r4["code"] == 0 and r4["data"] and all(
              all(k in d for k in ("key", "name", "county", "count",
                                   "mortality_rate", "avg_los", "ed_rate",
                                   "ama_rate", "transfer_rate", "newborns",
                                   "lbw_rate", "avg_charges", "avg_costs"))
              for d in r4["data"]), str(r4)[:200])

    r5 = get("/api/v1/quality/disposition")
    check("quality/disposition: 结构 {key,count,pct} 且 pct 合计 ≈ 100",
          r5["code"] == 0 and r5["data"] and all(
              all(k in d for k in ("key", "count", "pct")) for d in r5["data"])
          and abs(sum(d["pct"] for d in r5["data"]) - 100) < 1, str(r5)[:200])

    r6 = get("/api/v1/quality/mortality", {"dimension": "nonsense"})
    check("quality/mortality: 非法 dimension -> 400", r6["code"] == 400, str(r6)[:200])


def test_legacy():
    r = get("/api/v1/health")
    check("旧接口: /health 正常", r["code"] == 0 and r["data"]["db"] == "connected", str(r))
    r2 = get("/api/v1/analysis/aggregate", {"dimension": "gender", "metric": "count"})
    check("旧接口: /analysis/aggregate 正常（P4 兼容）", r2["code"] == 0 and r2["data"], str(r2)[:200])
    r3 = get("/api/v1/analysis/payment-mix")
    check("旧接口: /analysis/payment-mix 正常", r3["code"] == 0 and r3["data"], str(r3)[:200])
    r4 = get("/api/v1/analysis/trend")
    check("旧接口: /analysis/trend 正常", r4["code"] == 0 and r4["data"], str(r4)[:200])


def main():
    global SERVER
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=SERVER)
    args = parser.parse_args()
    SERVER = args.server

    print(f"目标服务: {SERVER}\n")
    test_envelope()
    test_top_diagnoses()
    test_top_procedures()
    test_severity_profile()
    test_population_diff()
    test_pyramid()
    test_region_diff()
    test_heatmap()
    test_composition()
    test_cross()
    test_sankey()
    test_cost_relation()
    test_oop_burden()
    test_summary()
    test_meta()
    test_filters()
    test_cache()
    test_quality()
    test_legacy()

    print(f"\n{'=' * 50}\n共 {19} 组用例，失败 {len(FAILED)} 组: {FAILED or '无'}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
