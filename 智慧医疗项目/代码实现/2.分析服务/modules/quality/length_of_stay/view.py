# -*- coding: utf-8 -*-
"""平均住院日分析：GET /api/v1/quality/length-of-stay
dimension ∈ diagnosis/facility/age_group/severity/risk_mortality；top 默认 20；min_cases 默认 30。
返回 [{key,name,count,avg_los,avg_charges,avg_costs}]，按平均住院日降序。
口径：平均住院日 = AVG(length_of_stay)（天），附次均费用/成本供"费用-效率"对照观察。
"""
from flask import request

from common import envelope, execute_cached, parse_choice, parse_filters, parse_top
from .._shared import QUALITY_DIM, _dim_parts, _endpoint, parse_min_cases, quality_bp


@quality_bp.route("/length-of-stay")
def length_of_stay():
    def handler(args):
        dimension = parse_choice(args, "dimension", QUALITY_DIM, "diagnosis")
        top = parse_top(args, default=20, cap=100)
        min_cases = parse_min_cases(args)
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        group_col, join_sql, key_sql, name_sql, extra_col = _dim_parts(dimension)

        extra_sql = f", {extra_col} AS extra" if extra_col else ""
        sql = (f"SELECT {key_sql} AS `key`, {name_sql} AS name, t.cnt, t.avg_los, "
               f"t.avg_charges, t.avg_costs{extra_sql} "
               f"FROM (SELECT {group_col} AS id, COUNT(*) AS cnt, "
               f"ROUND(AVG(length_of_stay), 2) AS avg_los, "
               f"ROUND(AVG(total_charges), 2) AS avg_charges, "
               f"ROUND(AVG(total_costs), 2) AS avg_costs "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY {group_col} HAVING cnt >= %s) t {join_sql}")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

        def post(rows):
            out = []
            for r in rows:
                item = {"key": r["key"] or "Unknown",
                        "name": r["name"] or "Unknown",
                        "count": int(r["cnt"]),
                        "avg_los": float(r["avg_los"] or 0),
                        "avg_charges": float(r["avg_charges"] or 0),
                        "avg_costs": float(r["avg_costs"] or 0)}
                if extra_col:
                    item["county"] = r["extra"]
                out.append(item)
            out.sort(key=lambda x: -x["avg_los"])
            return out[:top]

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params + [min_cases], count_sql, params, post)
        return envelope(data, f"quality_los_{dimension}", "avg_los",
                        total, ms, norm, cached, **extra)

    return _endpoint("length-of-stay", request.args, handler)
