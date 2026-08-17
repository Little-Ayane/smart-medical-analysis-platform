# -*- coding: utf-8 -*-
"""支付交叉（堆叠柱 / 热力）：GET /api/v1/payment/cross
dim2 ∈ age_group/diagnosis/severity；病种维度取全局频次前 N 防止 9×477 爆表。
"""
from flask import request

from common import (SEVERITY_CODE_TO_DESC, envelope, execute_cached, fetch_dim_names,
                    parse_choice, parse_filters, parse_metric, parse_top)
from .._shared import _endpoint, payment_bp

CROSS_DIMS = {
    "age_group": ("age_group", "fact"),
    "diagnosis": ("diagnosis_id", "dim"),
    "severity": ("apr_severity_code", "fact"),
}


@payment_bp.route("/cross")
def cross():
    def handler(args):
        dim2 = parse_choice(args, "dim2", CROSS_DIMS, "age_group")
        metric = parse_metric(args, ("count", "total_charges"))
        top = parse_top(args, 15, cap=50)
        where, params, norm = parse_filters(args)

        col2, kind2 = CROSS_DIMS[dim2]
        conds = list(where)
        extra_params = []
        if kind2 == "dim":   # 病种交叉只取全局频次前 N，防止 9×477 爆表
            conds.append(f"f.{col2} IN (SELECT id FROM (SELECT {col2} AS id, "
                         f"COUNT(*) AS c FROM fact_inpatient_discharge "
                         f"GROUP BY {col2} ORDER BY c DESC LIMIT %s) x)")
            extra_params.append(top)
        conds.append("f.payment_typology_1 IS NOT NULL")
        where_sql = "WHERE " + " AND ".join(conds)

        val_expr = "" if metric == "count" else ", ROUND(SUM(total_charges),2) AS charges"
        sql = (f"SELECT payment_typology_1 AS k, {col2} AS d2, COUNT(*) AS cnt{val_expr} "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY payment_typology_1, {col2}")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
                     f"{('WHERE ' + ' AND '.join(where)) if where else ''}")

        def post(rows):
            name_map = None
            if kind2 == "dim":
                name_map = fetch_dim_names("dim_ccsr_diagnosis", "diagnosis_id")

            def dim2_value(raw):
                if kind2 == "dim":
                    pair = name_map.get(raw)
                    return (pair[0], pair[1]) if pair else ("Unknown", "Unknown")
                if dim2 == "severity":
                    name = SEVERITY_CODE_TO_DESC.get(raw, "Unknown")
                    return name, name
                return raw or "Unknown", raw or "Unknown"

            order = {"0 to 17": 0, "18 to 29": 1, "30 to 49": 2,
                     "50 to 69": 3, "70 or Older": 4}
            sev_order = {"Minor": 0, "Moderate": 1, "Major": 2,
                         "Extreme": 3, "Unknown": 4}
            out = []
            for r in rows:
                v, name = dim2_value(r["d2"])
                out.append({"key": r["k"], "dim2": v, "dim2_name": name,
                            "count": int(r["cnt"]),
                            "value": r["cnt"] if metric == "count" else r["charges"]})
            out.sort(key=lambda x: (x["key"],
                                    order.get(x["dim2"], 9) if dim2 == "age_group"
                                    else sev_order.get(x["dim2"], 9)))
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params + extra_params, count_sql, params, post,
            extras={"top": top} if kind2 == "dim" else None)
        return envelope(data, f"payment_x_{dim2}", metric, total, ms, norm,
                        cached, **extra)

    return _endpoint("cross", request.args, handler)
