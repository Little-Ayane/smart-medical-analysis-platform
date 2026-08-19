# -*- coding: utf-8 -*-
"""KPI 总览（大屏首页卡片）：GET /api/v1/payment/summary
3 条 SQL 一个缓存 key：总记录/总费用/总成本/avg_los/自付占比/top 支付/严重度分布/急诊数。
"""
import time as _time

from flask import request

from common import (SEVERITY_CODE_TO_DESC, cache_get, cache_key, cache_set,
                    envelope, parse_filters, timed_query)
from .._shared import _endpoint, payment_bp


@payment_bp.route("/summary")
def summary():
    def handler(args):
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        key = cache_key(request.path, args)
        hit, payload = cache_get(key)
        if hit:
            return envelope(payload["data"], "summary", "kpi", payload["total"], 0,
                            filters=norm, cached=True, **payload["extras"])

        start = _time.time()
        row1, _ = timed_query(
            f"SELECT COUNT(*) AS c, ROUND(SUM(total_charges),2) AS tc, "
            f"ROUND(SUM(total_costs),2) AS tcost, "
            f"ROUND(AVG(total_charges),2) AS ac, ROUND(AVG(total_costs),2) AS acost, "
            f"ROUND(AVG(length_of_stay),2) AS alos, "
            f"SUM(payment_typology_1='Self-Pay') AS sp, "
            f"SUM(ed_indicator='Y') AS ed "
            f"FROM fact_inpatient_discharge f {where_sql}", params)
        sev_rows, _ = timed_query(
            f"SELECT apr_severity_code AS k, COUNT(*) AS c "
            f"FROM fact_inpatient_discharge f {where_sql} "
            f"GROUP BY apr_severity_code", params)
        pay_rows, _ = timed_query(
            f"SELECT payment_typology_1 AS k, COUNT(*) AS c "
            f"FROM fact_inpatient_discharge f {where_sql} "
            f"GROUP BY payment_typology_1 ORDER BY c DESC LIMIT 1", params)
        ms = int((_time.time() - start) * 1000)

        r = row1[0]
        total = int(r["c"] or 0)
        sev_dist = {SEVERITY_CODE_TO_DESC.get(x["k"], "Unknown"): int(x["c"])
                    for x in sev_rows}
        sev_dist = {k: sev_dist[k] for k in
                    ["Minor", "Moderate", "Major", "Extreme", "Unknown"] if k in sev_dist}
        top_pay = pay_rows[0] if pay_rows else None
        data = {
            "total_records": total,
            "total_charges": float(r["tc"] or 0),
            "total_costs": float(r["tcost"] or 0),
            "avg_charges": float(r["ac"] or 0),
            "avg_costs": float(r["acost"] or 0),
            "avg_los": float(r["alos"] or 0),
            "self_pay_count": int(r["sp"] or 0),
            "self_pay_pct": round(int(r["sp"] or 0) * 100.0 / total, 2) if total else 0,
            "top_payment": ({"key": top_pay["k"], "count": int(top_pay["c"]),
                             "pct": round(int(top_pay["c"]) * 100.0 / total, 2)}
                            if top_pay else None),
            "severity_distribution": sev_dist,
            "ed_count": int(r["ed"] or 0),
        }
        payload = {"data": data, "total": total, "extras": {}}
        cache_set(key, payload)
        return envelope(data, "summary", "kpi", total, ms, norm)

    return _endpoint("summary", request.args, handler)
