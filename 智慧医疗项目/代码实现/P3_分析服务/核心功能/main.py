"""
核心分析功能 - 独立入口
支持维度组合选择、指标切换、逐级下钻、时间上卷、交叉透视
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import router as analysis_router
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


# 根路由
@app.get("/")
async def root():
    """根路由"""
    return {
        "module": "核心分析功能",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefix": "/api/v1/analysis",
        "endpoints": [
            "POST /api/v1/analysis/dimension-combine",
            "POST /api/v1/analysis/metric-switch",
            "POST /api/v1/analysis/drill-down",
            "POST /api/v1/analysis/time-rollup",
            "POST /api/v1/analysis/pivot",
            "POST /api/v1/analysis/summary",
            "GET /api/v1/analysis/metadata",
            "GET /api/v1/analysis/health"
        ]
    }


# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print("=" * 50)
    print("核心分析功能启动中...")
    print(f"API文档: http://localhost:{app_config.port}/docs")
    print("API前缀: /api/v1/analysis")
    print("=" * 50)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=app_config.host,
        port=app_config.port,
        reload=app_config.debug,
        workers=app_config.workers
    )
