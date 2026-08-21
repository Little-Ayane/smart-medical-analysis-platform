"""
分析API路由
提供维度组合选择、指标切换、逐级下钻、时间上卷、交叉透视五大核心接口
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from analysis_service import analysis_service

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


# ==================== 请求模型 ====================

class DimensionCombineRequest(BaseModel):
    """维度组合选择请求"""
    dimensions: List[str] = Field(..., description="维度列表", min_length=1)
    metrics: List[str] = Field(..., description="指标列表", min_length=1)
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")
    sort: Optional[Dict[str, str]] = Field(default=None, description="排序配置")
    limit: Optional[int] = Field(default=100, description="返回条数", ge=1, le=10000)


class MetricSwitchRequest(BaseModel):
    """指标切换请求"""
    dimensions: List[str] = Field(..., description="维度列表", min_length=1)
    metric_groups: Dict[str, List[str]] = Field(..., description="指标组")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")


class DrillDownRequest(BaseModel):
    """逐级下钻请求"""
    current_level: str = Field(..., description="当前层级")
    current_value: Any = Field(..., description="当前值")
    drill_to: str = Field(..., description="下钻目标层级")
    metrics: List[str] = Field(..., description="指标列表", min_length=1)
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")


class TimeRollupRequest(BaseModel):
    """时间上卷请求"""
    time_level: str = Field(default="year", description="时间层级", pattern="^(year|quarter|month)$")
    metrics: List[str] = Field(..., description="指标列表", min_length=1)
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")
    compare_previous: bool = Field(default=False, description="是否与上期对比")


class PivotRequest(BaseModel):
    """交叉透视请求"""
    row_dimension: str = Field(..., description="行维度")
    col_dimension: str = Field(..., description="列维度")
    metric: str = Field(..., description="指标")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")


class SummaryRequest(BaseModel):
    """汇总统计请求"""
    metrics: List[str] = Field(..., description="指标列表", min_length=1)
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")


# ==================== 响应模型 ====================

class ApiResponse(BaseModel):
    """统一响应模型"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="消息")
    data: Any = Field(default=None, description="数据")


# ==================== API端点 ====================

@router.post("/dimension-combine", response_model=ApiResponse)
async def dimension_combine(request: DimensionCombineRequest):
    """
    维度组合选择

    支持任意维度组合分析，返回聚合结果
    """
    try:
        result = analysis_service.dimension_combine(
            dimensions=request.dimensions,
            metrics=request.metrics,
            filters=request.filters,
            sort=request.sort,
            limit=request.limit
        )
        return ApiResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/metric-switch", response_model=ApiResponse)
async def metric_switch(request: MetricSwitchRequest):
    """
    指标切换

    同一维度组合下，快速切换不同指标组
    """
    try:
        result = analysis_service.metric_switch(
            dimensions=request.dimensions,
            metric_groups=request.metric_groups,
            filters=request.filters
        )
        return ApiResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/drill-down", response_model=ApiResponse)
async def drill_down(request: DrillDownRequest):
    """
    逐级下钻

    从汇总数据逐层深入到明细
    """
    try:
        result = analysis_service.drill_down(
            current_level=request.current_level,
            current_value=request.current_value,
            drill_to=request.drill_to,
            metrics=request.metrics,
            filters=request.filters
        )
        return ApiResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/time-rollup", response_model=ApiResponse)
async def time_rollup(request: TimeRollupRequest):
    """
    时间上卷

    按时间维度聚合，支持月→季→年的上卷
    """
    try:
        result = analysis_service.time_rollup(
            time_level=request.time_level,
            metrics=request.metrics,
            filters=request.filters,
            compare_previous=request.compare_previous
        )
        return ApiResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/pivot", response_model=ApiResponse)
async def pivot(request: PivotRequest):
    """
    交叉透视

    多维度交叉分析，生成透视表
    """
    try:
        result = analysis_service.pivot(
            row_dimension=request.row_dimension,
            col_dimension=request.col_dimension,
            metric=request.metric,
            filters=request.filters
        )
        return ApiResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/summary", response_model=ApiResponse)
async def summary(request: SummaryRequest):
    """
    汇总统计

    返回指定指标的均值、总和、最小值、最大值等
    """
    try:
        result = analysis_service.summary(
            metrics=request.metrics,
            filters=request.filters
        )
        return ApiResponse(code=200, message="success", data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.get("/metadata", response_model=ApiResponse)
async def get_metadata():
    """
    获取元数据

    返回所有可用的维度和指标信息
    """
    try:
        result = analysis_service.get_metadata()
        return ApiResponse(code=200, message="success", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.get("/health", response_model=ApiResponse)
async def health_check():
    """
    健康检查

    检查服务和数据库状态
    """
    try:
        result = analysis_service.health_check()
        return ApiResponse(code=200, message="success", data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")
