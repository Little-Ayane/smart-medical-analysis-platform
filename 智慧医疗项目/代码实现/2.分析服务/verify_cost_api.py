# -*- coding: utf-8 -*-
"""
纪志鹏 · cost 接口验证脚本
运行环境：能连到 smart_health 且已装 flask / pymysql / flask-cors 的机器（即 VM，
          因为 common.DB 的 host=127.0.0.1，应用须与 MySQL 同机运行）。

用法：
  cd 2.分析服务
  python verify_cost_api.py            # 真实连库测试（依赖 smart_health 已导入 CSV 数据）
  python verify_cost_api.py --mock     # 用假数据验证逻辑/路由/信封，不连库（适合先确认代码无误）

退出码：全部通过=0，有失败=1
"""
import sys

# ---- mock 模式：必须在 import app 之前 patch 查询函数 ----
if "--mock" in sys.argv:
    import common
    import modules.cost.view as view

    def fake_timed_query(sql, params=None):
        if "COUNT(*) AS c" in sql:
            return [{"c": 3}], 1
        if "total_all" in sql:
            return [{"total_all": 1_000_000.0}], 1
        rows = [
            {"key": "示例维度A", "count": 120, "value": 12345.67,
             "total_charges": 500000.0, "total_costs": 380000.0,
             "avg_charges": 4166.0, "avg_costs": 3166.0,
             "avg_profit_difference": 1000.0, "profit_margin_pct": 31.58,
             "efficiency_grade": "A（高效益）", "grade_basis": "利润率 31.58%",
             "pct": 5.0, "year": 2021, "dimension_key": "示例维度A",
             "profit_difference": 120000.0},
            {"key": "示例维度B", "count": 80, "value": 6789.0,
             "total_charges": 300000.0, "total_costs": 240000.0,
             "avg_charges": 3750.0, "avg_costs": 3000.0,
             "avg_profit_difference": 750.0, "profit_margin_pct": 25.0,
             "efficiency_grade": "B（中高效益）", "grade_basis": "利润率 25.0%",
             "pct": 3.0, "year": 2021, "dimension_key": "示例维度B",
             "profit_difference": 60000.0},
        ]
        return rows, 1

    common.timed_query = fake_timed_query
    view.timed_query = fake_timed_query

from app import app
import json

client = app.test_client()


def hit(method, path, expect_code=0):
    """发起请求并校验返回信封。expect_code 指 body['code']（400 校验类也走 HTTP 200）。"""
    r = client.get(path) if method == "GET" else client.post(path)
    try:
        body = r.get_json()
    except Exception:
        body = None
    code = body.get("code") if isinstance(body, dict) else None
    ok = (code == expect_code)
    print(f"[{'OK ' if ok else 'FAIL'}] {method} {path}")
    if isinstance(body, dict):
        data = body.get("data")
        n = len(data) if isinstance(data, (list, dict)) else 0
        print(f"       code={code} message={body.get('message')} data_len={n}")
        if ok and isinstance(data, list) and data:
            print(f"       sample={json.dumps(data[0], ensure_ascii=False)[:220]}")
    else:
        print(f"       raw={str(r.data)[:220]}")
    return ok


results = []
print("===== 健康检查（真实模式会真正连库）=====")
results.append(hit("GET", "/api/v1/health"))

print("\n===== 5 个 cost 接口（正常参数）=====")
results.append(hit("GET", "/api/v1/cost/profit-difference?dimension=payment_typology&top=10"))
results.append(hit("GET", "/api/v1/cost/profit-margin?dimension=age_group"))
results.append(hit("GET", "/api/v1/cost/efficiency-ranking?dimension=mdc"))
results.append(hit("GET", "/api/v1/cost/composition?dimension=facility"))
results.append(hit("GET", "/api/v1/cost/trend?metric=total_charges"))

print("\n===== 参数校验（均应返回 code=400）=====")
results.append(hit("GET", "/api/v1/cost/profit-difference?dimension=bad", expect_code=400))
results.append(hit("GET", "/api/v1/cost/profit-difference?top=abc", expect_code=400))
results.append(hit("GET", "/api/v1/cost/profit-difference?year=2020", expect_code=400))

passed = sum(1 for x in results if x)
total = len(results)
print(f"\n===== 结果：{passed}/{total} 通过 =====")
sys.exit(0 if passed == total else 1)
