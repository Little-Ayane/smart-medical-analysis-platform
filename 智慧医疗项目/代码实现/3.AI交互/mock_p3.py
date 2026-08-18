from flask import Flask, request, jsonify
import time

app = Flask(__name__)

# 模拟聚合分析数据（对应 /analysis/aggregate）
@app.route('/api/v1/analysis/aggregate', methods=['GET'])
def aggregate():
    dimension = request.args.get('dimension', 'ccsr_diagnosis')
    metric = request.args.get('metric', 'count')
    top = int(request.args.get('top', 5))
    year = request.args.get('year')
    # 根据不同维度返回不同模拟数据（你可以扩展）
    if dimension == 'ccsr_diagnosis' and metric == 'avg_length_of_stay':
        data = [
            {"key": "肺炎", "value": 7.2, "count": 1200},
            {"key": "心力衰竭", "value": 6.8, "count": 980},
            {"key": "慢性阻塞性肺病", "value": 5.9, "count": 760},
            {"key": "急性心肌梗死", "value": 4.5, "count": 540},
            {"key": "脑卒中", "value": 3.2, "count": 430},
        ]
    elif dimension == 'payment_typology' and metric == 'payment_mix':
        data = [
            {"payment": "Medicare", "count": 45000, "pct": 45.0},
            {"payment": "Medicaid", "count": 30000, "pct": 30.0},
            {"payment": "Private Health Insurance", "count": 20000, "pct": 20.0},
            {"payment": "Self Pay", "count": 5000, "pct": 5.0},
        ]
    else:
        data = [{"key": f"类别{i}", "value": i*10} for i in range(1, top+1)]
    return jsonify({
        "data": data[:top],
        "meta": {
            "total_records": 100000,
            "query_ms": 15,
            "dimension": dimension,
            "metric": metric
        }
    })

# 模拟支付占比接口
@app.route('/api/v1/analysis/payment-mix', methods=['GET'])
def payment_mix():
    return jsonify({
        "data": [
            {"payment": "Medicare", "count": 45000, "pct": 45.0},
            {"payment": "Medicaid", "count": 30000, "pct": 30.0},
            {"payment": "Private Health Insurance", "count": 20000, "pct": 20.0},
            {"payment": "Self Pay", "count": 5000, "pct": 5.0}
        ],
        "meta": {"total_records": 100000, "query_ms": 10}
    })

# 模拟趋势接口
@app.route('/api/v1/analysis/trend', methods=['GET'])
def trend():
    return jsonify({
        "data": [
            {"year": 2018, "count": 80000},
            {"year": 2019, "count": 85000},
            {"year": 2020, "count": 95000},
            {"year": 2021, "count": 110000}
        ],
        "meta": {"total_records": 370000, "query_ms": 8}
    })

@app.route('/api/v1/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)