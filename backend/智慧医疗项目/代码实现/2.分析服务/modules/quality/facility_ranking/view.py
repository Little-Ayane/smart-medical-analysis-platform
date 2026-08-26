# -*- coding: utf-8 -*-
"""医院质量横向对比：GET /api/v1/quality/facility-ranking
数据源：medical_db 星型模型。
"""
from flask import request

from common import envelope, execute_cached, parse_top
from star_common import parse_filters_star, where_sql_star
from .._shared import (AMA_COND, LBW_COND, MORTALITY_COND, TRANSFER_COND, _endpoint,
                       parse_min_cases, quality_bp)


@quality_bp.route("/facility-ranking")
def facility_ranking():
    def handler(args):
        top = parse_top(args, default=15, cap=100)
        min_cases = parse_min_cases(args, default=100)
        where, params, norm, fjoins = parse_filters_star(args)
        where_sql = where_sql_star(where)
        join_sql = " ".join(fjoins)

        sql = (f"SELECT t.id, t.cnt, t.deaths, t.avg_los, t.ed, t.ama, t.transfer, "
               f"t.newborns, t.lbw, t.avg_charges, t.avg_costs, "
               f"h.facility_name AS name, h.hospital_county AS county "
               f"FROM (SELECT f.hospital_id AS id, COUNT(*) AS cnt, "
               f"SUM({MORTALITY_COND}) AS deaths, "
               f"ROUND(AVG(length_of_stay), 2) AS avg_los, "
               f"SUM(f.emergency_department_indicator = 'Y') AS ed, "
               f"SUM({AMA_COND}) AS ama, "
               f"SUM({TRANSFER_COND}) AS transfer, "
               f"SUM(birth_weight IS NOT NULL) AS newborns, "
               f"SUM({LBW_COND}) AS lbw, "
               f"ROUND(AVG(total_charges), 2) AS avg_charges, "
               f"ROUND(AVG(total_costs), 2) AS avg_costs "
               f"FROM fact_discharge f IGNORE INDEX (idx_hospital) {join_sql} {where_sql} "
               f"GROUP BY f.hospital_id HAVING cnt >= %s) t "
               f"LEFT JOIN dim_facility h ON t.id = h.facility_id")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} {where_sql}"

        def post(rows):
            out = []
            for r in rows:
                cnt = int(r["cnt"])
                newborns = int(r["newborns"] or 0)

                def _rate(x):
                    return round(int(x or 0) * 100.0 / cnt, 2) if cnt else 0

                out.append({
                    "key": r["name"] or "Unknown",
                    "name": r["name"] or "Unknown",
                    "county": r["county"],
                    "count": cnt,
                    "deaths": int(r["deaths"] or 0),
                    "mortality_rate": _rate(r["deaths"]),
                    "avg_los": float(r["avg_los"] or 0),
                    "ed_rate": _rate(r["ed"]),
                    "ama_rate": _rate(r["ama"]),
                    "transfer_rate": _rate(r["transfer"]),
                    "newborns": newborns,
                    "lbw_rate": (round(int(r["lbw"] or 0) * 100.0 / newborns, 2)
                                 if newborns else None),
                    "avg_charges": float(r["avg_charges"] or 0),
                    "avg_costs": float(r["avg_costs"] or 0),
                })
            out.sort(key=lambda x: -x["count"])
            return out[:top]

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params + [min_cases], count_sql, params, post)
        return envelope(data, "quality_facility", "kpi",
                        total, ms, norm, cached, **extra)

    return _endpoint("facility-ranking", request.args, handler)
