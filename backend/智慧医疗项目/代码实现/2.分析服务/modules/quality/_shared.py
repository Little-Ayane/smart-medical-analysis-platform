# -*- coding: utf-8 -*-
"""模块四 · 医疗质量监测 模块内公用：蓝图、统一异常包装、质量指标 SQL 条件常量。
性能约定：一律"先按事实表列/外键 GROUP BY 预聚合，后 JOIN 小维度表取名"。
数据源：medical_db 星型模型。
"""
from flask import Blueprint, current_app

from common import BadRequest, error, set_database
from star_common import JOIN_DRG, JOIN_PATIENT

quality_bp = Blueprint("quality", __name__, url_prefix="/api/v1/quality")


@quality_bp.before_request
def _use_medical_db():
    """试点：质量模块查询 medical_db（1000万/2020-2024）而非 smart_health。"""
    set_database("medical_db")


@quality_bp.teardown_request
def _clear_db(exc):
    set_database(None)


def _endpoint(path, args, handler):
    try:
        return handler(args)
    except BadRequest as e:
        return error(400, str(e))
    except Exception:
        current_app.logger.exception("[quality/%s] 处理异常", path)
        return error(500, "服务内部错误")


# ------------------------------------------------------------
# 质量指标 SQL 条件（口径统一；patient_disposition/birth_weight 为事实表列，无需 JOIN）
# ------------------------------------------------------------
# patient_disposition 是枚举列（实测全部为精确值），LIKE '%%x%%' 既是非 sargable 的
# 全表扫描，又可能配不上任何值。这里改为等值匹配：
#   - Expired / Left Against Medical Advice 是精确值，等值语义不变、性能大幅改善。
#   - TRANSFER 原三个模式 '%%Short-Term General Hospital%%'/'%%Fed Health Care%%'/
#     '%%Inpatient Critical Access%%' 与库中实际值一个都对不上 → transfer_out 恒为 0
#     （旧口径 BUG）。已对齐为实际值 Short-term Hospital / Federal Health Care Facility
#     / Critical Access Hospital，修复后该指标恢复真实值。
MORTALITY_COND = "f.patient_disposition = 'Expired'"
AMA_COND = "f.patient_disposition = 'Left Against Medical Advice'"
TRANSFER_COND = ("(f.patient_disposition = 'Short-term Hospital' "
                 "OR f.patient_disposition = 'Federal Health Care Facility' "
                 "OR f.patient_disposition = 'Critical Access Hospital')")
LBW_COND = "f.birth_weight < 2500"

QUALITY_DIM = ("diagnosis", "facility", "age_group", "severity", "risk_mortality")


def _dim_parts(dimension):
    """维度 -> (内层分组列, 内层 JOIN, 外层 JOIN, key 表达式, name 表达式, 附加列)。
    诊断/机构按外键分组后在外层 JOIN 维度表取名；
    age_group/severity/risk_mortality 需在事实表内 JOIN 维度表取列（内层分组）。
    """
    if dimension == "diagnosis":
        return ("f.diagnosis_id", "",
                "JOIN dim_ccsr_diagnosis d ON t.id = d.diagnosis_id",
                "d.ccsr_code", "d.description", None, "idx_diagnosis")
    if dimension == "facility":
        return ("f.hospital_id", "",
                "LEFT JOIN dim_facility h ON t.id = h.facility_id",
                "h.facility_name", "h.facility_name", "h.hospital_county", "idx_hospital")
    if dimension == "age_group":
        return ("f.age_group", "", "", "t.id", "t.id", None, "")
    if dimension == "severity":
        return ("f.apr_severity_desc", "", "", "t.id", "t.id", None, "")
    if dimension == "risk_mortality":
        return ("f.apr_risk_mortality", "", "", "t.id", "t.id", None, "")
    raise BadRequest(f"dimension 仅支持 {sorted(QUALITY_DIM)}，收到: {dimension}")


def parse_min_cases(args, default=30):
    raw = args.get("min_cases", default)
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"min_cases 必须为整数，收到: {raw}")
    return min(max(v, 1), 10000)
