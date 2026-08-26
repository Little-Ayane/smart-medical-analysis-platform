# -*- coding: utf-8 -*-
"""支付构成（饼图）：GET /api/v1/payment/composition
group ∈ payment1/2/3；该层为 NULL 的记录不计入构成，meta.null_excluded 回显排除数。
数据源：medical_db 星型模型。
"""
from flask import request

from common import envelope, execute_cached, parse_choice, parse_metric, timed_query
from star_common import JOIN_PAYMENT, merge_joins, parse_filters_star
from .._shared import _endpoint, payment_bp

PAY_GROUP_COLS = {"payment1": "f.payment_typology_1",
                  "payment2": "f.payment_typology_2",
                  "payment3": "f.payment_typology_3"}


@payment_bp.route("/composition")
def composition():
    def handler(args):
        group = parse_choice(args, "group", PAY_GROUP_COLS, "payment1")
        metric = parse_metric(args, ("count", "total_charges"))
        where, params, norm, fjoins = parse_filters_star(args)
        col = PAY_GROUP_COLS[group]
        join_sql = " ".join(fjoins)

        filter_where = ("WHERE " + " AND ".join(where)) if where else ""
        main_where = "WHERE " + " AND ".join(where + [f"{col} IS NOT NULL"])

        val_expr = "" if metric == "count" else ", ROUND(SUM(total_charges),2) AS charges"
        sql = (f"SELECT {col} AS k, COUNT(*) AS cnt{val_expr} "
               f"FROM fact_discharge f {join_sql} {main_where} "
               f"GROUP BY {col} ORDER BY cnt DESC")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} {filter_where}"

        def make_extras():
            null_rows, _ = timed_query(
                f"SELECT SUM({col} IS NULL) AS n "
                f"FROM fact_discharge f {join_sql} {filter_where}", params)
            return {"null_excluded": int(null_rows[0]["n"] or 0)}

        def post(rows):
            out = []
            if metric == "count":
                total = sum(int(r["cnt"]) for r in rows)
                for r in rows:
                    out.append({"key": r["k"], "count": int(r["cnt"]),
                                "pct": round(int(r["cnt"]) * 100.0 / total, 2)
                                if total else 0,
                                "value": r["cnt"]})
            else:
                charge_total = sum(float(r["charges"] or 0) for r in rows)
                for r in rows:
                    out.append({"key": r["k"], "count": int(r["cnt"]),
                                "pct": round(float(r["charges"] or 0) * 100.0
                                             / charge_total, 2)
                                if charge_total else 0,
                                "value": r["charges"]})
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post, make_extras)
        return envelope(data, group, metric, total, ms, norm, cached, **extra)

    return _endpoint("composition", request.args, handler)
