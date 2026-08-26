# -*- coding: utf-8 -*-
"""人口金字塔（性别 × 年龄段，专用结构）：GET /api/v1/disease/pyramid
返回 {age_group,male,female,total}。数据源：medical_db 星型模型。
"""
from flask import request

from common import envelope, execute_cached
from .._shared import _endpoint, disease_bp
from .._star import merge_joins, parse_filters_star

AGE_ORDER = ("FIELD(f.age_group, '0 to 17','18 to 29','30 to 49',"
             "'50 to 69','70 or Older')")


@disease_bp.route("/pyramid")
def pyramid():
    def handler(args):
        where, params, norm, fjoins = parse_filters_star(args)
        # 排除 gender NULL 不参与金字塔
        conds = where + ["f.gender IS NOT NULL"]
        where_sql = "WHERE " + " AND ".join(conds)
        join_sql = " ".join(fjoins)

        sql = (f"SELECT f.age_group, SUM(f.gender='M') AS male, "
               f"SUM(f.gender='F') AS female, COUNT(*) AS total "
               f"FROM fact_discharge f {join_sql} {where_sql} "
               f"GROUP BY f.age_group ORDER BY {AGE_ORDER}")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} {where_sql}"

        def post(rows):
            return [{"age_group": r["age_group"],
                     "male": int(r["male"] or 0), "female": int(r["female"] or 0),
                     "total": int(r["total"] or 0)} for r in rows]

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, "age_group_gender", "count", total, ms, norm, cached, **extra)

    return _endpoint("pyramid", request.args, handler)
