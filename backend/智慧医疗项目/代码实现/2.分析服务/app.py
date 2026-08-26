# -*- coding: utf-8 -*-
"""
P3 · 大数据分析服务模块（唯一入口，仅做组装）
技术：Flask / PyMySQL / 进程内 TTL 缓存
运行：python app.py  ->  http://127.0.0.1:5000
蓝图：
    modules.disease   模块一 · 病种与手术分析（/api/v1/disease）
    modules.payment   模块二 · 支付分析（/api/v1/payment）
    modules.cost      费用成本分析（/api/v1/cost，register_cost_routes 注册）
    modules.emergency 急诊与住院分析（/api/v1/analysis/*，register_emergency_routes 注册，medical_db）
    modules.quality   模块四 · 医疗质量监测（/api/v1/quality）
    meta              维度字典（/api/v1/meta）
    legacy            遗留接口（/api/v1/health、/api/v1/analysis/*，P4 兼容）
另有独立 FastAPI 服务 modules/core（端口 8000）与 modules/drg（端口 8001），
共享底座在 fastapi_common/，与主服务互不依赖。
注意：进程内缓存依赖单进程模型，请勿用 debug=True（reloader 双进程会让缓存各自为政）。
"""
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from common import apply_json_provider, error
from modules.disease import disease_bp
from modules.legacy import legacy_bp
from modules.meta import meta_bp
from modules.payment import payment_bp
from modules.quality import quality_bp

app = Flask(__name__)
apply_json_provider(app)
app.register_blueprint(disease_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(quality_bp)
app.register_blueprint(meta_bp)
app.register_blueprint(legacy_bp)


# ------------------------------------------------------------
# CORS（前端跨域直连，无需 flask-cors）
# ------------------------------------------------------------
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ------------------------------------------------------------
# 全局异常兜底（统一信封，不抛裸异常）
# ------------------------------------------------------------
@app.errorhandler(HTTPException)
def on_http_exception(e):
    return error(e.code if e.code < 500 else 500, e.name)


@app.errorhandler(Exception)
def on_unhandled(e):
    app.logger.exception("未处理异常: %s", request.path)
    return error(500, "服务内部错误")


# ===== 注册纪志鹏的费用成本路由（modules/cost）=====
from modules.cost import register_cost_routes
register_cost_routes(app)

# ===== 注册骆志远的急诊与住院分析路由（modules/emergency）=====
from modules.emergency import register_emergency_routes
register_emergency_routes(app)

# ===== 注册 3D 大屏预聚合路由（modules/bigscreen）=====
from modules.bigscreen import register_bigscreen_routes
register_bigscreen_routes(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
