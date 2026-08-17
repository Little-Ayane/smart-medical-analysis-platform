# -*- coding: utf-8 -*-
"""桑葚图（ECharts sankey）：GET /api/v1/payment/sankey
levels 硬编码白名单（禁止自由组合，见 SANK_LEVELS）；节点 name 一律 "{层}|{值}"
前缀（跨层同名支付方式保证全局唯一），display 为展示名；逐层 IS NOT NULL，
meta.total_records = 走完全部层的记录数，null_excluded = 中途退出链路的记录数。
三级链仅 15.8% 记录能走完（326,038 条），前端建议提示口径。
缓存：手动编排（null_excluded 需与链路样本数联动），命中时零 SQL。
"""
import time as _time

from flask import request

from common import (SEVERITY_CODE_TO_DESC, cache_get, cache_key, cache_set,
                    envelope, fetch_dim_names, parse_choice, parse_filters,
                    parse_top, timed_query)
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


@payment_bp.route("/sankey")
def sankey():
    def handler(args):
        levels_key = parse_choice(args, "levels", SANK_LEVELS, "payment,payment2")
        layers = SANK_LEVELS[levels_key]
        top_disease = parse_top(args, 8, cap=20, name="top_disease")
        where, params, norm = parse_filters(args)

        # 逐层 IS NOT NULL（三层链只有 326,038 条记录能走完）
        conds = [f"f.{col} IS NOT NULL" for _, col in layers]
        has_disease = any(col == "diagnosis_id" for _, col in layers)
        if has_disease:
            conds.append("f.diagnosis_id IN (SELECT id FROM "
                         "(SELECT diagnosis_id AS id, COUNT(*) AS c "
                         "FROM fact_inpatient_discharge "
                         "GROUP BY diagnosis_id ORDER BY c DESC LIMIT %s) x)")
        conds = where + conds
        where_sql = "WHERE " + " AND ".join(conds)

        cols = [col for _, col in layers]
        sql = (f"SELECT {', '.join(f'f.{c} AS l{i}' for i, c in enumerate(cols, 1))}, "
               f"COUNT(*) AS cnt FROM fact_inpatient_discharge f {where_sql} "
               f"GROUP BY {', '.join(f'f.{c}' for c in cols)}")
        query_params = params + ([top_disease] if has_disease else [])

        # 桑葚图 meta 特殊（null_excluded 需与链路样本数联动），手动缓存编排，
        # 保证缓存命中时不再执行任何 SQL。
        key = cache_key(request.path, args)
        hit, payload = cache_get(key)
        if hit:
            return envelope(payload["data"], "sankey", "count", payload["total"], 0,
                            filters=norm, cached=True, **payload["extras"])

        start = _time.time()
        rows, _ = timed_query(sql, query_params)
        chain_total = sum(int(r["cnt"]) for r in rows)   # 走完全部层的记录数
        filtered_rows, _ = timed_query(
            f"SELECT COUNT(*) AS c FROM fact_inpatient_discharge f "
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
                # 节点名用 CCSR 代码（全局唯一），展示用描述
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
