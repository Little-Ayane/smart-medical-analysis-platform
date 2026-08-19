# -*- coding: utf-8 -*-
"""通用热力图（ECharts heatmap 长表）：GET /api/v1/disease/heatmap
dim1/dim2 白名单：diagnosis/procedure/age_group/severity/gender/payment/service_area
（dim1 ≠ dim2）。top 语义：diagnosis/procedure 维度取全局频次前 N（独立于当前
过滤，保证切换过滤条件时排行稳定），其余维度全量（基数 <= 9）。
"""
from flask import request

from common import (BadRequest, SEVERITY_CODE_TO_DESC, envelope, execute_cached,
                    fetch_dim_names, fetch_facility_map, parse_choice,
                    parse_filters, parse_metric, parse_top)
from .._shared import _endpoint, disease_bp

HEATMAP_DIMS = {
    "diagnosis": ("diagnosis_id", "dim"),
    "procedure": ("procedure_id", "dim"),
    "age_group": ("age_group", "fact"),
    "severity": ("apr_severity_code", "fact"),
    "gender": ("gender", "fact"),
    "payment": ("payment_typology_1", "fact"),
    "service_area": ("facility_id", "facility"),
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
        where, params, norm = parse_filters(args)

        col1, kind1 = HEATMAP_DIMS[dim1]
        col2, kind2 = HEATMAP_DIMS[dim2]

        # topN 子查询：只针对 diagnosis/procedure（其余维度基数小全量即可）
        conds, top_params = [], []
        for col, kind in ((col1, kind1), (col2, kind2)):
            if kind == "dim":
                conds.append(f"f.{col} IN (SELECT id FROM (SELECT {col} AS id, "
                             f"COUNT(*) AS c FROM fact_inpatient_discharge "
                             f"GROUP BY {col} ORDER BY c DESC LIMIT %s) x)")
                top_params.append(top)
        all_conds = where + conds
        where_sql = ("WHERE " + " AND ".join(all_conds)) if all_conds else ""

        # avg 指标用 SUM + Python 加权（facility 维度汇总后需重新平均）
        sum_expr = ""
        if metric == "avg_charges":
            sum_expr = ", ROUND(SUM(total_charges),2) AS sum_val"
        elif metric == "avg_los":
            sum_expr = ", ROUND(SUM(length_of_stay),2) AS sum_val"
        sql = (f"SELECT f.{col1} AS d1, f.{col2} AS d2, COUNT(*) AS cnt{sum_expr} "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY f.{col1}, f.{col2}")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
                     f"{('WHERE ' + ' AND '.join(where)) if where else ''}")

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
                """原始值 -> (编码值, 展示名)。"""
                _, kind = HEATMAP_DIMS[slot]
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
