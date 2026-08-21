# -*- coding: utf-8 -*-
"""
遗留接口蓝图（P4 AI 模块向后兼容分支仍依赖，勿删）：
    GET /api/v1/health                   健康检查
    GET /api/v1/analysis/aggregate       通用聚合分析
    GET /api/v1/analysis/payment-mix     支付方式占比
    GET /api/v1/analysis/trend           疾病趋势（时间序列）
契约见 接口文档/RESTful_API接口文档.md；新开发请使用 modules/ 下各业务模块。
"""
import time

from flask import Blueprint, request

from common import envelope, error, get_conn

legacy_bp = Blueprint("legacy", __name__, url_prefix="/api/v1")


# ------------------------------------------------------------
# 维度/指标白名单（防 SQL 注入，禁止直接拼接用户输入）
# ------------------------------------------------------------
DIMENSIONS = {
    "age_group":       ("age_group", "varchar"),
    "gender":          ("gender", "varchar"),
    "discharge_year":  ("discharge_year", "int"),
    "ccsr_diagnosis":  ("d.description", "varchar"),
    "facility":        ("f.facility_name", "varchar"),
    "payment_typology":("payment_typology_1", "varchar"),
    "severity":        ("apr_severity_desc", "varchar"),
    "aprg_drg":        ("d2.apr_drg_desc", "varchar"),
}

METRICS = {
    "count":             "COUNT(*)",
    "avg_length_of_stay": "ROUND(AVG(length_of_stay), 2)",
    "total_charges":     "ROUND(SUM(total_charges), 2)",
    "avg_charges":       "ROUND(AVG(total_charges), 2)",
    "total_costs":       "ROUND(SUM(total_costs), 2)",
    "avg_costs":         "ROUND(AVG(total_costs), 2)",
}

BASE_FROM = """FROM fact_inpatient_discharge f
LEFT JOIN dim_ccsr_diagnosis d ON f.diagnosis_id = d.diagnosis_id
LEFT JOIN dim_apr_drg d2 ON f.drg_id = d2.drg_id"""


def _count_total(where_sql, params):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c {BASE_FROM} {where_sql}", params)
            return cur.fetchone()["c"]
    finally:
        conn.close()


# ------------------------------------------------------------
# 通用聚合分析（核心接口，P4 旧分支 /analysis/aggregate）
# ------------------------------------------------------------
@legacy_bp.route("/analysis/aggregate")
def aggregate():
    start = time.time()
    dimension = request.args.get("dimension", "discharge_year")
    metric = request.args.get("metric", "count")

    if dimension not in DIMENSIONS:
        return error(400, f"不支持的维度: {dimension}，可选 {list(DIMENSIONS)}")
    if metric not in METRICS:
        return error(400, f"不支持的指标: {metric}，可选 {list(METRICS)}")

    dim_col, _ = DIMENSIONS[dimension]
    metric_expr = METRICS[metric]
    top = min(int(request.args.get("top", 20)), 100)

    # 可选过滤条件
    where, params = [], []
    if request.args.get("year"):
        where.append("f.discharge_year = %s")
        params.append(int(request.args["year"]))
    if request.args.get("gender"):
        where.append("f.gender = %s")
        params.append(request.args["gender"].upper())
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = (f"SELECT {dim_col} AS `key`, {metric_expr} AS `value`, "
           f"COUNT(*) AS `count` {BASE_FROM} {where_sql} "
           f"GROUP BY {dim_col} ORDER BY `value` DESC LIMIT {top}")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    # total_records 单独统计
    total = _count_total(where_sql, params)
    return envelope(rows, dimension, metric, total, int((time.time()-start)*1000))


# ------------------------------------------------------------
# 支付方式占比
# ------------------------------------------------------------
@legacy_bp.route("/analysis/payment-mix")
def payment_mix():
    start = time.time()
    sql = (f"SELECT payment_typology_1 AS payment, COUNT(*) AS count "
           f"{BASE_FROM} GROUP BY payment_typology_1 ORDER BY count DESC")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    total = sum(r["count"] for r in rows)
    for r in rows:
        r["pct"] = round(r["count"] * 100.0 / total, 2) if total else 0
    return envelope(rows, "payment_typology", "count", total,
                    int((time.time()-start)*1000))


# ------------------------------------------------------------
# 疾病趋势（时间序列）
# ------------------------------------------------------------
@legacy_bp.route("/analysis/trend")
def trend():
    start = time.time()
    diagnosis = request.args.get("diagnosis")
    where, params = "", []
    if diagnosis:
        where = "WHERE d.ccsr_code = %s"
        params.append(diagnosis)
    sql = (f"SELECT discharge_year AS `year`, COUNT(*) AS count "
           f"{BASE_FROM} {where} GROUP BY discharge_year ORDER BY discharge_year")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    return envelope(rows, "discharge_year", "count",
                    None, int((time.time()-start)*1000))


# ------------------------------------------------------------
# 健康检查
# ------------------------------------------------------------
@legacy_bp.route("/health")
def health():
    try:
        conn = get_conn()
        conn.close()
        db_status = "connected"
    except Exception:
        db_status = "error"
    return envelope({"status": "ok", "db": db_status}, query_ms=1)
