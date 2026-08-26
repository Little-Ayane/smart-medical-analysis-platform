#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
图表端点缓存预热脚本

背景：本项目的图表聚合查询在 1038 万行 fact_discharge 上执行，冷查询单条 10~130s。
      common.py / fastapi_common/mysql_dao.py 已加「持久化预聚合层 medical_db.api_cache」
      （跨重启存活，不依赖 Redis），本脚本通过 HTTP 调用各端点，把前端实际会请求的
      参数组合全部预计算并落盘，之后前端打开图表即可秒开。

用法：
    python3.11 database/warm_cache.py            # 预热全部
    python3.11 database/warm_cache.py --only drg # 只预热某个模块

依赖：服务需已在运行（Flask:5000 / core:8000 / drg:8001）。幂等：缓存持久化后
      重跑近乎瞬时（全部 cached=True）。

数据刷新说明：若重新导入数据，需先 TRUNCATE medical_db.api_cache 再重跑本脚本，
      否则会读到旧快照。
"""
import argparse
import sys
import time
import urllib.parse

import requests

FLASK = "http://127.0.0.1:5000"
CORE = "http://127.0.0.1:8000"
DRG = "http://127.0.0.1:8001"

# 每条请求超时（秒）。首次冷构建个别查询需数分钟。
TIMEOUT = 600

# ------------------------------------------------------------
# 前端固定参数组合（从 src/api/index.js + 各视图逐行抄出）
# 各视图的 tab 参数全部是硬编码字面量，无下拉框，故这是前端会打的全集。
# ------------------------------------------------------------
FLASK_GETS = [
    # cost
    "/api/v1/cost/profit-difference?dimension=diagnosis&top=10",
    "/api/v1/cost/profit-margin?dimension=diagnosis&top=10&order=desc",
    "/api/v1/cost/efficiency-ranking?dimension=diagnosis&top=15",
    "/api/v1/cost/composition?dimension=mdc&top=10",
    "/api/v1/cost/trend?start_year=2020&end_year=2024",
    # disease
    "/api/v1/disease/top-diagnoses?metric=count&top=10",
    "/api/v1/disease/top-procedures?metric=count&top=10",
    "/api/v1/disease/severity-profile?by=age_group&metric=count",
    "/api/v1/disease/population-diff?dimension=gender&metric=count",
    "/api/v1/disease/pyramid",
    "/api/v1/disease/region-diff?level=service_area&metric=count",
    "/api/v1/disease/heatmap?dim1=diagnosis&dim2=age_group&top=10",
    # payment
    "/api/v1/payment/cross?dim2=age_group&metric=count&top=10",
    "/api/v1/payment/sankey?levels=payment,payment2",
    "/api/v1/payment/cost-relation?by=payment&top=20",
    "/api/v1/payment/oop-burden?dimension=age_group&mode=selfpay1&top=10",
    "/api/v1/payment/summary",
    # quality
    "/api/v1/quality/overview",
    "/api/v1/quality/mortality?dimension=diagnosis&top=10&min_cases=30",
    "/api/v1/quality/length-of-stay?dimension=diagnosis&top=10&min_cases=30",
    "/api/v1/quality/facility-ranking?top=10&min_cases=100",
    "/api/v1/quality/disposition",
    # emergency（此前无缓存，现已接入 execute_cached）
    "/api/v1/analysis/emergency-rate",
    "/api/v1/analysis/emergency-compare",
    "/api/v1/analysis/avg-los?group_by=age_group",
    "/api/v1/analysis/outliers?los_threshold=30&charge_threshold=500000",
    "/api/v1/analysis/disposition/emergency-cross",
    # meta（DrillView 下拉选项）
    "/api/v1/meta/dimensions",
    # bigscreen（Dashboard「3D 大屏」）
    "/api/v1/bigscreen/overview",
]

CORE_GETS = [
    "/api/v1/analysis/metadata",
]

DRG_POSTS = [
    ("/api/v1/drg/cost-ranking", {"limit": 10, "sort_by": "avg_charges", "sort_order": "desc"}),
    ("/api/v1/drg/stay-comparison", {"group_by": "drg", "limit": 10}),
    ("/api/v1/drg/mortality-risk", {"group_by": "risk_mortality"}),
    ("/api/v1/drg/cmi-ranking", {"group_by": "drg", "limit": 10, "sort_order": "desc"}),
    ("/api/v1/drg/outlier-detection", {"metric": "avg_charges", "group_by": "drg",
                                        "method": "iqr", "threshold": 1.5, "limit": 20}),
]
DRG_GETS = [
    "/api/v1/drg/summary",
]

# ------------------------------------------------------------
# AI 助手（P4:5001）会用不同参数打这些端点，各补一组常用变体。
# ------------------------------------------------------------
AI_VARIANTS = [
    "/api/v1/disease/top-diagnoses?metric=total_charges&top=10",
    "/api/v1/disease/population-diff?dimension=race&metric=avg_charges",
    "/api/v1/disease/severity-profile?by=payment&metric=count",
    "/api/v1/disease/region-diff?level=county&metric=count",
    "/api/v1/disease/heatmap?dim1=diagnosis&dim2=severity&top=10",
    "/api/v1/payment/cross?dim2=severity&metric=count&top=10",
    "/api/v1/payment/oop-burden?dimension=disease&mode=selfpay1&top=10",
    "/api/v1/quality/mortality?dimension=age_group&top=10&min_cases=30",
    "/api/v1/quality/length-of-stay?dimension=severity&top=10&min_cases=30",
    "/api/v1/cost/profit-difference?dimension=mdc&top=10",
    "/api/v1/cost/profit-margin?dimension=drg&top=10&order=desc",
    "/api/v1/analysis/avg-los?group_by=discharge_year",
]


def warm_get(session, base, path, label):
    url = base + path
    t0 = time.time()
    r = session.get(url, timeout=TIMEOUT)
    dt = int((time.time() - t0) * 1000)
    ok = 200 <= r.status_code < 300
    cached = (r.headers.get("X-Cache") or "").lower() == "true"
    print(f"  [{'OK' if ok else 'FAIL'}] {label:<12} {path}  -> {r.status_code} {dt}ms cached={cached}")
    return ok, dt


def warm_post(session, base, path, body, label):
    url = base + path
    t0 = time.time()
    r = session.post(url, json=body, timeout=TIMEOUT)
    dt = int((time.time() - t0) * 1000)
    ok = 200 <= r.status_code < 300
    print(f"  [{'OK' if ok else 'FAIL'}] {label:<12} {path} {body}  -> {r.status_code} {dt}ms")
    return ok, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["flask", "core", "drg", "ai"], default=None)
    args = ap.parse_args()

    session = requests.Session()
    failures = 0
    total_ms = 0
    t_start = time.time()

    def run_get(base, path, label):
        nonlocal failures, total_ms
        ok, dt = warm_get(session, base, path, label)
        total_ms += dt
        if not ok:
            failures += 1

    def run_post(base, path, body, label):
        nonlocal failures, total_ms
        ok, dt = warm_post(session, base, path, body, label)
        total_ms += dt
        if not ok:
            failures += 1

    if args.only in (None, "flask"):
        print("== Flask :5000 ==")
        for p in FLASK_GETS:
            run_get(FLASK, p, "flask")
    if args.only in (None, "ai"):
        print("== AI 助手变体 ==")
        for p in AI_VARIANTS:
            run_get(FLASK, p, "ai")
    if args.only in (None, "core"):
        print("== core :8000 ==")
        for p in CORE_GETS:
            run_get(CORE, p, "core")
    if args.only in (None, "drg"):
        print("== drg :8001 ==")
        for p in DRG_GETS:
            run_get(DRG, p, "drg")
        for p, b in DRG_POSTS:
            run_post(DRG, p, b, "drg")

    elapsed = int(time.time() - t_start)
    print(f"\n预热完成：{elapsed}s，累计请求耗时 {total_ms}ms，失败 {failures} 项")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
