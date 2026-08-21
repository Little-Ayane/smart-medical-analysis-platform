# -*- coding: utf-8 -*-
"""
P3 · 维度字典接口
功能：一次性返回各分析维度的枚举值，供前端筛选器联动与 code<->描述映射。
端点：GET /api/v1/meta/dimensions
缓存：数据静态，TTL 24 小时。
"""
from flask import Blueprint, request

from common import (AGE_ORDER_SQL, SEVERITY_CODE_TO_DESC, envelope, execute_cached,
                    timed_query)

meta_bp = Blueprint("meta", __name__, url_prefix="/api/v1/meta")


@meta_bp.route("/dimensions")
def dimensions():
    def build(_rows):
        diag, _ = timed_query(
            "SELECT ccsr_code AS code, description AS name "
            "FROM dim_ccsr_diagnosis ORDER BY ccsr_code")
        proc, _ = timed_query(
            "SELECT ccsr_code AS code, description AS name "
            "FROM dim_ccsr_procedure ORDER BY ccsr_code")
        pay, _ = timed_query(
            "SELECT payment_typology_1 AS name FROM fact_inpatient_discharge "
            "WHERE payment_typology_1 IS NOT NULL "
            "GROUP BY payment_typology_1 ORDER BY COUNT(*) DESC")
        age, _ = timed_query(
            f"SELECT age_group AS name FROM fact_inpatient_discharge "
            f"WHERE age_group IS NOT NULL GROUP BY age_group ORDER BY {AGE_ORDER_SQL}")
        area, _ = timed_query(
            "SELECT service_area AS name FROM dim_facility "
            "WHERE service_area IS NOT NULL GROUP BY service_area ORDER BY name")
        county, _ = timed_query(
            "SELECT hospital_county AS name FROM dim_facility "
            "WHERE hospital_county IS NOT NULL "
            "GROUP BY hospital_county ORDER BY name")
        return {
            "diagnosis": list(diag),
            "procedure": list(proc),
            "payment": [r["name"] for r in pay],
            "severity": [{"code": c, "name": n}
                         for c, n in SEVERITY_CODE_TO_DESC.items() if c is not None],
            "age_group": [r["name"] for r in age],
            "service_area": [r["name"] for r in area],
            "county": [r["name"] for r in county],
        }

    # build 里已自行查全部小表，execute_cached 只负责缓存编排
    data, total, ms, cached, extra = execute_cached(
        request.path, request.args, "SELECT 1", post=build, ttl=86400)
    return envelope(data, "meta", "dimensions", None, ms, cached=cached, **extra)
