"""
聚合结果API路由
查询预聚合表，毫秒级响应
"""
from fastapi import APIRouter, Query
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agg_service import agg_service

router = APIRouter(prefix="/api/v1/agg", tags=["聚合结果查询"])


@router.get("/drg/ranking")
async def drg_ranking(
    limit: int = Query(20, ge=1, le=500),
    sort_by: str = Query("cases", pattern="^(cases|avg_charges|total_charges|avg_stay|avg_costs)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$")
):
    """DRG费用排名"""
    return agg_service.get_drg_ranking(limit, sort_by, sort_order)


@router.get("/hospital/stats")
async def hospital_stats(
    limit: int = Query(20, ge=1, le=500),
    sort_by: str = Query("cases", pattern="^(cases|avg_charges|total_charges|avg_stay|mortality_rate)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$")
):
    """医院统计"""
    return agg_service.get_hospital_stats(limit, sort_by, sort_order)


@router.get("/diagnosis/stats")
async def diagnosis_stats(
    limit: int = Query(20, ge=1, le=500),
    sort_by: str = Query("cases", pattern="^(cases|avg_charges|total_charges|avg_stay)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$")
):
    """诊断统计"""
    return agg_service.get_diagnosis_stats(limit, sort_by, sort_order)


@router.get("/mortality/risk")
async def mortality_risk():
    """死亡风险分布"""
    return agg_service.get_mortality_risk()


@router.get("/severity/stats")
async def severity_stats():
    """严重程度分布"""
    return agg_service.get_severity_stats()


@router.get("/yearly/trend")
async def yearly_trend():
    """年度趋势"""
    return agg_service.get_yearly_trend()


@router.get("/age/distribution")
async def age_distribution():
    """年龄分布"""
    return agg_service.get_age_distribution()


@router.get("/payment/stats")
async def payment_stats():
    """支付方式分布"""
    return agg_service.get_payment_stats()


@router.get("/summary")
async def summary():
    """数据总览"""
    return agg_service.get_summary()
