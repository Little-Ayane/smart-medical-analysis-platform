# -*- coding: utf-8 -*-
"""
骆志远 - 急诊与住院分析模块（5 个接口）
功能：急诊率、急诊对比、平均住院日、超标识别、转归×急诊交叉
规范：复用 common 统一信封（envelope/error），与 cost 模块一致；
      但数据源为 medical_db（独立于主服务 common.py 的 smart_health）
库：medical_db（fact_discharge + dim_time/dim_patient/dim_hospital/dim_drg）
契约见《骆志远-急诊与住院分析模块接口文档.md》 v1.0

星型模型外键（与 fastapi_common/sql_builder.py 一致）：
    fact_discharge ── f.year_id          → dim_time.year_id        (discharge_year)
                   ── f.patient_demo_id  → dim_patient.patient_demo_id (gender/age_group)
                   ── f.hospital_id      → dim_hospital.hospital_id   (facility_name)
                   ── f.drg_id           → dim_drg.drg_id             (apr_severity_description)
"""
import os
import time

import pymysql
from flask import request

from common import envelope, error


# ------------------------------------------------------------
# 数据库连接（medical_db；凭据优先取环境变量，默认值兼容本地开发）
# 生产环境请用环境变量注入，勿把密码提交到公共仓库。
# ------------------------------------------------------------
def _db_config():
    return {
        "host": os.getenv("MEDICAL_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("MEDICAL_DB_PORT", "3306")),
        "user": os.getenv("MEDICAL_DB_USER", "root"),
        "password": os.getenv("MEDICAL_DB_PASSWORD", "Csu@Boy727620zy"),
        "database": os.getenv("MEDICAL_DB_DATABASE", "medical_db"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


def get_conn():
    return pymysql.connect(**_db_config())


# ------------------------------------------------------------
# avg-los 分组维度白名单：维度名 -> (列引用, JOIN 子句)
# 只允许白名单内的列参与 SELECT/GROUP BY，值不来自用户输入，杜绝注入。
# ------------------------------------------------------------
GROUP_BY_MAP = {
    "discharge_year": ("dt.discharge_year",
                       "JOIN dim_time dt ON f.year_id = dt.year_id"),
    "gender":         ("p.gender",
                       "JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id"),
    "age_group":      ("p.age_group",
                       "JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id"),
    "hospital_id":    ("f.hospital_id", ""),
}


def register_emergency_routes(app):

    # ① 急诊率（按年份统计急诊占比）
    @app.route("/api/v1/analysis/emergency-rate")
    def emergency_rate():
        start = time.time()
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT dt.discharge_year AS `year`,
                           SUM(CASE WHEN f.emergency_department_indicator = 'Y'
                                    THEN 1 ELSE 0 END) AS emergency_cnt,
                           COUNT(*) AS total_cnt,
                           ROUND(SUM(CASE WHEN f.emergency_department_indicator = 'Y'
                                          THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS emergency_rate
                    FROM fact_discharge f
                    JOIN dim_time dt ON f.year_id = dt.year_id
                    GROUP BY dt.discharge_year
                    ORDER BY dt.discharge_year
                """)
                rows = cur.fetchall()
        finally:
            conn.close()
        return envelope(rows, "discharge_year", "emergency_rate",
                        len(rows), int((time.time() - start) * 1000))

    # ② 急诊对比（急诊 vs 非急诊 的费用/住院日对比）
    @app.route("/api/v1/analysis/emergency-compare")
    def emergency_compare():
        start = time.time()
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f.emergency_department_indicator AS is_emergency,
                           COUNT(*) AS case_count,
                           ROUND(AVG(f.length_of_stay), 2) AS avg_los,
                           ROUND(AVG(f.total_charges), 2) AS avg_charges
                    FROM fact_discharge f
                    GROUP BY f.emergency_department_indicator
                """)
                rows = cur.fetchall()
        finally:
            conn.close()
        return envelope(rows, "is_emergency", "compare",
                        len(rows), int((time.time() - start) * 1000))

    # ③ 平均住院日（按维度分组）
    @app.route("/api/v1/analysis/avg-los")
    def avg_los():
        start = time.time()
        group_by = request.args.get("group_by", "discharge_year")
        if group_by not in GROUP_BY_MAP:
            return error(400, f"不支持的group_by: {group_by}，可选 {sorted(GROUP_BY_MAP)}")
        col, join_sql = GROUP_BY_MAP[group_by]

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {col} AS `key`,
                           ROUND(AVG(f.length_of_stay), 2) AS avg_los,
                           COUNT(*) AS case_count
                    FROM fact_discharge f
                    {join_sql}
                    GROUP BY {col}
                    ORDER BY avg_los DESC
                """)
                rows = cur.fetchall()
        finally:
            conn.close()
        return envelope(rows, group_by, "avg_los",
                        len(rows), int((time.time() - start) * 1000))

    # ④ 超标识别（住院日 > 阈值 或 费用 > 阈值）
    @app.route("/api/v1/analysis/outliers")
    def outliers():
        start = time.time()
        los_raw = request.args.get("los_threshold", "30")
        charge_raw = request.args.get("charge_threshold", "500000")
        try:
            los_th = int(los_raw)
            charge_th = float(charge_raw)
        except (TypeError, ValueError):
            return error(400, f"阈值参数必须为数字：los_threshold={los_raw}, charge_threshold={charge_raw}")

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f.fact_id,
                           h.facility_name,
                           p.age_group, p.gender,
                           f.emergency_department_indicator,
                           f.length_of_stay,
                           f.total_charges, f.total_costs,
                           f.patient_disposition,
                           d2.apr_severity_description AS severity_desc
                    FROM fact_discharge f
                    LEFT JOIN dim_hospital h ON f.hospital_id = h.hospital_id
                    LEFT JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id
                    LEFT JOIN dim_drg d2 ON f.drg_id = d2.drg_id
                    WHERE f.length_of_stay > %s OR f.total_charges > %s
                    ORDER BY f.length_of_stay DESC
                    LIMIT 500
                """, (los_th, charge_th))
                rows = cur.fetchall()
        finally:
            conn.close()
        return envelope(rows, "outlier", "detail",
                        len(rows), int((time.time() - start) * 1000))

    # ⑤ 转归 × 急诊交叉
    @app.route("/api/v1/analysis/disposition/emergency-cross")
    def disposition_emergency_cross():
        start = time.time()
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f.emergency_department_indicator AS is_emergency,
                           f.patient_disposition,
                           COUNT(*) AS cnt
                    FROM fact_discharge f
                    GROUP BY f.emergency_department_indicator, f.patient_disposition
                    ORDER BY cnt DESC
                """)
                rows = cur.fetchall()
        finally:
            conn.close()
        return envelope(rows, "disposition_x_emergency", "count",
                        len(rows), int((time.time() - start) * 1000))
