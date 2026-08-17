# -*- coding: utf-8 -*-
"""支付费用关系（散点图）：GET /api/v1/payment/cost-relation
by ∈ payment/age_group/diagnosis；返回 {key,count,avg_charges,avg_costs,
charge_cost_ratio}，前端建议 x=avg_costs、y=avg_charges、气泡=count、
颜色=charge_cost_ratio（费用与成本近共线，比率提供信息量）。
"""
from flask import request

from common import envelope, execute_cached, fetch_dim_names, parse_choice, parse_filters, parse_top
from .._shared import _endpoint, payment_bp

COST_BY = {"payment": ("payment_typology_1", "fact"),
           "age_group": ("age_group", "fact"),
           "diagnosis": ("diagnosis_id", "dim")}


@payment_bp.route("/cost-relation")
def cost_relation():
    def handler(args):
        by = parse_choice(args, "by", COST_BY, "payment")
        top = parse_top(args, 30, cap=100)
        where, params, norm = parse_filters(args)
        col, kind = COST_BY[by]

        conds = list(where)
        extra_params = []
        limit_sql = ""
        if kind == "dim":
            conds.append(f"f.{col} IN (SELECT id FROM (SELECT {col} AS id, "
                         f"COUNT(*) AS c FROM fact_inpatient_discharge "
                         f"GROUP BY {col} ORDER BY c DESC LIMIT %s) x)")
            extra_params.append(top)
            limit_sql = f" LIMIT {top}"
        where_sql = ("WHERE " + " AND ".join(conds)) if conds else ""

        sql = (f"SELECT {col} AS k, COUNT(*) AS cnt, "
               f"ROUND(AVG(total_charges),2) AS avg_charges, "
               f"ROUND(AVG(total_costs),2) AS avg_costs "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY {col} ORDER BY cnt DESC{limit_sql}")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
                     f"{('WHERE ' + ' AND '.join(where)) if where else ''}")

        def post(rows):
            name_map = fetch_dim_names("dim_ccsr_diagnosis", "diagnosis_id") \
                if kind == "dim" else None
            out = []
            for r in rows:
                ac = float(r["avg_charges"] or 0)
                aco = float(r["avg_costs"] or 0)
                item = {"key": r["k"] or "Unknown", "count": int(r["cnt"]),
                        "avg_charges": ac, "avg_costs": aco,
                        "charge_cost_ratio": round(ac / aco, 2) if aco else None}
                if kind == "dim":
                    pair = name_map.get(r["k"])
                    item["name"] = pair[1] if pair else None
                out.append(item)
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params + extra_params, count_sql, params, post)
        return envelope(data, by, "cost_relation", total, ms, norm, cached, **extra)

    return _endpoint("cost-relation", request.args, handler)
