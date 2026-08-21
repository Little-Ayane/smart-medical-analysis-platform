# -*- coding: utf-8 -*-
"""
P3 · 大数据分析服务模块
功能：多维度聚合分析 + RESTful API 封装，统一 JSON 信封返回
业务模块：病种与手术分析（disease.py）、支付分析（payment.py）、维度字典（meta.py）
技术：Flask / PyMySQL / 进程内 TTL 缓存
运行：python app.py  ->  http://127.0.0.1:5000
注意：进程内缓存依赖单进程模型，请勿用 debug=True（reloader 双进程会让缓存各自为政）。
"""

import json
import time
from functools import wraps

import pymysql
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from common import apply_json_provider, get_conn as _common_get_conn
from meta import meta_bp
from modules.disease import disease_bp
from modules.payment import payment_bp

from flask_cors import CORS
app = Flask(__name__)
CORS(app)  # ← 加这一行，允许所有来源跨域
app = Flask(__name__)
apply_json_provider(app)
app.register_blueprint(disease_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(meta_bp)


# ------------------------------------------------------------
# CORS（前端跨域直连，无需 flask-cors）
# ------------------------------------------------------------
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ------------------------------------------------------------
# 全局异常兜底（统一信封，不抛裸异常）
# ------------------------------------------------------------
@app.errorhandler(HTTPException)
def on_http_exception(e):
    return error(e.code if e.code < 500 else 500, e.name)


@app.errorhandler(Exception)
def on_unhandled(e):
    app.logger.exception("未处理异常: %s", request.path)
    return error(500, "服务内部错误")

# ------------------------------------------------------------
# 数据库连接
# ------------------------------------------------------------
def get_conn():
    # 复用 common.get_conn（统一读取 common.DB，避免密码散落多处导致 health/aggregate 等老接口连库失败）
    return _common_get_conn()


# ------------------------------------------------------------
# 统一响应信封
# ------------------------------------------------------------
def envelope(data, dimension=None, metric=None, total_records=None, query_ms=0):
    return {
        "code": 0,
        "message": "success",
        "data": data,
        "meta": {
            "dimension": dimension,
            "metric": metric,
            "total_records": total_records,
            "query_ms": query_ms,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }


def error(code, message):
    return jsonify({"code": code, "message": message, "data": None, "meta": {}}), 200


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


# ------------------------------------------------------------
# 通用聚合分析（核心接口）
# ------------------------------------------------------------
@app.route("/api/v1/analysis/aggregate")
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
    return jsonify(envelope(rows, dimension, metric, total, int((time.time()-start)*1000)))


def _count_total(where_sql, params):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c {BASE_FROM} {where_sql}", params)
            return cur.fetchone()["c"]
    finally:
        conn.close()


# ------------------------------------------------------------
# 支付方式占比
# ------------------------------------------------------------
@app.route("/api/v1/analysis/payment-mix")
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
    return jsonify(envelope(rows, "payment_typology", "count", total,
                            int((time.time()-start)*1000)))


# ------------------------------------------------------------
# 疾病趋势（时间序列）
# ------------------------------------------------------------
@app.route("/api/v1/analysis/trend")
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
    return jsonify(envelope(rows, "discharge_year", "count",
                            None, int((time.time()-start)*1000)))


# ------------------------------------------------------------
# 健康检查
# ------------------------------------------------------------
@app.route("/api/v1/health")
def health():
    try:
        conn = get_conn()
        conn.close()
        db_status = "connected"
    except Exception:
        db_status = "error"
    return jsonify(envelope({"status": "ok", "db": db_status}, query_ms=1))

# ===== 注册骆志远的路由 =====
from luo_routes import register_luo_routes
register_luo_routes(app)

# ===== 注册纪志鹏的费用成本路由（modules/cost）=====
from modules.cost import register_cost_routes
register_cost_routes(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
