"""
FastAPI应用入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.core.analysis import router as analysis_router
from src.drg.drg import router as drg_router
from config.database import app_config

# 创建FastAPI应用
app = FastAPI(
    title="智慧医疗数据分析平台",
    description="提供核心分析功能和DRG分析功能",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(analysis_router)  # 核心分析功能
app.include_router(drg_router)       # DRG分析功能


# 根路由
@app.get("/")
async def root():
    """根路由"""
    return {
        "message": "智慧医疗数据分析平台 API",
        "version": "1.0.0",
        "docs": "/docs",
        "api_prefixes": {
            "core_analysis": "/api/v1/analysis",
            "drg_analysis": "/api/v1/drg"
        }
    }


# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print("=" * 50)
    print("智慧医疗数据分析平台启动中...")
    print(f"API文档: http://localhost:{app_config.port}/docs")
    print("核心分析API: /api/v1/analysis")
    print("DRG分析API: /api/v1/drg")
    print("=" * 50)


# 关闭事件
@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    print("智慧医疗数据分析平台已关闭")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=app_config.host,
        port=app_config.port,
        reload=app_config.debug,
        workers=app_config.workers
    )
