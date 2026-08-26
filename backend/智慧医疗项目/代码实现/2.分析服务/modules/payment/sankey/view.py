# -*- coding: utf-8 -*-
"""桑葚图（ECharts sankey）：GET /api/v1/payment/sankey
levels 硬编码白名单；逐层 IS NOT NULL；缓存手动编排。数据源：medical_db 星型模型。
"""
import time as _time

from flask import request

from common import (SEVERITY_CODE_TO_DESC, cache_get, cache_key, cache_set,
                    envelope, fetch_dim_names, parse_choice, parse_top, timed_query)
from star_common import (JOIN_DRG, JOIN_PATIENT, JOIN_PAYMENT, merge_joins,
                         parse_filters_star)
from .._shared import _endpoint, payment_bp

SANK_LEVELS = {
    "payment,payment2": (
        ("支付1", "payment_typology_1"),
        ("支付2", "payment_typology_2"),
    ),
    "payment,payment2,payment3": (
        ("支付1", "payment_typology_1"),
        ("支付2", "payment_typology_2"),
        ("支付3", "payment_typology_3"),
    ),
    "payment,age_group": (
        ("支付", "payment_typology_1"),
        ("年龄段", "age_group"),
    ),
    "payment,age_group,disease": (
        ("支付", "payment_typology_1"),
        ("年龄段", "age_group"),
        ("病种", "diagnosis_id"),
    ),
    "payment,disease": (
        ("支付", "payment_typology_1"),
        ("病种", "diagnosis_id"),
    ),
    "payment,severity": (
        ("支付", "payment_typology_1"),
        ("严重程度", "apr_severity_code"),
    ),
}

# 扁平列名 -> (反规范化事实表列, JOIN)
_STAR_COL = {
    "payment_typology_1": ("f.payment_typology_1", ""),
    "payment_typology_2": ("f.payment_typology_2", ""),
    "payment_typology_3": ("f.payment_typology_3", ""),
    "age_group": ("f.age_group", ""),
    "diagnosis_id": ("f.diagnosis_id", ""),
    "apr_severity_code": ("f.apr_severity_code", ""),
}


@payment_bp.route("/sankey")
def sankey():
    def handler(args):
        levels_key = parse_choice(args, "levels", SANK_LEVELS, "payment,payment2")
        layers = SANK_LEVELS[levels_key]
        top_disease = parse_top(args, 8, cap=20, name="top_disease")
        where, params, norm, fjoins = parse_filters_star(args)

        star_cols = [_STAR_COL[c] for _, c in layers]
        joins = merge_joins([j for _, j in star_cols], fjoins)
        join_sql = " ".join(joins)

        conds = [f"{col} IS NOT NULL" for col, _ in star_cols]
        has_disease = any(c == "diagnosis_id" for _, c in layers)
        if has_disease:
            conds.append("f.diagnosis_id IN (SELECT id FROM "
                         "(SELECT diagnosis_id AS id, COUNT(*) AS c "
                         "FROM fact_discharge "
                         "GROUP BY diagnosis_id ORDER BY c DESC LIMIT %s) x)")
        conds = where + conds
        where_sql = "WHERE " + " AND ".join(conds)

        cols = [col for col, _ in star_cols]
        sql = (f"SELECT {', '.join(f'{c} AS l{i}' for i, c in enumerate(cols, 1))}, "
               f"COUNT(*) AS cnt FROM fact_discharge f {join_sql} {where_sql} "
               f"GROUP BY {', '.join(cols)}")
        query_params = params + ([top_disease] if has_disease else [])

        key = cache_key(request.path, args)
        hit, payload = cache_get(key)
        if hit:
            return envelope(payload["data"], "sankey", "count", payload["total"], 0,
                            filters=norm, cached=True, **payload["extras"])

        start = _time.time()
        rows, _ = timed_query(sql, query_params)
        chain_total = sum(int(r["cnt"]) for r in rows)
        filtered_rows, _ = timed_query(
            f"SELECT COUNT(*) AS c FROM fact_discharge f {join_sql} "
            f"{('WHERE ' + ' AND '.join(where)) if where else ''}", params)
        extra = {"null_excluded": int(filtered_rows[0]["c"] or 0) - chain_total,
                 "levels": levels_key}

        diag_names = fetch_dim_names("dim_ccsr_diagnosis", "diagnosis_id") \
            if has_disease else None
        nodes, node_names = [], {}

        def get_node(layer, layer_index, value):
            display = value
            if layer == "病种":
                pair = diag_names.get(value)
                value = pair[0] if pair else value
                display = pair[1] if pair else str(value)
            elif layer == "严重程度":
                display = SEVERITY_CODE_TO_DESC.get(value, "Unknown")
            name = f"{layer}|{value}"
            if name not in node_names:
                node_names[name] = {"name": name, "display": str(display),
                                    "layer": layer, "layer_index": layer_index}
                nodes.append(node_names[name])
            return name

        link_agg = {}
        for r in rows:
            values = [r[f"l{i}"] for i in range(1, len(layers) + 1)]
            for i in range(len(layers) - 1):
                src = get_node(layers[i][0], i, values[i])
                dst = get_node(layers[i + 1][0], i + 1, values[i + 1])
                link_agg[(src, dst)] = link_agg.get((src, dst), 0) + int(r["cnt"])
        data = {"nodes": nodes,
                "links": [{"source": s, "target": t, "value": v}
                          for (s, t), v in link_agg.items()]}
        ms = int((_time.time() - start) * 1000)
        payload = {"data": data, "total": chain_total, "extras": extra}
        cache_set(key, payload)
        return envelope(data, "sankey", "count", chain_total, ms, norm, **extra)

    return _endpoint("sankey", request.args, handler)
