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

反规范化优化：discharge_year/gender/age_group/apr_severity_desc/facility_name 已回填到
fact_discharge（见 database/backfill_denorm.sql），本模块直接引用事实表列，消除对
dim_time/dim_patient/dim_drg/dim_hospital 的全部 JOIN。
"""
import os

import pymysql
from flask import request

from common import envelope, error, execute_cached, set_database


# ------------------------------------------------------------
# 数据库连接（medical_db；凭据优先取环境变量，默认值兼容本地开发）
# 生产环境请用环境变量注入，勿把密码提交到公共仓库。
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


# ------------------------------------------------------------
# avg-los 分组维度白名单：维度名 -> (列引用, 覆盖索引名)
# 只允许白名单内的列参与 SELECT/GROUP BY，值不来自用户输入，杜绝注入。
# 索引名用于 FORCE INDEX：AVG(length_of_stay) 只有走含 length_of_stay 的覆盖索引
# 才不会退化成千万次主键回表（gender 无对应覆盖索引，留空交给优化器）。
# ------------------------------------------------------------
GROUP_BY_MAP = {
    "discharge_year": ("f.discharge_year", "idx_y_age_los"),
    "gender":         ("f.gender", ""),
    "age_group":      ("f.age_group", "idx_y_age_los"),
    "hospital_id":    ("f.hospital_id", "idx_y_hosp_full"),
}

# 让优化器能走 idx_year_* 覆盖索引族的「全集」谓词（discharge_year 无 NULL）。
YEAR_SCAN = "f.discharge_year IS NOT NULL"

# 本模块的路由；用于把线程局部库名切到 medical_db。
# 必须是精确白名单：/api/v1/analysis/ 前缀下还有 legacy 的 aggregate/payment-mix/trend，
# 那些接口必须继续走 smart_health，不能被一起切库。
EMERGENCY_PATHS = {
    "/api/v1/analysis/emergency-rate",
    "/api/v1/analysis/emergency-compare",
    "/api/v1/analysis/avg-los",
    "/api/v1/analysis/outliers",
    "/api/v1/analysis/disposition/emergency-cross",
}


def _force(index_name):
    return f"FORCE INDEX ({index_name})" if index_name else ""


def register_emergency_routes(app):

    @app.before_request
    def _emergency_use_medical_db():
        if request.path in EMERGENCY_PATHS:
            set_database("medical_db")

    @app.teardown_request
    def _emergency_reset_db(exc=None):
        set_database(None)

    # ① 急诊率（按年份统计急诊占比）
    @app.route("/api/v1/analysis/emergency-rate")
    def emergency_rate():
        sql = f"""
            SELECT f.discharge_year AS `year`,
                   SUM(CASE WHEN f.emergency_department_indicator = 'Y'
                            THEN 1 ELSE 0 END) AS emergency_cnt,
                   COUNT(*) AS total_cnt,
                   ROUND(SUM(CASE WHEN f.emergency_department_indicator = 'Y'
                                  THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS emergency_rate
            FROM fact_discharge f FORCE INDEX (idx_y_emerg)
            WHERE {YEAR_SCAN}
            GROUP BY f.discharge_year
            ORDER BY f.discharge_year
        """
        rows, _, ms, cached, _ = execute_cached(
            request.path, request.args.to_dict(), sql)
        return envelope(rows, "discharge_year", "emergency_rate",
                        len(rows), ms, cached=cached)

    # ② 急诊对比（急诊 vs 非急诊 的费用/住院日对比）
    @app.route("/api/v1/analysis/emergency-compare")
    def emergency_compare():
        sql = """
            SELECT f.emergency_department_indicator AS is_emergency,
                   COUNT(*) AS case_count,
                   ROUND(AVG(f.length_of_stay), 2) AS avg_los,
                   ROUND(AVG(f.total_charges), 2) AS avg_charges
            FROM fact_discharge f FORCE INDEX (idx_emerg_los_chg)
            GROUP BY f.emergency_department_indicator
        """
        rows, _, ms, cached, _ = execute_cached(
            request.path, request.args.to_dict(), sql)
        return envelope(rows, "is_emergency", "compare",
                        len(rows), ms, cached=cached)

    # ③ 平均住院日（按维度分组）
    @app.route("/api/v1/analysis/avg-los")
    def avg_los():
        group_by = request.args.get("group_by", "discharge_year")
        if group_by not in GROUP_BY_MAP:
            return error(400, f"不支持的group_by: {group_by}，可选 {sorted(GROUP_BY_MAP)}")
        col, index_name = GROUP_BY_MAP[group_by]

        sql = f"""
            SELECT {col} AS `key`,
                   ROUND(AVG(f.length_of_stay), 2) AS avg_los,
                   COUNT(*) AS case_count
            FROM fact_discharge f {_force(index_name)}
            WHERE {YEAR_SCAN}
            GROUP BY {col}
            ORDER BY avg_los DESC
        """
        rows, _, ms, cached, _ = execute_cached(
            request.path, request.args.to_dict(), sql)
        return envelope(rows, group_by, "avg_los", len(rows), ms, cached=cached)

    # ④ 超标识别（住院日 > 阈值 或 费用 > 阈值）
    @app.route("/api/v1/analysis/outliers")
    def outliers():
        los_raw = request.args.get("los_threshold", "30")
        charge_raw = request.args.get("charge_threshold", "500000")
        try:
            los_th = int(los_raw)
            charge_th = float(charge_raw)
        except (TypeError, ValueError):
            return error(400, f"阈值参数必须为数字：los_threshold={los_raw}, charge_threshold={charge_raw}")

        sql = """
            SELECT f.fact_id,
                   f.facility_name,
                   f.age_group, f.gender,
                   f.emergency_department_indicator,
                   f.length_of_stay,
                   f.total_charges, f.total_costs,
                   f.patient_disposition,
                   f.apr_severity_desc AS severity_desc
            FROM fact_discharge f
            WHERE f.length_of_stay > %s OR f.total_charges > %s
            ORDER BY f.length_of_stay DESC
            LIMIT 500
        """
        rows, _, ms, cached, _ = execute_cached(
            request.path, request.args.to_dict(), sql, (los_th, charge_th))
        return envelope(rows, "outlier", "detail", len(rows), ms, cached=cached)

    # ⑤ 转归 × 急诊交叉
    @app.route("/api/v1/analysis/disposition/emergency-cross")
    def disposition_emergency_cross():
        sql = """
            SELECT f.emergency_department_indicator AS is_emergency,
                   f.patient_disposition,
                   COUNT(*) AS cnt
            FROM fact_discharge f FORCE INDEX (idx_emerg_dispo)
            GROUP BY f.emergency_department_indicator, f.patient_disposition
            ORDER BY cnt DESC
        """
        rows, _, ms, cached, _ = execute_cached(
            request.path, request.args.to_dict(), sql)
        return envelope(rows, "disposition_x_emergency", "count",
                        len(rows), ms, cached=cached)
