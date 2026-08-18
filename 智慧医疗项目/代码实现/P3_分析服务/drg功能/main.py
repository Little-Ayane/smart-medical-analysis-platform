"""
DRG分析功能 - 独立入口
支持DRG费用排名、住院天数对比、死亡风险对比、CMI排名、离群识别
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drg import router as drg_router
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


# 根路由
@app.get("/")
async def root():
    """根路由"""
    return {
        "module": "DRG分析功能",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefix": "/api/v1/drg",
        "endpoints": [
            "POST /api/v1/drg/cost-ranking",
            "POST /api/v1/drg/stay-comparison",
            "POST /api/v1/drg/mortality-risk",
            "POST /api/v1/drg/cmi-ranking",
            "POST /api/v1/drg/outlier-detection",
            "GET /api/v1/drg/summary",
            "GET /api/v1/drg/health"
        ]
    }


# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print("=" * 50)
    print("DRG分析功能启动中...")
    print(f"API文档: http://localhost:{app_config.port}/docs")
    print("API前缀: /api/v1/drg")
    print("=" * 50)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=app_config.host,
        port=app_config.port,
        reload=app_config.debug,
        workers=app_config.workers
    )
