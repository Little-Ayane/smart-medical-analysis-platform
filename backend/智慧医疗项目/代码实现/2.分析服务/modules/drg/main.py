"""
DRG分析功能 - 独立入口
支持DRG费用排名、住院天数对比、死亡风险对比、CMI排名、离群识别
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import sys
import os

# 导入路径引导：本服务目录（平级 import drg/agg_api）+ 共享底座 fastapi_common
# 支持两种启动方式：cd modules/drg && python main.py 或 从分析服务根 uvicorn modules.drg.main:app
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_here)), "fastapi_common"))

from drg import router as drg_router
from agg_api import router as agg_router
from database import app_config

# 创建FastAPI应用
app = FastAPI(
    title="DRG分析功能",
    description="DRG费用排名、住院天数对比、死亡风险对比、CMI排名、离群识别",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(drg_router)
app.include_router(agg_router)


# 根路由
@app.get("/")
async def root():
    """根路由"""
    return {
        "module": "DRG分析功能",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefix": "/api/v1/drg"
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
