# -*- coding: utf-8 -*-
"""地区差异（柱状图 / 地区地图）：GET /api/v1/disease/region-diff
level ∈ service_area/county/facility。先按 facility_id 预聚合（<=210 行），
Python 侧按 level 汇总，避免 2M 行 JOIN；facility 无归属 12,089 条归 Unknown。
"""
from flask import request

from common import (envelope, execute_cached, fetch_facility_map, parse_choice,
                    parse_filters, parse_metric, parse_top)
from .._shared import _endpoint, disease_bp

REGION_LEVELS = {"service_area": 2, "county": 1, "facility": 0}   # 取值索引见 fetch_facility_map
REGION_DEFAULT_TOP = {"service_area": 20, "county": 20, "facility": 15}


@disease_bp.route("/region-diff")
def region_diff():
    def handler(args):
        level = parse_choice(args, "level", REGION_LEVELS, "service_area")
        metric = parse_metric(args, ("count", "total_charges", "avg_charges"))
        top = parse_top(args, REGION_DEFAULT_TOP[level], cap=50)
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        # 内层只需 cnt 与费用合计（avg 在 Python 侧加权算，facility 无归属 12,089 条归 Unknown）
        sql = (f"SELECT t.id, t.cnt, t.charges FROM ("
               f"SELECT facility_id AS id, COUNT(*) AS cnt, "
               f"ROUND(SUM(total_charges),2) AS charges "
               f"FROM fact_inpatient_discharge f {where_sql} GROUP BY facility_id) t "
               f"LEFT JOIN dim_facility fac ON t.id = fac.facility_id")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

        def post(rows):
            fac_map = fetch_facility_map()
            idx = REGION_LEVELS[level]
            groups = {}   # key -> [cnt, charges]
            for r in rows:
                key = fac_map[r["id"]][idx] if r["id"] in fac_map else "Unknown"
                cnt, charges = groups.get(key, (0, 0.0))
                groups[key] = (cnt + int(r["cnt"]), charges + float(r["charges"] or 0))
            out = []
            for key, (cnt, charges) in groups.items():
                if metric == "count":
                    value = cnt
                elif metric == "total_charges":
                    value = round(charges, 2)
                else:
                    value = round(charges / cnt, 2) if cnt else 0
                out.append({"key": key, "count": cnt, "value": value})
            out.sort(key=lambda x: -x["value"])
            return out[:top]

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, level, metric, total, ms, norm, cached, **extra)

    return _endpoint("region-diff", request.args, handler)
