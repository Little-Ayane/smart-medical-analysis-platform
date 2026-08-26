# -*- coding: utf-8 -*-
"""P3 分析服务模块包：
    disease  模块一 · 病种与手术分析（/api/v1/disease）
    payment  模块二 · 支付分析（/api/v1/payment）
    cost     费用成本分析（/api/v1/cost，register_cost_routes 注册）
    quality  模块四 · 医疗质量监测（/api/v1/quality）
    drg      DRG 分析（独立 FastAPI 服务，端口 8001，见 modules/drg/main.py）
    core     核心分析（独立 FastAPI 服务，端口 8000，见 modules/core/main.py）
公共底座（信封/缓存/过滤）与服务层文件位于上一级目录：
    common.py / meta.py / legacy.py / app.py，FastAPI 共享底座在 fastapi_common/。
"""
