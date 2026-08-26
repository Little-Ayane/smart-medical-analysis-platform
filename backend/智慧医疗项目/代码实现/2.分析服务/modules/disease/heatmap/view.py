# -*- coding: utf-8 -*-
"""通用热力图（ECharts heatmap 长表）：GET /api/v1/disease/heatmap
dim1/dim2 白名单：diagnosis/procedure/age_group/severity/gender/payment/service_area。
数据源：medical_db 星型模型。
"""
from flask import request

from common import (BadRequest, SEVERITY_CODE_TO_DESC, envelope, execute_cached,
                    fetch_dim_names, fetch_facility_map, parse_choice,
                    parse_metric, parse_top)
from .._shared import _endpoint, disease_bp
from .._star import merge_joins, parse_filters_star, where_sql_star, year_scan_cond

# 参数值 -> (限定列, topN 用外键列, 类型, JOIN 子句)
HEATMAP_DIMS = {
    "diagnosis": ("f.diagnosis_id", "diagnosis_id", "dim", ""),
    "procedure": ("f.procedure_id", "procedure_id", "dim", ""),
    "age_group": ("f.age_group", None, "fact", ""),
    "severity": ("f.apr_severity_code", None, "fact", ""),
    "gender": ("f.gender", None, "fact", ""),
    "payment": ("f.payment_typology_1", None, "fact", ""),
    "service_area": ("f.hospital_id", None, "facility", ""),
}


@disease_bp.route("/heatmap")
def heatmap():
    def handler(args):
        dim1 = parse_choice(args, "dim1", HEATMAP_DIMS, "diagnosis")
        dim2 = parse_choice(args, "dim2", HEATMAP_DIMS, "age_group")
        if dim1 == dim2:
            raise BadRequest("dim1 与 dim2 不能相同")
        metric = parse_metric(args, ("count", "avg_charges", "avg_los"))
        top = parse_top(args, 15, cap=50)
        where, params, norm, fjoins = parse_filters_star(args)

        col1, fk1, kind1, join1 = HEATMAP_DIMS[dim1]
        col2, fk2, kind2, join2 = HEATMAP_DIMS[dim2]

        # topN 子查询：只针对 diagnosis/procedure
        conds, top_params = [], []
        for fk, kind in ((fk1, kind1), (fk2, kind2)):
            if kind == "dim":
                # 内层 topN 也要带年份谓词，否则这一层自己就退化成全表回表
                conds.append(f"f.{fk} IN (SELECT id FROM (SELECT {fk} AS id, "
                             f"COUNT(*) AS c FROM fact_discharge "
                             f"WHERE {year_scan_cond(alias='')} "
                             f"GROUP BY {fk} ORDER BY c DESC LIMIT %s) x)")
                top_params.append(top)
        all_conds = where + conds
        # 补全集年份谓词，解锁 idx_year_diag_age 等覆盖索引（实测 >130s → 秒级）
        where_sql = where_sql_star(all_conds)

        join_sql = " ".join(merge_joins([join1, join2], fjoins))

        # avg 指标用 SUM + Python 加权（facility 维度汇总后需重新平均）
        sum_expr = ""
        if metric == "avg_charges":
            sum_expr = ", ROUND(SUM(total_charges),2) AS sum_val"
        elif metric == "avg_los":
            sum_expr = ", ROUND(SUM(length_of_stay),2) AS sum_val"
        sql = (f"SELECT {col1} AS d1, {col2} AS d2, COUNT(*) AS cnt{sum_expr} "
               f"FROM fact_discharge f {join_sql} {where_sql} "
               f"GROUP BY {col1}, {col2}")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} "
                     f"{where_sql_star(where)}")

        def post(rows):
            name_maps = {}
            if "diagnosis" in (dim1, dim2):
                name_maps["diagnosis"] = fetch_dim_names(
                    "dim_ccsr_diagnosis", "diagnosis_id")
            if "procedure" in (dim1, dim2):
                name_maps["procedure"] = fetch_dim_names(
                    "dim_ccsr_procedure", "procedure_id")
            if "service_area" in (dim1, dim2):
                name_maps["service_area"] = {
                    k: v[2] for k, v in fetch_facility_map().items()}

            def dim_value(slot, raw):
                _, _, kind, _ = HEATMAP_DIMS[slot]
                if kind == "dim":
                    pair = name_maps[slot].get(raw)
                    return (pair[0], pair[1]) if pair else ("Unknown", "Unknown")
                if kind == "facility":
                    name = name_maps["service_area"].get(raw, "Unknown")
                    return name, name
                if slot == "severity":
                    name = SEVERITY_CODE_TO_DESC.get(raw, "Unknown")
                    return name, name
                if raw is None:
                    return "Unknown", "Unknown"
                return raw, raw

            merged = {}
            for r in rows:
                v1, n1 = dim_value(dim1, r["d1"])
                v2, n2 = dim_value(dim2, r["d2"])
                key = (v1, v2)
                m = merged.get(key)
                if m is None:
                    merged[key] = m = {"dim1": v1, "dim1_name": n1,
                                       "dim2": v2, "dim2_name": n2,
                                       "count": 0, "sum": 0.0}
                m["count"] += int(r["cnt"])
                m["sum"] += float(r.get("sum_val") or 0)
            out = []
            for m in merged.values():
                if metric == "count":
                    value = m["count"]
                else:
                    value = round(m["sum"] / m["count"], 2) if m["count"] else 0
                out.append({"dim1": m["dim1"], "dim1_name": m["dim1_name"],
                            "dim2": m["dim2"], "dim2_name": m["dim2_name"],
                            "count": m["count"], "value": value})
            out.sort(key=lambda x: -x["value"])
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params + top_params, count_sql, params, post,
            extras={"top": top})
        return envelope(data, f"{dim1}_x_{dim2}", metric, total, ms, norm,
                        cached, **extra)

    return _endpoint("heatmap", request.args, handler)
