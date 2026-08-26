# -*- coding: utf-8 -*-
"""离院去向构成（饼图）：GET /api/v1/quality/disposition
数据源：medical_db 星型模型。
"""
from flask import request

from common import envelope, execute_cached
from star_common import parse_filters_star, where_sql_star
from .._shared import _endpoint, quality_bp

GROUP_ORDER = ["Home", "Transfer/Other Facility", "SNF", "Hospice",
               "Expired", "AMA", "Other"]

GROUP_CASE = """CASE
    WHEN patient_disposition = 'Expired' THEN 'Expired'
    WHEN patient_disposition = 'Left Against Medical Advice' THEN 'AMA'
    WHEN patient_disposition IN ('Hospice - Home', 'Hospice - Medical Facility') THEN 'Hospice'
    WHEN patient_disposition = 'Skilled Nursing Home' THEN 'SNF'
    WHEN patient_disposition IN ('Short-term Hospital',
                                 'Federal Health Care Facility',
                                 'Critical Access Hospital',
                                 'Psychiatric Hospital or Unit of Hosp',
                                 'Inpatient Rehabilitation Facility',
                                 'Hosp Basd Medicare Approved Swing Bed') THEN 'Transfer/Other Facility'
    WHEN patient_disposition IN ('Home or Self Care', 'Home w/ Home Health Services') THEN 'Home'
    ELSE 'Other' END"""


@quality_bp.route("/disposition")
def disposition():
    def handler(args):
        where, params, norm, fjoins = parse_filters_star(args)
        where_sql = where_sql_star(where)
        join_sql = " ".join(fjoins)

        sql = (f"SELECT {GROUP_CASE} AS grp, COUNT(*) AS cnt "
               f"FROM fact_discharge f {join_sql} {where_sql} GROUP BY grp")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} {where_sql}"

        def post(rows):
            by_key = {r["grp"]: int(r["cnt"]) for r in rows}
            total = sum(by_key.values())
            out = []
            for key in GROUP_ORDER:
                if key in by_key:
                    out.append({"key": key, "count": by_key[key],
                                "pct": round(by_key[key] * 100.0 / total, 2)})
            for key, cnt in by_key.items():
                if key not in GROUP_ORDER:
                    out.append({"key": key, "count": cnt,
                                "pct": round(cnt * 100.0 / total, 2)})
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, "disposition", "count", total, ms, norm, cached, **extra)

    return _endpoint("disposition", request.args, handler)
