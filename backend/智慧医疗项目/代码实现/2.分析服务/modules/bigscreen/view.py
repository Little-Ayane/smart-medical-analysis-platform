# -*- coding: utf-8 -*-
"""
大屏预聚合数据：GET /api/v1/bigscreen/overview

给前端「3D 大屏」（views/bigscreen/）一次性提供 8 块数据：
    summary / service_areas / top_hospitals / top_diseases /
    age_distribution / payment_types / severity_dist / top_drg

数据源：medical_db.fact_discharge（1038 万行、2020–2024，约 16.5GB）。
性能：全表 AVG/SUM 若不带覆盖索引会退化为 10M+ 次主键回表（单条 6~10 分钟），
      故全部查询显式 FORCE INDEX 走覆盖索引（含本模块新增的 idx_bs_area /
      idx_bs_hosp），冷启动全量构建 ~10s。
      结果落盘到预聚合表 `bigscreen_overview`（JSON 单行），接口只读小表 <10ms、
      且跨服务重启仍有效（不依赖 Redis/内存缓存）。
"""
import json
import os
import time

import pymysql
from flask import request

from common import envelope, error, cache_get, cache_set

CACHE_KEY = "bigscreen:overview"
AGG_TABLE = "bigscreen_overview"


# ------------------------------------------------------------
# 数据库连接（medical_db；凭据优先取环境变量，默认值兼容本地开发）
# 与 emergency/view.py 保持一致。
# ------------------------------------------------------------
def _db_config():
    return {
        "host": os.getenv("MEDICAL_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("MEDICAL_DB_PORT", "3306")),
        "user": os.getenv("MEDICAL_DB_USER", "root"),
        "password": os.getenv("MEDICAL_DB_PASSWORD", ""),
        "database": os.getenv("MEDICAL_DB_DATABASE", "medical_db"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


def get_conn():
    return pymysql.connect(**_db_config())


def _query(sql, params=None):
    """独立连接跑一条查询，返回行列表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def _exec(sql, params=None):
    """执行写语句（CREATE/INSERT/UPDATE）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------
# 聚合 SQL —— 全部 FORCE INDEX 覆盖索引，避免主键回表
# ------------------------------------------------------------
_SQL_YEAR_DIST = """
    SELECT discharge_year, COUNT(*) AS c
    FROM fact_discharge FORCE INDEX (idx_discharge_year)
    GROUP BY discharge_year
"""

_SQL_EMERGENCY_CNT = """
    SELECT COUNT(*) AS c
    FROM fact_discharge FORCE INDEX (idx_emerg_dispo)
    WHERE emergency_department_indicator = 'Y'
"""

_SQL_DIM_COUNTS = """
    SELECT (SELECT COUNT(*) FROM dim_hospital)  AS hospitals,
           (SELECT COUNT(*) FROM dim_diagnosis) AS diagnoses
"""

_SQL_SERVICE_AREAS = """
    SELECT hospital_service_area AS area,
           COUNT(*) AS cases,
           ROUND(AVG(total_charges), 2)     AS avg_charges,
           ROUND(AVG(length_of_stay), 2)    AS avg_los,
           ROUND(COALESCE(SUM(emergency_department_indicator = 'Y'), 0) * 100.0 / COUNT(*), 2) AS emergency_rate
    FROM fact_discharge FORCE INDEX (idx_bs_area)
    GROUP BY hospital_service_area
    ORDER BY cases DESC
"""

_SQL_TOP_HOSPITALS = """
    SELECT facility_name AS hospital_name,
           COUNT(*) AS cases,
           ROUND(AVG(total_charges), 2)  AS avg_charges,
           ROUND(AVG(length_of_stay), 2) AS avg_los
    FROM fact_discharge FORCE INDEX (idx_bs_hosp)
    WHERE facility_name IS NOT NULL
    GROUP BY facility_name
    ORDER BY cases DESC
    LIMIT 10
"""

_SQL_TOP_DISEASES = """
    SELECT t.id, t.cases, d.ccsr_diagnosis_description AS diagnosis
    FROM (
        SELECT diagnosis_id AS id, COUNT(*) AS cases
        FROM fact_discharge FORCE INDEX (idx_diagnosis)
        WHERE diagnosis_id IS NOT NULL
        GROUP BY diagnosis_id
        ORDER BY cases DESC
        LIMIT 10
    ) t
    JOIN dim_diagnosis d ON t.id = d.diagnosis_id
    ORDER BY t.cases DESC
"""

_SQL_AGE_DISTRIBUTION = """
    SELECT age_group, COUNT(*) AS cases
    FROM fact_discharge FORCE INDEX (idx_age_group)
    GROUP BY age_group
    ORDER BY cases DESC
"""

_SQL_PAYMENT_TYPES = """
    SELECT payment_typology_1 AS payment_type, COUNT(*) AS cases
    FROM fact_discharge FORCE INDEX (idx_payment1)
    GROUP BY payment_typology_1
    ORDER BY cases DESC
"""

_SQL_SEVERITY_DIST = """
    SELECT apr_severity_desc AS severity, COUNT(*) AS cases
    FROM fact_discharge FORCE INDEX (idx_severity_desc)
    GROUP BY apr_severity_desc
    ORDER BY cases DESC
"""

_SQL_TOP_DRG = """
    SELECT t.id, t.cases, t.avg_charges, d.apr_drg_description AS drg_name
    FROM (
        SELECT drg_id AS id, COUNT(*) AS cases, ROUND(AVG(total_charges), 2) AS avg_charges
        FROM fact_discharge FORCE INDEX (idx_year_drg_cost)
        WHERE drg_id IS NOT NULL
        GROUP BY drg_id
        ORDER BY cases DESC
        LIMIT 10
    ) t
    JOIN dim_drg d ON t.id = d.drg_id
    ORDER BY t.cases DESC
"""


def _build_payload():
    """跑 8 块聚合，组装成前端期望的 data 字典。"""
    # summary：由年份分布 + 急诊计数 + 维度表行数合成（全部覆盖索引/小表，秒级）
    year_rows = _query(_SQL_YEAR_DIST)
    total = sum(int(r["c"]) for r in year_rows)
    total_years = len(year_rows)
    emg_cnt = int(_query(_SQL_EMERGENCY_CNT)[0]["c"] or 0)
    dim_row = _query(_SQL_DIM_COUNTS)[0]

    summary = {
        "total_records": total,
        "total_hospitals": int(dim_row["hospitals"] or 0),
        "total_diagnoses": int(dim_row["diagnoses"] or 0),
        "total_years": total_years,
        "emergency_rate": round(emg_cnt * 100.0 / total, 2) if total else 0.0,
    }

    service_rows = _query(_SQL_SERVICE_AREAS)
    hosp_rows = _query(_SQL_TOP_HOSPITALS)
    disease_rows = _query(_SQL_TOP_DISEASES)
    age_rows = _query(_SQL_AGE_DISTRIBUTION)
    pay_rows = _query(_SQL_PAYMENT_TYPES)
    sev_rows = _query(_SQL_SEVERITY_DIST)
    drg_rows = _query(_SQL_TOP_DRG)

    service_areas = [
        {"area": r["area"] or "Unknown", "cases": int(r["cases"]),
         "avg_charges": float(r["avg_charges"] or 0), "avg_los": float(r["avg_los"] or 0),
         "emergency_rate": float(r["emergency_rate"] or 0)}
        for r in service_rows
    ]

    top_hospitals = [
        {"hospital_name": r["hospital_name"], "cases": int(r["cases"]),
         "avg_charges": float(r["avg_charges"] or 0), "avg_los": float(r["avg_los"] or 0)}
        for r in hosp_rows
    ]

    top_diseases = [
        {"diagnosis": r["diagnosis"], "cases": int(r["cases"])}
        for r in disease_rows
    ]

    age_distribution = [
        {"age_group": r["age_group"] or "Unknown", "cases": int(r["cases"])}
        for r in age_rows
    ]

    # percentage 在 Python 里算（避免 SQL 窗口函数），口径一致
    pay_total = sum(int(r["cases"]) for r in pay_rows) or 1
    payment_types = [
        {"payment_type": r["payment_type"] or "Unknown", "cases": int(r["cases"]),
         "percentage": round(int(r["cases"]) * 100.0 / pay_total, 2)}
        for r in pay_rows
    ]

    severity_dist = [
        {"severity": r["severity"] or "Unknown", "cases": int(r["cases"])}
        for r in sev_rows
    ]

    top_drg = [
        {"drg_name": r["drg_name"], "cases": int(r["cases"]),
         "avg_charges": float(r["avg_charges"] or 0)}
        for r in drg_rows
    ]

    return {
        "summary": summary,
        "service_areas": service_areas,
        "top_hospitals": top_hospitals,
        "top_diseases": top_diseases,
        "age_distribution": age_distribution,
        "payment_types": payment_types,
        "severity_dist": severity_dist,
        "top_drg": top_drg,
    }


# ------------------------------------------------------------
# 预聚合表读写（JSON 单行持久化）
# ------------------------------------------------------------
def _ensure_table():
    _exec(f"""
        CREATE TABLE IF NOT EXISTS {AGG_TABLE} (
            id TINYINT PRIMARY KEY,
            payload JSON NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)


def _load_payload():
    """读预聚合表，返回 dict 或 None。"""
    rows = _query(f"SELECT payload FROM {AGG_TABLE} WHERE id = 1")
    if not rows:
        return None
    raw = rows[0]["payload"]
    if isinstance(raw, str):
        return json.loads(raw)
    return json.loads(json.dumps(raw, ensure_ascii=False)) if raw is not None else None


def _store_payload(payload):
    _ensure_table()
    _exec(
        f"INSERT INTO {AGG_TABLE} (id, payload) VALUES (1, %s) "
        f"ON DUPLICATE KEY UPDATE payload = VALUES(payload)",
        (json.dumps(payload, ensure_ascii=False),),
    )


def register_bigscreen_routes(app):

    @app.route("/api/v1/bigscreen/overview")
    def bigscreen_overview():
        # 1) 进程/Redis 缓存（热）→ 秒回
        hit, payload = cache_get(CACHE_KEY)
        if not hit:
            # 2) 预聚合表（冷，但持久）→ 秒回
            try:
                payload = _load_payload()
            except Exception:
                app.logger.exception("[bigscreen/overview] 读取预聚合表失败")
                payload = None
            if payload is None:
                # 3) 表里没有 → 全量构建（覆盖索引，~10s）+ 持久化
                start = time.time()
                try:
                    payload = _build_payload()
                except Exception:
                    app.logger.exception("[bigscreen/overview] 全量构建失败")
                    return error(500, "服务内部错误")
                try:
                    _store_payload(payload)
                except Exception:
                    app.logger.exception("[bigscreen/overview] 写入预聚合表失败")
                cache_set(CACHE_KEY, payload)
                ms = int((time.time() - start) * 1000)
                return envelope(payload, "bigscreen", "overview", query_ms=ms, cached=False)
            cache_set(CACHE_KEY, payload)
            ms = 0
        else:
            ms = 0
        return envelope(payload, "bigscreen", "overview", query_ms=ms, cached=True)
