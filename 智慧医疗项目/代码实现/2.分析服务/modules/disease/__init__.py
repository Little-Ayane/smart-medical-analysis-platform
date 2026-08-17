# -*- coding: utf-8 -*-
"""模块一 · 病种与手术分析（前缀 /api/v1/disease）。

每个小功能一个独立子文件夹（子文件夹内 view.py 导入即注册路由）：
    top_diagnoses    Top 诊断排行（柱状图 / 词云）
    top_procedures   手术谱排行（柱状图）
    severity_profile 病重趋势：分组 × 严重程度构成（堆叠柱；数据仅 2021 年，无时间趋势）
    population_diff  人群差异（分组柱状）
    pyramid          人口金字塔（性别 × 年龄段，专用结构）
    region_diff      地区差异（service_area / county / facility 三级）
    heatmap          通用热力图（白名单 dim1 × dim2，topN 先行防全量爆表）
"""
from ._shared import disease_bp
from . import (heatmap, population_diff, pyramid, region_diff, severity_profile,
               top_diagnoses, top_procedures)

__all__ = ["disease_bp"]
