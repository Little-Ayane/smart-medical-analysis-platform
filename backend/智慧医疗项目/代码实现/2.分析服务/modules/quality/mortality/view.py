# -*- coding: utf-8 -*-
"""死亡率分析：GET /api/v1/quality/mortality
dimension ∈ diagnosis/facility/age_group/severity/risk_mortality。数据源：medical_db 星型模型。
"""
from flask import request

from common import envelope, execute_cached, parse_choice, parse_top
from star_common import merge_joins, parse_filters_star, where_sql_star
from .._shared import (MORTALITY_COND, QUALITY_DIM, _dim_parts, _endpoint,
                       parse_min_cases, quality_bp)


@quality_bp.route("/mortality")
def mortality():
    def handler(args):
        dimension = parse_choice(args, "dimension", QUALITY_DIM, "diagnosis")
        top = parse_top(args, default=20, cap=100)
        min_cases = parse_min_cases(args)
        where, params, norm, fjoins = parse_filters_star(args)
        where_sql = where_sql_star(where)
        group_col, inner_join, outer_join, key_sql, name_sql, extra_col, ignore_idx = _dim_parts(dimension)
        inner_joins = " ".join(merge_joins([inner_join], fjoins))
        ignore = f" IGNORE INDEX ({ignore_idx})" if ignore_idx else ""

        extra_sql = f", {extra_col} AS extra" if extra_col else ""
        sql = (f"SELECT {key_sql} AS `key`, {name_sql} AS name, t.cnt, t.deaths"
               f"{extra_sql} "
               f"FROM (SELECT {group_col} AS id, COUNT(*) AS cnt, "
               f"SUM({MORTALITY_COND}) AS deaths "
               f"FROM fact_discharge f{ignore} {inner_joins} {where_sql} "
               f"GROUP BY {group_col} HAVING cnt >= %s) t {outer_join}")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {inner_joins} {where_sql}"

        def post(rows):
            out = []
            for r in rows:
                item = {"key": r["key"] or "Unknown",
                        "name": r["name"] or "Unknown",
                        "count": int(r["cnt"]),
                        "deaths": int(r["deaths"] or 0),
                        "mortality_rate": round(int(r["deaths"] or 0) * 100.0
                                               / int(r["cnt"]), 2)}
                if extra_col:
                    item["county"] = r["extra"]
                out.append(item)
            out.sort(key=lambda x: -x["mortality_rate"])
            return out[:top]

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params + [min_cases], count_sql, params, post)
        return envelope(data, f"quality_mortality_{dimension}", "mortality_rate",
                        total, ms, norm, cached, **extra)

    return _endpoint("mortality", request.args, handler)
