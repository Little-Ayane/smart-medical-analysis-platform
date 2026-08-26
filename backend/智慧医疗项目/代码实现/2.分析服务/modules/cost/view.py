# -*- coding: utf-8 -*-
"""
纪志鹏 - 费用成本分析模块（5 个接口）
库：medical_db 星型模型（fact_discharge + 维度表）
性能：
  外键类维度(drg/mdc/diagnosis/facility)先按外键预聚合再 JOIN 取名；
  且用 IGNORE INDEX 强制全表扫描——否则 MySQL 会走外键索引导致 SUM(total_charges)
  逐行随机回表(1000万次随机 I/O,~100s)，强制全表扫描后 ~5s。
"""
from flask import request

from common import (BadRequest, envelope, error, execute_cached, parse_choice,
                    parse_top, set_database, timed_query)
from star_common import (JOIN_PATIENT, JOIN_PAYMENT, merge_joins,
                         parse_filters_star, year_scan_cond)

# 维度 -> (分组列, JOIN(f.xxx 版, 供 trend 用), key 表达式, 是否外键类, 需忽略的索引)
DIM = {
    "drg":              ("f.drg_id",       "JOIN dim_apr_drg d ON f.drg_id = d.drg_id", "d.apr_drg_desc", True, "drg_id"),
    "mdc":              ("f.drg_id",       "JOIN dim_apr_drg d ON f.drg_id = d.drg_id", "d.apr_mdc_desc", True, "drg_id"),
    "diagnosis":        ("f.diagnosis_id", "JOIN dim_ccsr_diagnosis d2 ON f.diagnosis_id = d2.diagnosis_id", "d2.description", True, "idx_diagnosis"),
    "facility":         ("f.hospital_id",  "JOIN dim_facility h ON f.hospital_id = h.facility_id", "h.facility_name", True, "idx_hospital"),
    "age_group":        ("f.age_group",    "", "f.age_group", False, ""),
    "payment_typology": ("f.payment_typology_1", "", "f.payment_typology_1", False, ""),
}

_MARGIN = "(SUM(f.total_charges) - SUM(f.total_costs)) / SUM(f.total_costs) * 100"


def _to_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} 必须为整数，收到: {raw}")


def _cost(fn):
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except BadRequest as e:
            return error(400, str(e))
    wrapper.__name__ = fn.__name__
    return wrapper


def _rank_endpoint(args, metric, default_top=20, extras=(), order_opt=False):
    dimension = parse_choice(args, "dimension", DIM, "drg")
    group_col, dim_join, key_expr, is_fk, fk_idx = DIM[dimension]
    top = parse_top(args, default=default_top)
    order = "DESC"
    if order_opt:
        order = "DESC" if args.get("order", "desc").lower() == "desc" else "ASC"

    where, params, norm, fjoins = parse_filters_star(args)
    where.append("f.total_charges IS NOT NULL")
    where.append("f.total_costs IS NOT NULL")
    if metric in ("profit_margin", "efficiency_ranking"):
        where.append("f.total_costs > 0")
    where_sql = "WHERE " + " AND ".join(where)

    value_expr = ("ROUND(SUM(f.total_charges) - SUM(f.total_costs), 2)"
                  if metric == "profit_difference"
                  else f"ROUND({_MARGIN}, 2)")

    inner_extras = "".join(f", {expr} AS {alias}" for expr, alias in extras)
    if is_fk:
        # 聚合优先 + IGNORE INDEX 强制全表扫描(避免逐行回表)
        fk = group_col.split(".")[1]
        t_join = dim_join.replace(f"f.{fk}", "t.id")
        filter_join = " ".join(fjoins)
        ignore = f" IGNORE INDEX ({fk_idx})"
        outer_extras = "".join(f", t.{alias}" for _, alias in extras)
        sql = (f"SELECT {key_expr} AS `key`, t.cnt AS `count`, t.value AS `value`{outer_extras} "
               f"FROM (SELECT {group_col} AS id, COUNT(*) AS cnt, "
               f"{value_expr} AS value{inner_extras} "
               f"FROM fact_discharge f{ignore} {filter_join} {where_sql} "
               f"GROUP BY {group_col} HAVING cnt >= 10) t {t_join} "
               f"ORDER BY t.value {order} LIMIT %s")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_discharge f "
                     f"{filter_join} {where_sql}")
    else:
        join_sql = " ".join(merge_joins([dim_join], fjoins))
        sql = (f"SELECT {key_expr} AS `key`, COUNT(*) AS `count`, "
               f"{value_expr} AS `value`{inner_extras} "
               f"FROM fact_discharge f {join_sql} {where_sql} "
               f"GROUP BY {key_expr} HAVING `count` >= 10 "
               f"ORDER BY `value` {order} LIMIT %s")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_discharge f "
                     f"{join_sql} {where_sql}")

    data, total, ms, cached, extra = execute_cached(
        request.path, args, sql, params + [top], count_sql, params)
    return envelope(data, dimension, metric, total, ms,
                    filters=norm, cached=cached, **extra)


def register_cost_routes(app):

    @app.before_request
    def _cost_use_medical_db():
        if request.path.startswith("/api/v1/cost"):
            set_database("medical_db")

    @app.teardown_request
    def _cost_clear_db(exc):
        set_database(None)

    # ---------- 1. 费用成本差 ----------
    @app.route("/api/v1/cost/profit-difference")
    @_cost
    def cost_profit_difference():
        extras = [
            ("ROUND(SUM(f.total_charges), 2)", "total_charges"),
            ("ROUND(SUM(f.total_costs), 2)", "total_costs"),
            ("ROUND(AVG(f.total_charges), 2)", "avg_charges"),
            ("ROUND(AVG(f.total_costs), 2)", "avg_costs"),
            ("ROUND(AVG(f.total_charges) - AVG(f.total_costs), 2)", "avg_profit_difference"),
        ]
        return _rank_endpoint(request.args, "profit_difference", default_top=20, extras=extras)

    # ---------- 2. 利润率 ----------
    @app.route("/api/v1/cost/profit-margin")
    @_cost
    def cost_profit_margin():
        extras = [
            ("ROUND(SUM(f.total_charges), 2)", "total_charges"),
            ("ROUND(SUM(f.total_costs), 2)", "total_costs"),
            (f"ROUND({_MARGIN}, 2)", "profit_margin_pct"),
            ("ROUND(AVG(f.total_charges), 2)", "avg_charges"),
            ("ROUND(AVG(f.total_costs), 2)", "avg_costs"),
            ("ROUND(AVG(f.total_charges) - AVG(f.total_costs), 2)", "avg_profit_difference"),
        ]
        return _rank_endpoint(request.args, "profit_margin", default_top=20,
                              extras=extras, order_opt=True)

    # ---------- 3. 成本效益排行 ----------
    @app.route("/api/v1/cost/efficiency-ranking")
    @_cost
    def cost_efficiency_ranking():
        extras = [
            ("ROUND(SUM(f.total_charges), 2)", "total_charges"),
            ("ROUND(SUM(f.total_costs), 2)", "total_costs"),
            (f"ROUND({_MARGIN}, 2)", "profit_margin_pct"),
            ("ROUND(AVG(f.total_charges), 2)", "avg_charges"),
            ("ROUND(AVG(f.total_costs), 2)", "avg_costs"),
            (f"CASE WHEN {_MARGIN} > 15 THEN 'A（高效益）'"
             f" WHEN {_MARGIN} > 10 THEN 'B（中高效益）'"
             f" WHEN {_MARGIN} > 5 THEN 'C（中低效益）'"
             " ELSE 'D（低效益）' END", "efficiency_grade"),
            (f"CONCAT('利润率 ', ROUND({_MARGIN}, 2), '%%')", "grade_basis"),
        ]
        return _rank_endpoint(request.args, "efficiency_ranking", default_top=30, extras=extras)

    # ---------- 4. 费用构成 ----------
    @app.route("/api/v1/cost/composition")
    @_cost
    def cost_composition():
        args = request.args
        dimension = parse_choice(args, "dimension", DIM, "mdc")
        group_col, dim_join, key_expr, is_fk, fk_idx = DIM[dimension]
        top = parse_top(args, default=10, cap=50)
        where, params, norm, fjoins = parse_filters_star(args)
        where.append("f.total_charges IS NOT NULL")
        where_sql = "WHERE " + " AND ".join(where)
        filter_join = " ".join(fjoins)

        total_rows, _ = timed_query(
            f"SELECT ROUND(SUM(f.total_charges), 2) AS total_all "
            f"FROM fact_discharge f {filter_join} {where_sql}", params)
        total_all = total_rows[0]["total_all"] if total_rows and total_rows[0]["total_all"] else 1

        if is_fk:
            fk = group_col.split(".")[1]
            t_join = dim_join.replace(f"f.{fk}", "t.id")
            ignore = f" IGNORE INDEX ({fk_idx})"
            sql = (f"SELECT {key_expr} AS `key`, t.cnt AS `count`, "
                   f"ROUND(t.charges / %s * 100, 2) AS `value`, "
                   f"ROUND(t.charges, 2) AS total_charges, "
                   f"ROUND(t.charges / t.cnt, 2) AS avg_charges, "
                   f"ROUND(t.charges / %s * 100, 2) AS pct "
                   f"FROM (SELECT {group_col} AS id, COUNT(*) AS cnt, "
                   f"SUM(f.total_charges) AS charges "
                   f"FROM fact_discharge f{ignore} {filter_join} {where_sql} "
                   f"GROUP BY {group_col}) t {t_join} "
                   f"ORDER BY t.charges DESC LIMIT %s")
            count_sql = (f"SELECT COUNT(*) AS c FROM fact_discharge f "
                         f"{filter_join} {where_sql}")
        else:
            join_sql = " ".join(merge_joins([dim_join], fjoins))
            sql = (f"SELECT {key_expr} AS `key`, COUNT(*) AS `count`, "
                   f"ROUND(SUM(f.total_charges) / %s * 100, 2) AS `value`, "
                   f"ROUND(SUM(f.total_charges), 2) AS total_charges, "
                   f"ROUND(AVG(f.total_charges), 2) AS avg_charges, "
                   f"ROUND(SUM(f.total_charges) / %s * 100, 2) AS pct "
                   f"FROM fact_discharge f {join_sql} {where_sql} "
                   f"GROUP BY {key_expr} ORDER BY SUM(f.total_charges) DESC LIMIT %s")
            count_sql = (f"SELECT COUNT(*) AS c FROM fact_discharge f "
                         f"{join_sql} {where_sql}")

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, [total_all, total_all] + params + [top],
            count_sql, params, extras={"total_charges_all": total_all})
        return envelope(data, dimension, "composition_pct", total, ms,
                        filters=norm, cached=cached, **extra)

    # ---------- 5. 年度趋势 ----------
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
        # 全集年份谓词：让 GROUP BY discharge_year 走 idx_discharge_year / idx_year_* 覆盖索引
        if not args.get("start_year") and not args.get("end_year"):
            where.append(year_scan_cond("f"))
        where.append("f.total_charges IS NOT NULL")
        where.append("f.total_costs IS NOT NULL")
        where.append("f.total_costs > 0")

        dim_select, dim_group, dim_order, dim_join = "", "", "", ""
        if dimension:
            _, dim_join, key_expr, _, _ = DIM[dimension]
            dim_select = f", {key_expr} AS dimension_key"
            dim_group = f", {key_expr}"
            dim_order = f", {key_expr} ASC"
            if args.get("dimension_value"):
                where.append(f"{key_expr} = %s")
                params.append(args["dimension_value"])

        # discharge_year 已反规范化到事实表，直接 GROUP BY f.discharge_year，
        # 去掉 JOIN dim_time（原 35.3s 的主因之一）
        join_sql = " ".join(dim_join.split()) if dim_join else ""
        where_sql = "WHERE " + " AND ".join(where)

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
               f"FROM fact_discharge f {join_sql} {where_sql} "
               f"GROUP BY f.discharge_year{dim_group} "
               f"ORDER BY f.discharge_year ASC{dim_order}")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_discharge f "
                     f"{join_sql} {where_sql}")

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params)
        extra.update({"start_year": args.get("start_year"),
                      "end_year": args.get("end_year")})
        return envelope(data, dimension or "overall", metric, total, ms,
                        filters={}, cached=cached, **extra)
