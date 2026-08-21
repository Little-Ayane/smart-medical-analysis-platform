# -*- coding: utf-8 -*-
"""
纪志鹏 - 费用成本分析模块（5 个接口）
功能：费用成本差、利润率、成本效益排行、费用构成、年度趋势
兼容：P4 对接 —— data 统一 key/value/count 字段，另附扩展字段供前端详展
规范：复用 common（统一信封 + 过滤白名单 + 参数解析 + TTL 缓存），与 disease|payment 模块一致
库：smart_health 主库（fact_inpatient_discharge + dim_apr_drg/dim_ccsr_diagnosis/dim_facility）
注意：调试期请确认 common.py 中 DB 连接信息与本机一致（root 密码）。
"""
from flask import request

from common import (BadRequest, envelope, error, execute_cached, parse_choice,
                    parse_filters, parse_top, timed_query)

# ------------------------------------------------------------
# 维度 -> (分组列, JOIN 子句, key 表达式)（smart_health 主库 schema）
# 事实表列：age_group / payment_typology_1 无需 JOIN；
# 外键类：drg/mdc/diagnosis/facility 需 JOIN 对应维度表取名。
# ------------------------------------------------------------
DIM = {
    "drg":              ("f.drg_id",       "JOIN dim_apr_drg d ON f.drg_id = d.drg_id",
                         "d.apr_drg_desc"),
    "mdc":              ("f.drg_id",       "JOIN dim_apr_drg d ON f.drg_id = d.drg_id",
                         "d.apr_mdc_desc"),
    "diagnosis":        ("f.diagnosis_id", "JOIN dim_ccsr_diagnosis d2 ON f.diagnosis_id = d2.diagnosis_id",
                         "d2.description"),
    "facility":         ("f.facility_id",  "JOIN dim_facility h ON f.facility_id = h.facility_id",
                         "h.facility_name"),
    "age_group":        ("f.age_group",    "",
                         "f.age_group"),
    "payment_typology": ("f.payment_typology_1", "",
                         "f.payment_typology_1"),
}

# 利润率表达式（接口 2/3 与 CASE 复用，避免重复）
_MARGIN = "(SUM(f.total_charges) - SUM(f.total_costs)) / SUM(f.total_costs) * 100"


def _to_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} 必须为整数，收到: {raw}")


def _cost(fn):
    """统一参数校验兜底：BadRequest -> 400 信封（与主模块 _endpoint 一致）。"""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except BadRequest as e:
            return error(400, str(e))
    wrapper.__name__ = fn.__name__
    return wrapper


# ------------------------------------------------------------
# 排行类接口共享实现（接口 1/2/3 共用：费用成本差 / 利润率 / 成本效益排行）
# 先按维度 GROUP BY 预聚合 + JOIN 维度表取名，LIMIT topN 后排序；
# 过滤走 common.parse_filters（12 种白名单、防注入、参数化）。
# ------------------------------------------------------------
def _rank_endpoint(args, metric, default_top=20, extra_select="", order_opt=False):
    dimension = parse_choice(args, "dimension", DIM, "drg")
    _, join_sql, key_expr = DIM[dimension]
    top = parse_top(args, default=default_top)
    order = "DESC"
    if order_opt:
        order = "DESC" if args.get("order", "desc").lower() == "desc" else "ASC"

    where, params, norm = parse_filters(args)
    where.append("f.total_charges IS NOT NULL")
    where.append("f.total_costs IS NOT NULL")
    if metric in ("profit_margin", "efficiency_ranking"):
        where.append("f.total_costs > 0")
    where_sql = "WHERE " + " AND ".join(where)

    value_expr = ("ROUND(SUM(f.total_charges) - SUM(f.total_costs), 2)"
                  if metric == "profit_difference"
                  else f"ROUND({_MARGIN}, 2)")

    sql = (f"SELECT {key_expr} AS `key`, COUNT(*) AS `count`, "
           f"{value_expr} AS `value`{extra_select} "
           f"FROM fact_inpatient_discharge f {join_sql} {where_sql} "
           f"GROUP BY {key_expr} HAVING `count` >= 10 "
           f"ORDER BY `value` {order} LIMIT %s")
    count_sql = (f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
                 f"{join_sql} {where_sql}")

    data, total, ms, cached, extra = execute_cached(
        request.path, args, sql, params + [top], count_sql, params)
    return envelope(data, dimension, metric, total, ms,
                    filters=norm, cached=cached, **extra)


def register_cost_routes(app):

    # ---------- 1. 费用成本差 ----------
    # key=维度值, value=费用-成本差(元), count=病例数
    # 扩展：total_charges/total_costs/avg_charges/avg_costs/avg_profit_difference
    @app.route("/api/v1/cost/profit-difference")
    @_cost
    def cost_profit_difference():
        extras = (", ROUND(SUM(f.total_charges), 2) AS total_charges"
                  ", ROUND(SUM(f.total_costs), 2) AS total_costs"
                  ", ROUND(AVG(f.total_charges), 2) AS avg_charges"
                  ", ROUND(AVG(f.total_costs), 2) AS avg_costs"
                  ", ROUND(AVG(f.total_charges) - AVG(f.total_costs), 2) AS avg_profit_difference")
        return _rank_endpoint(request.args, "profit_difference",
                              default_top=20, extra_select=extras)

    # ---------- 2. 利润率 ----------
    # value=利润率(%)，count=病例数；支持 order=asc/desc
    @app.route("/api/v1/cost/profit-margin")
    @_cost
    def cost_profit_margin():
        extras = (", ROUND(SUM(f.total_charges), 2) AS total_charges"
                  ", ROUND(SUM(f.total_costs), 2) AS total_costs"
                  f", ROUND({_MARGIN}, 2) AS profit_margin_pct"
                  ", ROUND(AVG(f.total_charges), 2) AS avg_charges"
                  ", ROUND(AVG(f.total_costs), 2) AS avg_costs"
                  f", ROUND(AVG(f.total_charges) - AVG(f.total_costs), 2) AS avg_profit_difference")
        return _rank_endpoint(request.args, "profit_margin",
                              default_top=20, extra_select=extras, order_opt=True)

    # ---------- 3. 成本效益排行 ----------
    # value=利润率(%)，efficiency_grade=A/B/C/D 等级，grade_basis=等级依据
    @app.route("/api/v1/cost/efficiency-ranking")
    @_cost
    def cost_efficiency_ranking():
        extras = (", ROUND(SUM(f.total_charges), 2) AS total_charges"
                  ", ROUND(SUM(f.total_costs), 2) AS total_costs"
                  f", ROUND({_MARGIN}, 2) AS profit_margin_pct"
                  ", ROUND(AVG(f.total_charges), 2) AS avg_charges"
                  ", ROUND(AVG(f.total_costs), 2) AS avg_costs"
                  f", CASE WHEN {_MARGIN} > 15 THEN 'A（高效益）'"
                  f" WHEN {_MARGIN} > 10 THEN 'B（中高效益）'"
                  f" WHEN {_MARGIN} > 5 THEN 'C（中低效益）'"
                  " ELSE 'D（低效益）' END AS efficiency_grade"
                  f", CONCAT('利润率 ', ROUND({_MARGIN}, 2), '%%') AS grade_basis")
        return _rank_endpoint(request.args, "efficiency_ranking",
                              default_top=30, extra_select=extras)

    # ---------- 4. 费用构成 ----------
    # value=占总费用百分比(%)，meta.total_charges_all=总费用
    @app.route("/api/v1/cost/composition")
    @_cost
    def cost_composition():
        args = request.args
        dimension = parse_choice(args, "dimension", DIM, "mdc")
        _, join_sql, key_expr = DIM[dimension]
        top = parse_top(args, default=10, cap=50)
        where, params, norm = parse_filters(args)
        where.append("f.total_charges IS NOT NULL")
        where_sql = "WHERE " + " AND ".join(where)

        # 先算总费用（静态快照，随查询走；作为占比分母）
        total_rows, _ = timed_query(
            f"SELECT ROUND(SUM(f.total_charges), 2) AS total_all "
            f"FROM fact_inpatient_discharge f {where_sql}", params)
        total_all = total_rows[0]["total_all"] if total_rows and total_rows[0]["total_all"] else 1

        sql = (f"SELECT {key_expr} AS `key`, COUNT(*) AS `count`, "
               f"ROUND(SUM(f.total_charges) / %s * 100, 2) AS `value`, "
               f"ROUND(SUM(f.total_charges), 2) AS total_charges, "
               f"ROUND(AVG(f.total_charges), 2) AS avg_charges, "
               f"ROUND(SUM(f.total_charges) / %s * 100, 2) AS pct "
               f"FROM fact_inpatient_discharge f {join_sql} {where_sql} "
               f"GROUP BY {key_expr} ORDER BY SUM(f.total_charges) DESC LIMIT %s")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
                     f"{join_sql} {where_sql}")

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, [total_all, total_all] + params + [top],
            count_sql, params, extras={"total_charges_all": total_all})
        return envelope(data, dimension, "composition_pct", total, ms,
                        filters=norm, cached=cached, **extra)

    # ---------- 5. 年度趋势 ----------
    # 按年份统计费用/成本/利润率趋势；可选 dimension + dimension_value 限定单条线
    @app.route("/api/v1/cost/trend")
    @_cost
    def cost_trend():
        args = request.args
        dimension = args.get("dimension")
        if dimension is not None and dimension not in DIM:
            raise BadRequest(f"dimension 仅支持 {sorted(DIM)}，收到: {dimension}")
        metric = args.get("metric", "total_charges")
        if metric not in ("total_charges", "profit_margin", "total_costs"):
            raise BadRequest(f"metric 仅支持 total_charges/profit_margin/total_costs，收到: {metric}")

        where, params = [], []
        if args.get("start_year"):
            where.append("f.discharge_year >= %s")
            params.append(_to_int("start_year", args["start_year"]))
        if args.get("end_year"):
            where.append("f.discharge_year <= %s")
            params.append(_to_int("end_year", args["end_year"]))
        where.append("f.total_charges IS NOT NULL")
        where.append("f.total_costs IS NOT NULL")
        where.append("f.total_costs > 0")
        where_sql = "WHERE " + " AND ".join(where)

        # 可选维度：dimension_key 列 + join + 过滤
        dim_select = ""
        dim_group = ""
        dim_order = ""
        if dimension:
            _, join_sql, key_expr = DIM[dimension]
            dim_select = f", {key_expr} AS dimension_key"
            dim_group = f", {key_expr}"
            dim_order = f", {key_expr} ASC"
            if args.get("dimension_value"):
                where.append(f"{key_expr} = %s")
                params.append(args["dimension_value"])
            # 注意 where_sql 在 join 确定后才完整，重新拼接
            where_sql = "WHERE " + " AND ".join(where)
            join_sql = join_sql or ""
        else:
            join_sql = ""

        if metric == "profit_margin":
            value_field = f"ROUND({_MARGIN}, 2)"
        elif metric == "total_costs":
            value_field = "ROUND(SUM(f.total_costs), 2)"
        else:
            value_field = "ROUND(SUM(f.total_charges), 2)"

        sql = (f"SELECT f.discharge_year AS `year`{dim_select}, COUNT(*) AS `count`, "
               f"{value_field} AS `value`, "
               f"ROUND(SUM(f.total_charges), 2) AS total_charges, "
               f"ROUND(SUM(f.total_costs), 2) AS total_costs, "
               f"ROUND(SUM(f.total_charges) - SUM(f.total_costs), 2) AS profit_difference, "
               f"ROUND({_MARGIN}, 2) AS profit_margin_pct, "
               f"ROUND(AVG(f.total_charges), 2) AS avg_charges, "
               f"ROUND(AVG(f.total_costs), 2) AS avg_costs "
               f"FROM fact_inpatient_discharge f {join_sql} {where_sql} "
               f"GROUP BY f.discharge_year{dim_group} "
               f"ORDER BY f.discharge_year ASC{dim_order}")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
                     f"{join_sql} {where_sql}")

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params)
        extra.update({"start_year": args.get("start_year"),
                      "end_year": args.get("end_year")})
        return envelope(data, dimension or "overall", metric, total, ms,
                        filters={}, cached=cached, **extra)
