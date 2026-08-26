"""
核心分析功能 - 独立入口
支持维度组合选择、指标切换、逐级下钻、时间上卷、交叉透视
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import sys
import os

# 导入路径引导：本服务目录（平级 import analysis/agg_api）+ 共享底座 fastapi_common
# 支持两种启动方式：cd modules/core && python main.py 或 从分析服务根 uvicorn modules.core.main:app
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_here)), "fastapi_common"))

from analysis import router as analysis_router
from agg_api import router as agg_router
from database import app_config

# 创建FastAPI应用
app = FastAPI(
    title="核心分析功能",
    description="维度组合选择、指标切换、逐级下钻、时间上卷、交叉透视",
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
app.include_router(analysis_router)
app.include_router(agg_router)


# 根路由
@app.get("/")
async def root():
    """根路由"""
    return {
        "module": "核心分析功能",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefix": "/api/v1/analysis"
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
