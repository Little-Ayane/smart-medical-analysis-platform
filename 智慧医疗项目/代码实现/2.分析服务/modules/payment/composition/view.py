# -*- coding: utf-8 -*-
"""支付构成（饼图）：GET /api/v1/payment/composition
group ∈ payment1/2/3；该层为 NULL 的记录不计入构成（pay2 空 50.8%、pay3 空 84.2%，
不排除饼图会被吞掉），meta.null_excluded 回显排除数，pct 按排除后总数计算。
"""
from flask import request

from common import envelope, execute_cached, parse_choice, parse_filters, parse_metric, timed_query
from .._shared import _endpoint, payment_bp

PAY_GROUP_COLS = {"payment1": "payment_typology_1",
                  "payment2": "payment_typology_2",
                  "payment3": "payment_typology_3"}


@payment_bp.route("/composition")
def composition():
    def handler(args):
        group = parse_choice(args, "group", PAY_GROUP_COLS, "payment1")
        metric = parse_metric(args, ("count", "total_charges"))
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        col = PAY_GROUP_COLS[group]

        # 该层为 NULL 的记录不计入构成（pay2 空 50.8%、pay3 空 84.2%，不排除饼图会被吞掉）
        val_expr = "" if metric == "count" else ", ROUND(SUM(total_charges),2) AS charges"
        sql = (f"SELECT {col} AS k, COUNT(*) AS cnt{val_expr} "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY cnt DESC")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

        def make_extras():
            null_rows, _ = timed_query(
                f"SELECT SUM({col} IS NULL) AS n "
                f"FROM fact_inpatient_discharge f {where_sql}")
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
