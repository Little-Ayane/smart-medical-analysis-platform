# -*- coding: utf-8 -*-
"""医院质量横向对比：GET /api/v1/quality/facility-ranking
top 默认 15；min_cases 默认 100（出院量不足的医院比率失真，予以剔除）。
返回 [{key,name,county,count,deaths,mortality_rate,avg_los,ed_rate,ama_rate,
       transfer_rate,newborns,lbw_rate,avg_charges,avg_costs}]，按出院量降序
（横向对比需统一分母口径，比率全部由本接口在 Python 侧计算）。
facility 无归属的 12,089 条归 Unknown（与 region-diff 口径一致）。
"""
from flask import request

from common import envelope, execute_cached, parse_filters, parse_top
from .._shared import (AMA_COND, LBW_COND, MORTALITY_COND, TRANSFER_COND, _endpoint,
                       parse_min_cases, quality_bp)


@quality_bp.route("/facility-ranking")
def facility_ranking():
    def handler(args):
        top = parse_top(args, default=15, cap=100)
        min_cases = parse_min_cases(args, default=100)
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        sql = (f"SELECT t.id, t.cnt, t.deaths, t.avg_los, t.ed, t.ama, t.transfer, "
               f"t.newborns, t.lbw, t.avg_charges, t.avg_costs, "
               f"h.facility_name AS name, h.hospital_county AS county "
               f"FROM (SELECT facility_id AS id, COUNT(*) AS cnt, "
               f"SUM({MORTALITY_COND}) AS deaths, "
               f"ROUND(AVG(length_of_stay), 2) AS avg_los, "
               f"SUM(ed_indicator = 'Y') AS ed, "
               f"SUM({AMA_COND}) AS ama, "
               f"SUM({TRANSFER_COND}) AS transfer, "
               f"SUM(birth_weight IS NOT NULL) AS newborns, "
               f"SUM({LBW_COND}) AS lbw, "
               f"ROUND(AVG(total_charges), 2) AS avg_charges, "
               f"ROUND(AVG(total_costs), 2) AS avg_costs "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY facility_id HAVING cnt >= %s) t "
               f"LEFT JOIN dim_facility h ON t.id = h.facility_id")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

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
