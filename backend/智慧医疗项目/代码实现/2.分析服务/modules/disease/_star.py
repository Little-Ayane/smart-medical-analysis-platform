# -*- coding: utf-8 -*-
"""病种模块 · 星型模型(medical_db)查询辅助。
与 common.py 的 smart_health 扁平表版本对应：把列引用改为维度表 JOIN。
维度表视图(dim_ccsr_diagnosis/dim_ccsr_procedure/dim_facility)已在 medical_db 建好、
列名与 smart_health 对齐，因此 DIM_SUBQUERY 与 fetch_dim_names/fetch_facility_map 可复用。
"""
from common import BadRequest, DIM_SUBQUERY, _norm_gender, _norm_severity
# 年份谓词helper 与 star_common 共用一份实现，避免两处逻辑漂移
from star_common import year_scan_cond, where_sql_star  # noqa: F401


def _norm_year_star(v):
    v = v.strip()
    if v not in ("2020", "2021", "2022", "2023", "2024"):
        raise BadRequest(f"year 仅支持 2020-2024，收到: {v}")
    return int(v)


# 参数名 -> (列表达式, 规范化函数, 需要的 JOIN 子句)
# 已反规范化到 fact_discharge 的维度列直接用事实表列，避免 JOIN 维度表导致覆盖索引失效。
FILTER_COLS_STAR = {
    "year": ("f.discharge_year", _norm_year_star, ""),
    "gender": ("f.gender", _norm_gender, ""),
    "age_group": ("f.age_group", lambda v: v.strip(), ""),
    "payment": ("f.payment_typology_1", lambda v: v.strip(), ""),
    "payment2": ("f.payment_typology_2", lambda v: v.strip(), ""),
    "payment3": ("f.payment_typology_3", lambda v: v.strip(), ""),
    "severity": ("f.apr_severity_code", _norm_severity, ""),
    "diagnosis": ("f.diagnosis_id", None, ""),
    "procedure": ("f.procedure_id", None, ""),
    "service_area": ("f.hospital_id", None, ""),
    "county": ("f.hospital_id", None, ""),
    "facility": ("f.hospital_id", None, ""),
}

# 维度值过滤子查询：表名/列名已与 medical_db 维度视图对齐，直接复用
DIM_SUBQUERY_STAR = DIM_SUBQUERY


def parse_filters_star(args):
    """星型版 parse_filters：额外返回去重后的 JOIN 子句列表。"""
    where, params, norm, joins = [], [], {}, []
    seen = set()
    for name, value in args.items():
        if name not in FILTER_COLS_STAR:
            continue
        col, norm_fn, join_sql = FILTER_COLS_STAR[name]
        if join_sql and join_sql not in seen:
            joins.append(join_sql)
            seen.add(join_sql)
        if name in DIM_SUBQUERY_STAR:
            table, pk, cond, val_fn = DIM_SUBQUERY_STAR[name]
            vals = val_fn(value)
            where.append(f"{col} IN (SELECT {pk} FROM {table} WHERE {cond})")
            params.extend(vals)
            norm[name] = vals[0]
        else:
            v = norm_fn(value)
            where.append(f"{col} = %s")
            params.append(v)
            norm[name] = v
    return where, params, norm, joins


def merge_joins(*groups):
    """合并多组 JOIN 子句并去重。"""
    seen, out = set(), []
    for group in groups:
        for j in group:
            if j and j not in seen:
                seen.add(j)
                out.append(j)
    return out
