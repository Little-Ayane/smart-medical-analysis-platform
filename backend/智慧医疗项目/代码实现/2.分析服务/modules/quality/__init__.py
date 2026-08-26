# -*- coding: utf-8 -*-
"""模块四 · 医疗质量监测（前缀 /api/v1/quality）。

每个小功能一个独立子文件夹（子文件夹内 view.py 导入即注册路由）：
    overview         质量总览 KPI（大屏首页卡片）
    mortality        死亡率分析（诊断/医院/年龄/严重程度/死亡风险分组，按死亡率排行）
    length_of_stay   平均住院日分析（分组排行，附次均费用/成本）
    facility_ranking 医院质量横向对比（出院量 ≥ min_cases 的医院多指标排行）
    disposition      离院去向构成（Home/Expired/AMA/转院/Hospice/SNF 等，饼图）
口径声明：再入院率、院内感染率因数据无患者唯一标识/无感染字段无法计算，见接口文档。
"""
from ._shared import quality_bp
from . import (disposition, facility_ranking, length_of_stay, mortality, overview)

__all__ = ["quality_bp"]
