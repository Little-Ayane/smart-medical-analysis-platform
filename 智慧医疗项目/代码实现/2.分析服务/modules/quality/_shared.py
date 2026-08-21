# -*- coding: utf-8 -*-
"""模块四 · 医疗质量监测 模块内公用：蓝图、统一异常包装、质量指标 SQL 条件常量。

口径说明（数据为 NY SPARCS 2021 快照，字段见 数据库设计/schema.sql）：
    - 住院死亡率：patient_disposition 含 'Expired'（院内死亡）
    - 非医嘱离院率：patient_disposition 含 'Left Against Medical Advice'
    - 转院率：离院去向为短期综合医院 / 联邦医疗机构 / 乡村急救医院
    - 低出生体重率：birth_weight < 2500 克（仅新生儿有出生体重，非新生儿为 NULL，不参与分母）
    - 再入院率 / 院内感染率：数据无患者唯一标识 / 无感染字段，无法计算（见接口文档口径声明）
性能约定：一律"先按事实表列/外键 GROUP BY 预聚合，后 JOIN 小维度表取名"。
"""
from flask import Blueprint, current_app

from common import BadRequest, error

quality_bp = Blueprint("quality", __name__, url_prefix="/api/v1/quality")


def _endpoint(path, args, handler):
    try:
        return handler(args)
    except BadRequest as e:
        return error(400, str(e))
    except Exception:
        current_app.logger.exception("[quality/%s] 处理异常", path)
        return error(500, "服务内部错误")


# ------------------------------------------------------------
# 质量指标 SQL 条件（口径统一，多接口复用；MySQL 中 SUM(条件) = 满足行数）
# ------------------------------------------------------------
MORTALITY_COND = "f.patient_disposition LIKE '%Expired%'"
AMA_COND = "f.patient_disposition LIKE '%Left Against Medical Advice%'"
TRANSFER_COND = ("(f.patient_disposition LIKE '%Short-Term General Hospital%' "
                 "OR f.patient_disposition LIKE '%Fed Health Care%' "
                 "OR f.patient_disposition LIKE '%Inpatient Critical Access%')")
LBW_COND = "f.birth_weight < 2500"   # 低出生体重：<2500g；分母为 birth_weight IS NOT NULL

# 维度白名单：分组分析（死亡率 / 平均住院日）可用维度
QUALITY_DIM = ("diagnosis", "facility", "age_group", "severity", "risk_mortality")


def _dim_parts(dimension):
    """维度 -> (内层分组列, 外层 JOIN, 外层 key 表达式, 外层 name 表达式, 附加列)。
    内层子查询统一以 id 别名分组，外层 JOIN 小维度表取名；
    无维度表依赖的列（age_group/severity/risk_mortality）直接用 t.id。
    """
    if dimension == "diagnosis":
        return ("f.diagnosis_id", "JOIN dim_ccsr_diagnosis d ON t.id = d.diagnosis_id",
                "d.ccsr_code", "d.description", None)
    if dimension == "facility":
        return ("f.facility_id", "LEFT JOIN dim_facility h ON t.id = h.facility_id",
                "h.facility_name", "h.facility_name", "h.hospital_county")
    if dimension in ("age_group", "severity", "risk_mortality"):
        col = {"age_group": "f.age_group", "severity": "f.apr_severity_desc",
               "risk_mortality": "f.apr_risk_mortality"}[dimension]
        return (col, "", "t.id", "t.id", None)
    raise BadRequest(f"dimension 仅支持 {sorted(QUALITY_DIM)}，收到: {dimension}")


def parse_min_cases(args, default=30):
    """最小样本量（剔除分母过小导致比率失真的分组）。"""
    raw = args.get("min_cases", default)
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"min_cases 必须为整数，收到: {raw}")
    return min(max(v, 1), 10000)
