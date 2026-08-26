# -*- coding: utf-8 -*-
"""地区差异（柱状图 / 地区地图）：GET /api/v1/disease/region-diff
level ∈ service_area/county/facility。先按 hospital_id 预聚合，Python 侧按 level 汇总。
数据源：medical_db 星型模型。
"""
from flask import request

from common import (envelope, execute_cached, fetch_facility_map, parse_choice,
                    parse_metric, parse_top)
from .._shared import _endpoint, disease_bp
from .._star import parse_filters_star, where_sql_star

REGION_LEVELS = {"service_area": 2, "county": 1, "facility": 0}   # 取值索引见 fetch_facility_map
REGION_DEFAULT_TOP = {"service_area": 20, "county": 20, "facility": 15}


@disease_bp.route("/region-diff")
def region_diff():
    def handler(args):
        level = parse_choice(args, "level", REGION_LEVELS, "service_area")
        metric = parse_metric(args, ("count", "total_charges", "avg_charges"))
        top = parse_top(args, REGION_DEFAULT_TOP[level], cap=50)
        where, params, norm, fjoins = parse_filters_star(args)
        # 补全集年份谓词，让 GROUP BY hospital_id 能走 idx_y_hosp_full 覆盖索引
        # （否则退化为千万次主键回表，实测 >130s）
        where_sql = where_sql_star(where)
        join_sql = " ".join(fjoins)

        # 内层只按 hospital_id 预聚合（avg 在 Python 侧加权算）
        sql = (f"SELECT f.hospital_id AS id, COUNT(*) AS cnt, "
               f"ROUND(SUM(f.total_charges),2) AS charges "
               f"FROM fact_discharge f {join_sql} {where_sql} GROUP BY f.hospital_id")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} {where_sql}"

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
