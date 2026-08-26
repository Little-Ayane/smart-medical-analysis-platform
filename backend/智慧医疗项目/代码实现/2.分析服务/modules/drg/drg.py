"""
DRG分析API路由
提供DRG费用排名、住院天数对比、死亡风险对比、CMI排名、离群识别等功能
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from drg_service import drg_service

# 创建路由器
router = APIRouter(prefix="/api/v1/drg", tags=["DRG分析"])


# ==================== 请求模型 ====================

class DRGRankingRequest(BaseModel):
    """DRG费用排名请求"""
    metrics: List[str] = Field(
        default=["cases", "total_charges", "avg_charges"],
        description="指标列表"
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="筛选条件"
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="返回条数"
    )
    sort_order: str = Field(
        default="desc",
        description="排序方式 (desc/asc)"
    )


class StayComparisonRequest(BaseModel):
    """住院天数对比请求"""
    group_by: str = Field(
        default="drg",
        description="分组维度 (drg/diagnosis/severity/mdc)"
    )
    metrics: List[str] = Field(
        default=["avg_stay", "max_stay", "cases"],
        description="指标列表"
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="筛选条件"
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="返回条数"
    )


class MortalityRiskRequest(BaseModel):
    """死亡风险对比请求"""
    group_by: str = Field(
        default="risk_mortality",
        description="分组维度 (risk_mortality/severity/mdc/drg)"
    )
    metrics: List[str] = Field(
        default=["cases", "avg_charges", "avg_stay"],
        description="指标列表"
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="筛选条件"
    )


class CMIRankingRequest(BaseModel):
    """CMI排名请求"""
    group_by: str = Field(
        default="drg",
        description="分组维度 (drg/mdc/hospital)"
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="筛选条件"
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="返回条数"
    )
    sort_order: str = Field(
        default="desc",
        description="排序方式 (desc/asc)"
    )


class OutlierDetectionRequest(BaseModel):
    """离群识别请求"""
    metric: str = Field(
        default="avg_charges",
        description="检测指标 (avg_charges/avg_stay/cases)"
    )
    group_by: str = Field(
        default="drg",
        description="分组维度 (drg/diagnosis/hospital)"
    )
    method: str = Field(
        default="iqr",
        description="检测方法 (iqr/zscore)"
    )
    threshold: float = Field(
        default=1.5,
        description="阈值 (IQR倍数或Z分数)"
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="筛选条件"
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="返回条数"
    )


# ==================== 响应模型 ====================

class DRGResponse(BaseModel):
    """DRG响应通用模型"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="状态信息")
    data: Dict[str, Any] = Field(description="响应数据")


# ==================== API端点 ====================

@router.post("/cost-ranking", response_model=DRGResponse, summary="DRG费用排名")
async def drg_cost_ranking(request: DRGRankingRequest):
    """
    DRG费用排名

    按DRG分组统计费用，返回排名结果

    - **metrics**: 指标列表，默认为病例数、总费用、平均费用
    - **filters**: 筛选条件，如 {"year": 2021}
    - **limit**: 返回条数，默认20
    - **sort_order**: 排序方式，desc(降序)/asc(升序)
    """
    try:
        result = drg_service.drg_cost_ranking(
            metrics=request.metrics,
            filters=request.filters,
            limit=request.limit,
            sort_order=request.sort_order
        )
        return DRGResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/stay-comparison", response_model=DRGResponse, summary="住院天数对比")
async def stay_comparison(request: StayComparisonRequest):
    """
    住院天数对比

    按不同维度分组统计住院天数

    - **group_by**: 分组维度 (drg/diagnosis/severity/mdc)
    - **metrics**: 指标列表，默认为平均住院天数、最大住院天数、病例数
    - **filters**: 筛选条件
    - **limit**: 返回条数
    """
    try:
        result = drg_service.stay_comparison(
            group_by=request.group_by,
            metrics=request.metrics,
            filters=request.filters,
            limit=request.limit
        )
        return DRGResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/mortality-risk", response_model=DRGResponse, summary="死亡风险对比")
async def mortality_risk_comparison(request: MortalityRiskRequest):
    """
    死亡风险对比

    按死亡风险等级统计分析

    - **group_by**: 分组维度 (risk_mortality/severity/mdc/drg)
    - **metrics**: 指标列表，默认为病例数、平均费用、平均住院天数
    - **filters**: 筛选条件
    """
    try:
        result = drg_service.mortality_risk_comparison(
            group_by=request.group_by,
            metrics=request.metrics,
            filters=request.filters
        )
        return DRGResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/cmi-ranking", response_model=DRGResponse, summary="CMI排名")
async def cmi_ranking(request: CMIRankingRequest):
    """
    CMI排名 (Case Mix Index - 病例组合指数)

    计算并展示各分组的CMI值

    - **group_by**: 分组维度 (drg/mdc/hospital)
    - **filters**: 筛选条件
    - **limit**: 返回条数
    - **sort_order**: 排序方式
    """
    try:
        result = drg_service.cmi_ranking(
            group_by=request.group_by,
            filters=request.filters,
            limit=request.limit,
            sort_order=request.sort_order
        )
        return DRGResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/outlier-detection", response_model=DRGResponse, summary="离群识别")
async def outlier_detection(request: OutlierDetectionRequest):
    """
    离群识别

    识别费用/住院天数异常的病例

    - **metric**: 检测指标 (avg_charges/avg_stay/cases)
    - **group_by**: 分组维度 (drg/diagnosis/hospital)
    - **method**: 检测方法 (iqr/zscore)
    - **threshold**: 阈值 (IQR倍数或Z分数)
    - **filters**: 筛选条件
    - **limit**: 返回条数
    """
    try:
        result = drg_service.outlier_detection(
            metric=request.metric,
            group_by=request.group_by,
            method=request.method,
            threshold=request.threshold,
            filters=request.filters,
            limit=request.limit
        )
        return DRGResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.get("/summary", response_model=DRGResponse, summary="DRG汇总信息")
async def drg_summary(filters: Optional[Dict[str, Any]] = None):
    """
    获取DRG汇总信息

    返回DRG相关的汇总统计数据，包括：
    - 总DRG数
    - 总病例数
    - 总费用
    - 平均住院天数
    - 死亡风险分布
    - 严重程度分布
    """
    try:
        result = drg_service.get_drg_summary(filters=filters)
        return DRGResponse(code=200, message="success", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.get("/health", summary="DRG服务健康检查")
async def health_check():
    """DRG服务健康检查"""
    try:
        from mysql_dao import mysql_dao
        db_status = "healthy" if mysql_dao.test_connection() else "unhealthy"

        return {
            "status": "healthy" if db_status == "healthy" else "degraded",
            "database": db_status,
            "service": "drg-analysis"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "service": "drg-analysis"
        }
