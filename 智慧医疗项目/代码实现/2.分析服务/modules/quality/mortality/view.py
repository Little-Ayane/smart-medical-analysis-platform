# -*- coding: utf-8 -*-
"""死亡率分析：GET /api/v1/quality/mortality
dimension ∈ diagnosis/facility/age_group/severity/risk_mortality；top 默认 20；min_cases 默认 30。
返回 [{key,name,count,deaths,mortality_rate}]，按死亡率降序。
口径：住院死亡率 = 离院去向含 'Expired' 的记录占比；dimension=risk_mortality 即
按预期死亡风险分层的观察死亡率（风险调整对照视图）。
"""
from flask import request

from common import envelope, execute_cached, parse_choice, parse_filters, parse_top
from .._shared import (MORTALITY_COND, QUALITY_DIM, _dim_parts, _endpoint,
                       parse_min_cases, quality_bp)


@quality_bp.route("/mortality")
def mortality():
    def handler(args):
        dimension = parse_choice(args, "dimension", QUALITY_DIM, "diagnosis")
        top = parse_top(args, default=20, cap=100)
        min_cases = parse_min_cases(args)
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        group_col, join_sql, key_sql, name_sql, extra_col = _dim_parts(dimension)

        extra_sql = f", {extra_col} AS extra" if extra_col else ""
        sql = (f"SELECT {key_sql} AS `key`, {name_sql} AS name, t.cnt, t.deaths"
               f"{extra_sql} "
               f"FROM (SELECT {group_col} AS id, COUNT(*) AS cnt, "
               f"SUM({MORTALITY_COND}) AS deaths "
               f"FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY {group_col} HAVING cnt >= %s) t {join_sql}")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

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
