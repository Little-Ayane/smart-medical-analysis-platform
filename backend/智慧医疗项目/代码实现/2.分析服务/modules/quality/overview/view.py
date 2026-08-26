# -*- coding: utf-8 -*-
"""质量总览 KPI（大屏首页卡片）：GET /api/v1/quality/overview
数据源：medical_db 星型模型。
"""
import time as _time

from flask import request

from common import cache_get, cache_key, cache_set, envelope, timed_query
from star_common import parse_filters_star, where_sql_star
from .._shared import (AMA_COND, LBW_COND, MORTALITY_COND, TRANSFER_COND, _endpoint,
                       quality_bp)


@quality_bp.route("/overview")
def overview():
    def handler(args):
        where, params, norm, fjoins = parse_filters_star(args)
        where_sql = where_sql_star(where)
        join_sql = " ".join(fjoins)

        key = cache_key(request.path, args)
        hit, payload = cache_get(key)
        if hit:
            return envelope(payload["data"], "quality_overview", "kpi", payload["total"],
                            0, filters=norm, cached=True, **payload["extras"])

        start = _time.time()
        rows, _ = timed_query(
            f"SELECT COUNT(*) AS c, "
            f"SUM({MORTALITY_COND}) AS deaths, "
            f"SUM({AMA_COND}) AS ama, "
            f"SUM({TRANSFER_COND}) AS transfer, "
            f"SUM(f.emergency_department_indicator = 'Y') AS ed, "
            f"ROUND(AVG(length_of_stay), 2) AS alos, "
            f"SUM(birth_weight IS NOT NULL) AS newborns, "
            f"SUM({LBW_COND}) AS lbw, "
            f"ROUND(AVG(total_charges), 2) AS ac, "
            f"ROUND(AVG(total_costs), 2) AS acost "
            f"FROM fact_discharge f {join_sql} {where_sql}", params)
        ms = int((_time.time() - start) * 1000)

        r = rows[0]
        total = int(r["c"] or 0)
        newborns = int(r["newborns"] or 0)

        def _rate(cnt):
            return round(int(cnt or 0) * 100.0 / total, 2) if total else 0

        data = {
            "total_records": total,
            "deaths": int(r["deaths"] or 0),
            "mortality_rate": _rate(r["deaths"]),
            "avg_los": float(r["alos"] or 0),
            "ed_count": int(r["ed"] or 0),
            "ed_rate": _rate(r["ed"]),
            "ama_count": int(r["ama"] or 0),
            "ama_rate": _rate(r["ama"]),
            "transfer_count": int(r["transfer"] or 0),
            "transfer_rate": _rate(r["transfer"]),
            "newborns": newborns,
            "lbw_count": int(r["lbw"] or 0),
            "lbw_rate": round(int(r["lbw"] or 0) * 100.0 / newborns, 2) if newborns else None,
            "avg_charges": float(r["ac"] or 0),
            "avg_costs": float(r["acost"] or 0),
        }
        payload = {"data": data, "total": total, "extras": {}}
        cache_set(key, payload)
        return envelope(data, "quality_overview", "kpi", total, ms, norm)

    return _endpoint("overview", request.args, handler)
