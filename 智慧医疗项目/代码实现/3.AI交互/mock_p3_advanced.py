# -*- coding: utf-8 -*-
"""
P3 Mock 服务（支持新版 13 个接口）
用途：在 P3 真实服务未开启时，让 P4 进行端到端测试
启动：python mock_p3_advanced.py
监听：http://127.0.0.1:5000/api/v1
"""
from flask import Flask, request, jsonify
import time
import random

app = Flask(__name__)

# ==================== 通用响应包装 ====================
def ok_response(data, total=None, query_ms=None):
    if total is None:
        total = len(data) if isinstance(data, list) else 1
    return {
        "data": data,
        "meta": {
            "total_records": total,
            "query_ms": query_ms or random.randint(5, 20),
        }
    }
# ==================== 旧版接口（向后兼容） ====================

@app.route('/api/v1/analysis/aggregate', methods=['GET'])
def mock_aggregate():
    """旧版聚合接口：按 dimension 和 metric 分组统计"""
    dimension = request.args.get('dimension', 'ccsr_diagnosis')
    metric = request.args.get('metric', 'count')
    top = int(request.args.get('top', 10))
    year = request.args.get('year')
    gender = request.args.get('gender')
    age_group = request.args.get('age_group')

    # 模拟数据（与新版 top_diagnoses 保持一致）
    sample = [
        {"key": "肺炎", "value": 1200, "count": 1200},
        {"key": "心力衰竭", "value": 980, "count": 980},
        {"key": "慢性阻塞性肺病", "value": 760, "count": 760},
        {"key": "急性心肌梗死", "value": 540, "count": 540},
        {"key": "脑卒中", "value": 430, "count": 430},
    ]
    # 根据 metric 调整 value
    if metric == "count":
        for item in sample:
            item["value"] = item["count"]
    elif metric == "avg_length_of_stay":
        # 模拟住院天数
        los_map = {"肺炎": 7.2, "心力衰竭": 6.8, "慢性阻塞性肺病": 5.9, "急性心肌梗死": 4.5, "脑卒中": 3.2}
        for item in sample:
            item["value"] = los_map.get(item["key"], 5.0)
    elif metric == "total_charges":
        charges_map = {"肺炎": 3200000, "心力衰竭": 2800000, "慢性阻塞性肺病": 2100000, "急性心肌梗死": 1800000, "脑卒中": 1200000}
        for item in sample:
            item["value"] = charges_map.get(item["key"], 1000000)
    elif metric == "avg_charges":
        avg_map = {"肺炎": 2666.67, "心力衰竭": 2857.14, "慢性阻塞性肺病": 2763.16, "急性心肌梗死": 3333.33, "脑卒中": 2790.70}
        for item in sample:
            item["value"] = avg_map.get(item["key"], 2000.0)
    else:
        # 默认 count
        for item in sample:
            item["value"] = item["count"]

    data = sample[:top]
    return jsonify({
        "data": data,
        "meta": {
            "total_records": sum(item["count"] for item in sample),
            "query_ms": 15,
            "dimension": dimension,
            "metric": metric
        }
    })

@app.route('/api/v1/analysis/payment-mix', methods=['GET'])
def mock_payment_mix():
    """旧版支付占比接口"""
    data = [
        {"payment": "Medicare", "count": 45000, "pct": 45.0},
        {"payment": "Medicaid", "count": 30000, "pct": 30.0},
        {"payment": "Private Health Insurance", "count": 20000, "pct": 20.0},
        {"payment": "Self-Pay", "count": 5000, "pct": 5.0},
    ]
    return jsonify({
        "data": data,
        "meta": {"total_records": 100000, "query_ms": 10}
    })

@app.route('/api/v1/analysis/trend', methods=['GET'])
def mock_trend():
    """旧版趋势接口"""
    data = [
        {"year": 2018, "count": 80000},
        {"year": 2019, "count": 85000},
        {"year": 2020, "count": 95000},
        {"year": 2021, "count": 110000},
    ]
    return jsonify({
        "data": data,
        "meta": {"total_records": 370000, "query_ms": 8}
    })
# ==================== 病种分析接口（7 个） ====================

@app.route('/api/v1/disease/top-diagnoses', methods=['GET'])
def mock_top_diagnoses():
    metric = request.args.get('metric', 'count')
    top = int(request.args.get('top', 10))
    sample = [
        {"code": "J18", "name": "肺炎", "count": 1200, "value": 1200, "avg_los": 7.2, "total_charges": 3200000, "avg_charges": 2666.67},
        {"code": "I50", "name": "心力衰竭", "count": 980, "value": 980, "avg_los": 6.8, "total_charges": 2800000, "avg_charges": 2857.14},
        {"code": "J44", "name": "慢性阻塞性肺病", "count": 760, "value": 760, "avg_los": 5.9, "total_charges": 2100000, "avg_charges": 2763.16},
        {"code": "I21", "name": "急性心肌梗死", "count": 540, "value": 540, "avg_los": 4.5, "total_charges": 1800000, "avg_charges": 3333.33},
        {"code": "I63", "name": "脑卒中", "count": 430, "value": 430, "avg_los": 3.2, "total_charges": 1200000, "avg_charges": 2790.70},
    ]
    # 根据 metric 调整返回字段
    result = []
    for item in sample[:top]:
        if metric == "count":
            val = item["count"]
        elif metric == "avg_los":
            val = item["avg_los"]
        elif metric == "total_charges":
            val = item["total_charges"]
        else:
            val = item["avg_charges"]
        result.append({"code": item["code"], "name": item["name"], "value": val, "count": item["count"]})
    return jsonify(ok_response(result, total=sum(item["count"] for item in sample)))

@app.route('/api/v1/disease/top-procedures', methods=['GET'])
def mock_top_procedures():
    samples = [
        {"code": "PGN003", "name": "剖宫产术", "count": 320, "value": 320},
        {"code": "MST006", "name": "膝关节置换术", "count": 280, "value": 280},
        {"code": "MST007", "name": "髋关节置换术", "count": 210, "value": 210},
    ]
    return jsonify(ok_response(samples, total=810))

@app.route('/api/v1/disease/severity-profile', methods=['GET'])
def mock_severity_profile():
    by = request.args.get('by', 'age_group')
    groups = ["0-17", "18-29", "30-49", "50-69", "70+"] if by == "age_group" else ["肺炎", "心衰", "COPD"]
    data = []
    sev = ["Minor", "Moderate", "Major", "Extreme"]
    for g in groups:
        for s in sev:
            data.append({"group": g, "severity": s, "value": random.randint(10, 100), "count": random.randint(10, 100)})
    return jsonify(ok_response(data, total=sum(d["value"] for d in data)))

@app.route('/api/v1/disease/population-diff', methods=['GET'])
def mock_population_diff():
    dim = request.args.get('dimension', 'gender')
    if dim == "gender":
        data = [{"key": "男性", "value": 5800, "count": 5800, "pct": 58.0},
                {"key": "女性", "value": 4200, "count": 4200, "pct": 42.0}]
    elif dim == "race":
        data = [{"key": "White", "value": 4500, "count": 4500, "pct": 45.0},
                {"key": "Black/African American", "value": 3000, "count": 3000, "pct": 30.0},
                {"key": "Other Race", "value": 2500, "count": 2500, "pct": 25.0}]
    else:
        data = [{"key": "Medical", "value": 6000, "count": 6000, "pct": 60.0},
                {"key": "Surgical", "value": 4000, "count": 4000, "pct": 40.0}]
    return jsonify(ok_response(data, total=sum(d["value"] for d in data)))

@app.route('/api/v1/disease/pyramid', methods=['GET'])
def mock_pyramid():
    data = [
        {"age_group": "0-17", "male": 3200, "female": 2900, "total": 6100},
        {"age_group": "18-29", "male": 2800, "female": 3100, "total": 5900},
        {"age_group": "30-49", "male": 3500, "female": 3800, "total": 7300},
        {"age_group": "50-69", "male": 4200, "female": 4600, "total": 8800},
        {"age_group": "70+", "male": 2100, "female": 3400, "total": 5500},
    ]
    return jsonify(ok_response(data, total=sum(d["total"] for d in data)))

@app.route('/api/v1/disease/region-diff', methods=['GET'])
def mock_region_diff():
    level = request.args.get('level', 'service_area')
    if level == "facility":
        data = [{"key": "Montefiore Medical Center", "value": 1200, "count": 1200},
                {"key": "NewYork-Presbyterian", "value": 980, "count": 980},
                {"key": "Mount Sinai Hospital", "value": 760, "count": 760}]
    else:
        data = [{"key": "New York City", "value": 8000, "count": 8000},
                {"key": "Long Island", "value": 3500, "count": 3500},
                {"key": "Hudson Valley", "value": 2500, "count": 2500}]
    return jsonify(ok_response(data, total=sum(d["value"] for d in data)))

@app.route('/api/v1/disease/heatmap', methods=['GET'])
def mock_heatmap():
    dim1 = request.args.get('dim1', 'diagnosis')
    dim2 = request.args.get('dim2', 'age_group')
    diags = ["肺炎", "心衰", "COPD"]
    ages = ["0-17", "18-29", "30-49", "50-69", "70+"]
    data = []
    for i, d in enumerate(diags):
        for j, a in enumerate(ages):
            data.append({
                "dim1": d, "dim1_name": d,
                "dim2": a, "dim2_name": a,
                "value": random.randint(20, 200),
                "count": random.randint(20, 200)
            })
    return jsonify(ok_response(data, total=sum(d["value"] for d in data)))

# ==================== 支付分析接口（6 个） ====================

@app.route('/api/v1/payment/composition', methods=['GET'])
def mock_payment_composition():
    group = request.args.get('group', 'payment1')
    data = [
        {"key": "Medicare", "value": 45000, "count": 45000, "pct": 45.0},
        {"key": "Medicaid", "value": 30000, "count": 30000, "pct": 30.0},
        {"key": "Private Health Insurance", "value": 20000, "count": 20000, "pct": 20.0},
        {"key": "Self-Pay", "value": 5000, "count": 5000, "pct": 5.0},
    ]
    return jsonify(ok_response(data, total=100000))

@app.route('/api/v1/payment/cross', methods=['GET'])
def mock_payment_cross():
    dim2 = request.args.get('dim2', 'age_group')
    payments = ["Medicare", "Medicaid", "Private", "Self-Pay"]
    ages = ["0-17", "18-29", "30-49", "50-69", "70+"]
    data = []
    for p in payments:
        for a in ages:
            data.append({"key": p, "dim2": a, "dim2_name": a, "value": random.randint(100, 800), "count": random.randint(100, 800)})
    return jsonify(ok_response(data, total=sum(d["value"] for d in data)))

@app.route('/api/v1/payment/sankey', methods=['GET'])
def mock_sankey():
    # 节点必须带 layer 前缀（P4 会去掉前缀展示）
    nodes = [
        {"name": "layer0|Medicare", "display": "Medicare", "layer_index": 0},
        {"name": "layer0|Medicaid", "display": "Medicaid", "layer_index": 0},
        {"name": "layer0|Private", "display": "Private", "layer_index": 0},
        {"name": "layer1|Hospital A", "display": "Hospital A", "layer_index": 1},
        {"name": "layer1|Hospital B", "display": "Hospital B", "layer_index": 1},
        {"name": "layer2|DRG 137", "display": "DRG 137", "layer_index": 2},
        {"name": "layer2|DRG 194", "display": "DRG 194", "layer_index": 2},
    ]
    links = [
        {"source": "layer0|Medicare", "target": "layer1|Hospital A", "value": 25000},
        {"source": "layer0|Medicare", "target": "layer1|Hospital B", "value": 20000},
        {"source": "layer0|Medicaid", "target": "layer1|Hospital A", "value": 18000},
        {"source": "layer0|Private", "target": "layer1|Hospital B", "value": 12000},
        {"source": "layer1|Hospital A", "target": "layer2|DRG 137", "value": 15000},
        {"source": "layer1|Hospital A", "target": "layer2|DRG 194", "value": 10000},
        {"source": "layer1|Hospital B", "target": "layer2|DRG 137", "value": 8000},
    ]
    return jsonify({
        "data": {"nodes": nodes, "links": links},
        "meta": {"total_records": 50000, "query_ms": 12, "levels": "payment,payment2,payment3", "null_excluded": 5000}
    })

@app.route('/api/v1/payment/cost-relation', methods=['GET'])
def mock_cost_relation():
    by = request.args.get('by', 'payment')
    items = [
        {"key": "Medicare", "avg_costs": 8000, "avg_charges": 12000, "count": 45000, "charge_cost_ratio": 1.5},
        {"key": "Medicaid", "avg_costs": 7000, "avg_charges": 9000, "count": 30000, "charge_cost_ratio": 1.29},
        {"key": "Private", "avg_costs": 10000, "avg_charges": 18000, "count": 20000, "charge_cost_ratio": 1.8},
        {"key": "Self-Pay", "avg_costs": 5000, "avg_charges": 5500, "count": 5000, "charge_cost_ratio": 1.1},
    ]
    return jsonify(ok_response(items, total=100000))

@app.route('/api/v1/payment/oop-burden', methods=['GET'])
def mock_oop_burden():
    dimension = request.args.get('dimension', 'disease')
    mode = request.args.get('mode', 'selfpay1')
    data = [
        {"key": "肺炎", "self_pay_count": 350, "self_pay_pct": 12.5, "self_pay_avg_charges": 3500, "self_pay_share_of_charges": 8.2},
        {"key": "心力衰竭", "self_pay_count": 280, "self_pay_pct": 10.8, "self_pay_avg_charges": 4200, "self_pay_share_of_charges": 7.1},
        {"key": "COPD", "self_pay_count": 210, "self_pay_pct": 9.2, "self_pay_avg_charges": 2800, "self_pay_share_of_charges": 5.8},
        {"key": "急性心肌梗死", "self_pay_count": 150, "self_pay_pct": 8.5, "self_pay_avg_charges": 5600, "self_pay_share_of_charges": 4.3},
    ]
    return jsonify(ok_response(data, total=sum(d["self_pay_count"] for d in data)))

@app.route('/api/v1/payment/summary', methods=['GET'])
def mock_payment_summary():
    data = {
        "total_records": 100000,
        "total_charges": 120000000,
        "total_costs": 95000000,
        "avg_charges": 1200.00,
        "avg_costs": 950.00,
        "avg_los": 4.8,
        "self_pay_count": 5000,
        "self_pay_pct": 5.0,
        "top_payment": {"key": "Medicare", "pct": 45.0},
        "severity_distribution": {"Minor": 35000, "Moderate": 30000, "Major": 20000, "Extreme": 15000},
        "ed_count": 28000,
    }
    return jsonify(ok_response(data, total=100000))

# ==================== 健康检查 ====================
@app.route('/api/v1/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "mock": True, "version": "v2_support_13_endpoints"})

if __name__ == '__main__':
    print("🚀 P3 Mock 服务启动（支持新版 13 个接口）")
    print("   监听地址：http://127.0.0.1:5000/api/v1")
    print("   可用端点：/disease/* (7个) + /payment/* (6个)")
    print("   按 Ctrl+C 停止")
    app.run(host='0.0.0.0', port=5000, debug=True)