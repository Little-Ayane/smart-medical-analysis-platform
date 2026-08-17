# -*- coding: utf-8 -*-
"""人口金字塔（性别 × 年龄段，专用结构）：GET /api/v1/disease/pyramid
返回 {age_group,male,female,total}；排除 151 条 gender NULL（total_records=2,056,623）。
SQL 用 SUM(gender='M') 一次出两列（idx_age_gender 覆盖扫描）。
"""
from flask import request

from common import AGE_ORDER_SQL, envelope, execute_cached, parse_filters
from .._shared import _endpoint, disease_bp


@disease_bp.route("/pyramid")
def pyramid():
    def handler(args):
        where, params, norm = parse_filters(args)
        # 151 条 gender NULL 不参与金字塔（文档口径声明）
        conds = where + ["f.gender IS NOT NULL"]
        where_sql = "WHERE " + " AND ".join(conds)
        sql = (f"SELECT age_group, SUM(gender='M') AS male, SUM(gender='F') AS female, "
               f"COUNT(*) AS total FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY age_group ORDER BY {AGE_ORDER_SQL}")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

        def post(rows):
            return [{"age_group": r["age_group"],
                     "male": int(r["male"] or 0), "female": int(r["female"] or 0),
                     "total": int(r["total"] or 0)} for r in rows]

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, "age_group_gender", "count", total, ms, norm, cached, **extra)

    return _endpoint("pyramid", request.args, handler)
