# -*- coding: utf-8 -*-
"""病重趋势（堆叠柱）：GET /api/v1/disease/severity-profile
by 白名单：age_group / medical_surgical / payment。
返回长表 {group,severity,value,count}，severity 顺序 Minor<Moderate<Major<Extreme<Unknown。
数据源：medical_db 星型模型。
性能：先按外键预聚合（10M -> ~197万 组合），再 JOIN 小维度表取名。
"""
from flask import request

from common import (SEVERITY_CODE_TO_DESC, envelope, execute_cached,
                    parse_choice, parse_metric)
from .._shared import _endpoint, disease_bp
from .._star import merge_joins, parse_filters_star, where_sql_star

# by -> 反规范化事实表列（直接 GROUP BY，无需 JOIN 维度表）
SEV_BY = {
    "age_group": "f.age_group",
    "medical_surgical": "f.apr_medical_surgical",
    "payment": "f.payment_typology_1",
}


@disease_bp.route("/severity-profile")
def severity_profile():
    def handler(args):
        by = parse_choice(args, "by", SEV_BY, "age_group")
        metric = parse_metric(args, ("count", "avg_charges"))
        where, params, norm, fjoins = parse_filters_star(args)
        where_sql = where_sql_star(where)
        filter_join = " ".join(fjoins)

        by_col = SEV_BY[by]
        val_expr = ("COUNT(*)" if metric == "count"
                    else "ROUND(AVG(total_charges), 2)")

        sql = (f"SELECT {by_col} AS grp, f.apr_severity_code AS sev_code, "
               f"{val_expr} AS val, COUNT(*) AS cnt "
               f"FROM fact_discharge f {filter_join} {where_sql} "
               f"GROUP BY {by_col}, f.apr_severity_code")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_discharge f "
                     f"{filter_join} {where_sql}")

        sev_rank = {1: 0, 2: 1, 3: 2, 4: 3, None: 4}

        def grp_rank(g):
            if by == "age_group":
                try:
                    return ["0 to 17", "18 to 29", "30 to 49", "50 to 69",
                            "70 or Older"].index(g)
                except ValueError:
                    return 99
            return str(g or "")

        def post(rows):
            out = []
            for r in rows:
                out.append({"group": r["grp"] or "Unknown",
                            "severity": SEVERITY_CODE_TO_DESC.get(r["sev_code"], "Unknown"),
                            "value": r["val"], "count": int(r["cnt"]),
                            "_sort": (grp_rank(r["grp"]), sev_rank.get(r["sev_code"], 4))})
            out.sort(key=lambda x: x["_sort"])
            for row in out:
                row.pop("_sort")
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, "severity_profile", metric, total, ms, norm, cached, **extra)

    return _endpoint("severity-profile", request.args, handler)
