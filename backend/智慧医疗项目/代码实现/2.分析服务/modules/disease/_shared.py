# -*- coding: utf-8 -*-
"""模块一 · 模块内公用：蓝图、统一异常包装、Top 排行共用预聚合函数。
性能约定：一律"先按事实表外键/列预聚合（LIMIT topN），后 JOIN 小维度表取名"。
数据源：medical_db 星型模型（fact_discharge + 维度表）。
"""
from flask import Blueprint, current_app, request

from common import (BadRequest, envelope, error, execute_cached,
                    parse_metric, parse_top, set_database)
from ._star import parse_filters_star, where_sql_star

disease_bp = Blueprint("disease", __name__, url_prefix="/api/v1/disease")


@disease_bp.before_request
def _use_medical_db():
    """试点：病种模块查询 medical_db（1000万/2020-2024）而非 smart_health。"""
    set_database("medical_db")


@disease_bp.teardown_request
def _clear_db(exc):
    set_database(None)


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
    """先按外键预聚合取 topN，再 JOIN 维度表取名。"""
    metric = parse_metric(args, metric_allowed)
    top = parse_top(args)
    where, params, norm, fjoins = parse_filters_star(args)
    # 无诊断/无手术的记录不参与排行
    where = where + [f"f.{fk_col} IS NOT NULL"]
    where_sql = where_sql_star(where)
    join_sql = " ".join(fjoins)

    metric_exprs = {
        "count": "COUNT(*) AS cnt, COUNT(*) AS val",
        "total_charges": "COUNT(*) AS cnt, ROUND(SUM(total_charges),2) AS val",
        "avg_charges": "COUNT(*) AS cnt, ROUND(AVG(total_charges),2) AS val",
        "avg_los": "COUNT(*) AS cnt, ROUND(AVG(length_of_stay),2) AS val",
    }
    sql = (f"SELECT t.id, t.cnt, t.val, d.ccsr_code AS code, d.description AS name "
           f"FROM (SELECT f.{fk_col} AS id, {metric_exprs[metric]} "
           f"FROM fact_discharge f {join_sql} {where_sql} "
           f"GROUP BY f.{fk_col} ORDER BY val DESC LIMIT %s) t "
           f"JOIN {dim_table} d ON t.id = d.{pk} ORDER BY t.val DESC")
    count_sql = f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} {where_sql}"

    def post(rows):
        return [{"code": r["code"], "name": r["name"], "count": int(r["cnt"]),
                 "value": r["val"]} for r in rows]

    data, total, ms, cached, extra = execute_cached(
        request.path, args, sql, params + [top], count_sql, params, post)
    return envelope(data, dimension, metric, total, ms, norm, cached, **extra)
