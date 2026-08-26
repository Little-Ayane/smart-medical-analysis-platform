# -*- coding: utf-8 -*-
"""人群差异（分组柱状）：GET /api/v1/disease/population-diff
dimension ∈ gender/race/medical_surgical；返回 {key,count,pct,value}。
数据源：medical_db 星型模型。
"""
from flask import request

from common import METRICS, envelope, execute_cached, parse_choice, parse_metric
from .._shared import _endpoint, disease_bp
from .._star import merge_joins, parse_filters_star, where_sql_star

POP_DIMS = {
    "gender": ("f.gender", ""),
    "race": ("f.race", ""),
    "medical_surgical": ("f.apr_medical_surgical", ""),
}


@disease_bp.route("/population-diff")
def population_diff():
    def handler(args):
        dimension = parse_choice(args, "dimension", POP_DIMS, "gender")
        metric = parse_metric(args, ("count", "avg_charges", "avg_los"))
        where, params, norm, fjoins = parse_filters_star(args)
        where_sql = where_sql_star(where)
        col, own_join = POP_DIMS[dimension]
        join_sql = " ".join(merge_joins([own_join], fjoins))

        val_expr = "" if metric == "count" else f", {METRICS[metric]} AS val"
        sql = (f"SELECT {col} AS k, COUNT(*) AS cnt{val_expr} "
               f"FROM fact_discharge f {join_sql} {where_sql} GROUP BY {col}")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} {where_sql}"

        def post(rows):
            total = sum(int(r["cnt"]) for r in rows)
            out = [{"key": r["k"] or "Unknown", "count": int(r["cnt"]),
                    "pct": round(int(r["cnt"]) * 100.0 / total, 2) if total else 0,
                    "value": r["cnt"] if metric == "count" else r["val"]}
                   for r in rows]
            out.sort(key=lambda x: -x["count"])
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, dimension, metric, total, ms, norm, cached, **extra)

    return _endpoint("population-diff", request.args, handler)
