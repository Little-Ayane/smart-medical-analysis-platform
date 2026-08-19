# -*- coding: utf-8 -*-
"""模块一 · 模块内公用：蓝图、统一异常包装、Top 排行共用预聚合函数。
性能约定：一律"先按事实表外键/列预聚合（LIMIT topN），后 JOIN 小维度表取名"。
"""
from flask import Blueprint, current_app, request

from common import (BadRequest, envelope, error, execute_cached, parse_filters,
                    parse_metric, parse_top)

disease_bp = Blueprint("disease", __name__, url_prefix="/api/v1/disease")


def _endpoint(path, args, handler):
    """统一异常处理：BadRequest -> 400；其他异常记日志 -> 500（不抛裸异常）。"""
    try:
        return handler(args)
    except BadRequest as e:
        return error(400, str(e))
    except Exception:
        current_app.logger.exception("[disease/%s] 处理异常", path)
        return error(500, "服务内部错误")


# ------------------------------------------------------------
# Top 诊断排行 / 手术谱排行 共用预聚合函数
# ------------------------------------------------------------
def _top_by_dim(fk_col, dim_table, pk, args, dimension, metric_allowed):
    """先按外键预聚合取 topN，再 JOIN 维度表取名（实测 0.7s vs 旧模式 4.3s）。"""
    metric = parse_metric(args, metric_allowed)
    top = parse_top(args)
    where, params, norm = parse_filters(args)
    # 无诊断/无手术的记录不参与排行（top-procedures 口径 = 1,500,426 条）
    where = where + [f"f.{fk_col} IS NOT NULL"]
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    metric_exprs = {
        "count": "COUNT(*) AS cnt, COUNT(*) AS val",
        "total_charges": "COUNT(*) AS cnt, ROUND(SUM(total_charges),2) AS val",
        "avg_charges": "COUNT(*) AS cnt, ROUND(AVG(total_charges),2) AS val",
        "avg_los": "COUNT(*) AS cnt, ROUND(AVG(length_of_stay),2) AS val",
    }
    sql = (f"SELECT t.id, t.cnt, t.val, d.ccsr_code AS code, d.description AS name "
           f"FROM (SELECT {fk_col} AS id, {metric_exprs[metric]} "
           f"FROM fact_inpatient_discharge f {where_sql} "
           f"GROUP BY {fk_col} ORDER BY val DESC LIMIT %s) t "
           f"JOIN {dim_table} d ON t.id = d.{pk} ORDER BY t.val DESC")
    count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

    def post(rows):
        return [{"code": r["code"], "name": r["name"], "count": int(r["cnt"]),
                 "value": r["val"]} for r in rows]

    data, total, ms, cached, extra = execute_cached(
        request.path, args, sql, params + [top], count_sql, params, post)
    return envelope(data, dimension, metric, total, ms, norm, cached, **extra)
