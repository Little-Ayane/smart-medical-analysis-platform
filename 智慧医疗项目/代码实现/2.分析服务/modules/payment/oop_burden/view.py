# -*- coding: utf-8 -*-
"""自付负担（柱状 / 散点）：GET /api/v1/payment/oop-burden
dimension ∈ disease/age_group/county；mode 双口径：
    selfpay1  支付方式1 = Self-Pay（全额自费 26,310 条，有真实费用），
              返回 self_pay_charges/avg/share_of_charges 金额字段；
    any_layer 任一层含 Self-Pay（保险自付部分，本数据无法推断金额），仅返回占比。
返回按 self_pay_count 降序；county 维度经 facility 重映射后合并。
"""
from flask import request

from common import (envelope, execute_cached, fetch_dim_names, fetch_facility_map,
                    parse_choice, parse_filters, parse_top)
from .._shared import _endpoint, payment_bp

OOP_DIMS = {"disease": ("diagnosis_id", "dim"),
            "age_group": ("age_group", "fact"),
            "county": ("facility_id", "facility")}


@payment_bp.route("/oop-burden")
def oop_burden():
    def handler(args):
        dimension = parse_choice(args, "dimension", OOP_DIMS, "disease")
        mode = parse_choice(args, "mode", ("selfpay1", "any_layer"), "selfpay1")
        top = parse_top(args, 15, cap=50)
        where, params, norm = parse_filters(args)
        col, kind = OOP_DIMS[dimension]

        conds = list(where)
        extra_params = []
        if kind == "dim":
            conds.append(f"f.{col} IN (SELECT id FROM (SELECT {col} AS id, "
                         f"COUNT(*) AS c FROM fact_inpatient_discharge "
                         f"GROUP BY {col} ORDER BY c DESC LIMIT %s) x)")
            extra_params.append(top)
        where_sql = ("WHERE " + " AND ".join(conds)) if conds else ""

        if mode == "selfpay1":
            sp_cond = "payment_typology_1='Self-Pay'"
            charge_cols = (", ROUND(SUM(CASE WHEN payment_typology_1='Self-Pay' "
                           "THEN total_charges END),2) AS sp_charges, "
                           "ROUND(SUM(total_charges),2) AS total_charges")
        else:
            sp_cond = ("payment_typology_1='Self-Pay' OR "
                       "payment_typology_2='Self-Pay' OR "
                       "payment_typology_3='Self-Pay'")
            charge_cols = ""
        sql = (f"SELECT {col} AS k, COUNT(*) AS total_count, "
               f"SUM({sp_cond}) AS sp_count{charge_cols} "
               f"FROM fact_inpatient_discharge f {where_sql} GROUP BY {col}")
        count_sql = (f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
                     f"{('WHERE ' + ' AND '.join(where)) if where else ''}")

        def post(rows):
            fac_map = fetch_facility_map() if kind == "facility" else None
            name_map = fetch_dim_names("dim_ccsr_diagnosis", "diagnosis_id") \
                if kind == "dim" else None
            merged = {}    # key -> [total_count, sp_count, sp_charges, total_charges]
            for r in rows:
                if kind == "facility":
                    key = fac_map[r["k"]][1] if r["k"] in fac_map else "Unknown"
                else:
                    key = r["k"] or "Unknown"
                m = merged.get(key)
                if m is None:
                    merged[key] = m = [0, 0, 0.0, 0.0]
                m[0] += int(r["total_count"])
                m[1] += int(r["sp_count"] or 0)
                # any_layer 模式 SQL 不含费用列，用 .get 兜底
                m[2] += float(r.get("sp_charges") or 0)
                m[3] += float(r.get("total_charges") or 0)

            out = []
            for key, (total_c, sp_c, sp_chg, total_chg) in merged.items():
                item = {"key": key, "total_count": total_c, "self_pay_count": sp_c,
                        "self_pay_pct": round(sp_c * 100.0 / total_c, 2)
                        if total_c else 0}
                if kind == "dim":
                    pair = name_map.get(key)
                    item["name"] = pair[1] if pair else None
                if mode == "selfpay1":
                    item["self_pay_charges"] = round(sp_chg, 2)
                    item["self_pay_avg_charges"] = round(sp_chg / sp_c, 2) if sp_c else None
                    item["self_pay_share_of_charges"] = round(
                        sp_chg * 100.0 / total_chg, 2) if total_chg else None
                out.append(item)
            out.sort(key=lambda x: -x["self_pay_count"])
            return out

        data, total, ms, cached, extra = execute_cached(
            request.path, args, sql, params + extra_params, count_sql, params, post)
        return envelope(data, dimension, f"oop_{mode}", total, ms, norm,
                        cached, **extra)

    return _endpoint("oop-burden", request.args, handler)
