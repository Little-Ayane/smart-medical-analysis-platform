# -*- coding: utf-8 -*-
"""病重趋势（堆叠柱）：GET /api/v1/disease/severity-profile
当前数据仅 2021 年、无时间维度，形态为 分组 × 严重程度构成，by 白名单：
age_group / medical_surgical / payment（by=year 暂不开放，见接口文档口径声明）。
返回长表 {group,severity,value,count}，severity 顺序 Minor<Moderate<Major<Extreme<Unknown。
"""
from flask import request

from common import (METRICS, SEVERITY_CODE_TO_DESC, envelope, execute_cached,
                    parse_choice, parse_filters, parse_metric)
from .._shared import _endpoint, disease_bp

SEV_BY = {
    "age_group": "age_group",
    "medical_surgical": "apr_medical_surgical",
    "payment": "payment_typology_1",
}


@disease_bp.route("/severity-profile")
def severity_profile():
    def handler(args):
        by = parse_choice(args, "by", SEV_BY, "age_group")
        metric = parse_metric(args, ("count", "avg_charges"))
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        by_col = SEV_BY[by]

        sql = (f"SELECT {by_col} AS grp, apr_severity_code AS sev_code, "
               f"{METRICS[metric]} AS val, COUNT(*) AS cnt "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY {by_col}, apr_severity_code")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

        sev_rank = {1: 0, 2: 1, 3: 2, 4: 3, None: 4}

        def grp_rank(g):
            if by == "age_group":
                try:
                    return ["0 to 17", "18 to 29", "30 to 49", "50 to 69",
                            "70 or Older"].index(g)
                except ValueError:
                    return 99
            return str(g or "")

        def post(rows):
            out = []
            for r in rows:
                out.append({"group": r["grp"] or "Unknown",
                            "severity": SEVERITY_CODE_TO_DESC.get(r["sev_code"], "Unknown"),
                            "value": r["val"], "count": int(r["cnt"]),
                            "_sort": (grp_rank(r["grp"]), sev_rank.get(r["sev_code"], 4))})
            out.sort(key=lambda x: x["_sort"])
            for row in out:
                row.pop("_sort")
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, "severity_profile", metric, total, ms, norm, cached, **extra)

    return _endpoint("severity-profile", request.args, handler)
