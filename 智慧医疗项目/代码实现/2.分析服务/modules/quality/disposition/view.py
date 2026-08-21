# -*- coding: utf-8 -*-
"""离院去向构成（饼图）：GET /api/v1/quality/disposition
返回 [{key,count,pct}]，固定业务顺序 Home < Transfer/Other Facility < SNF <
Hospice < Expired < AMA < Other（无法归入的原始去向追加在后）。
口径：离院去向是质量安全观察窗口——Expired=院内死亡、AMA=非医嘱离院、
Transfer/Other Facility=转院（含精神/康复/联邦机构），Home=常规出院。
"""
from flask import request

from common import envelope, execute_cached, parse_filters
from .._shared import _endpoint, quality_bp

# 分组顺序即业务顺序（前端饼图扇区顺序）
GROUP_ORDER = ["Home", "Transfer/Other Facility", "SNF", "Hospice",
               "Expired", "AMA", "Other"]

# 归一化 CASE：WHEN 顺序即优先级（Expired/AMA 优先，转院类次之，Home 兜底识别）
GROUP_CASE = """CASE
    WHEN patient_disposition LIKE '%Expired%' THEN 'Expired'
    WHEN patient_disposition LIKE '%Left Against Medical Advice%' THEN 'AMA'
    WHEN patient_disposition LIKE '%Hospice%' THEN 'Hospice'
    WHEN patient_disposition LIKE '%Skilled Nursing%' THEN 'SNF'
    WHEN (patient_disposition LIKE '%Short-Term General Hospital%'
       OR patient_disposition LIKE '%Fed Health Care%'
       OR patient_disposition LIKE '%Inpatient Critical Access%'
       OR patient_disposition LIKE '%Psychiatric%'
       OR patient_disposition LIKE '%Rehabilitation%'
       OR patient_disposition LIKE '%Swing Bed%') THEN 'Transfer/Other Facility'
    WHEN patient_disposition LIKE '%Home%' THEN 'Home'
    ELSE 'Other' END"""


@quality_bp.route("/disposition")
def disposition():
    def handler(args):
        where, params, norm = parse_filters(args)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        sql = (f"SELECT {GROUP_CASE} AS grp, COUNT(*) AS cnt "
               f"FROM fact_inpatient_discharge f {where_sql} GROUP BY grp")
        count_sql = f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f {where_sql}"

        def post(rows):
            by_key = {r["grp"]: int(r["cnt"]) for r in rows}
            total = sum(by_key.values())
            out = []
            for key in GROUP_ORDER:
                if key in by_key:
                    out.append({"key": key, "count": by_key[key],
                                "pct": round(by_key[key] * 100.0 / total, 2)})
            for key, cnt in by_key.items():          # 未归一化的原始去向追加在后
                if key not in GROUP_ORDER:
                    out.append({"key": key, "count": cnt,
                                "pct": round(cnt * 100.0 / total, 2)})
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params, count_sql, params, post)
        return envelope(data, "disposition", "count", total, ms, norm, cached, **extra)

    return _endpoint("disposition", request.args, handler)
