# -*- coding: utf-8 -*-
"""模块二 · 支付分析（前缀 /api/v1/payment）。

每个小功能一个独立子文件夹（子文件夹内 view.py 导入即注册路由）：
    composition   支付构成（饼图；payment1/2/3 三层可选，NULL 组排除并回显）
    cross         支付交叉：支付方式 × 年龄段/病种/严重程度（堆叠柱 / 热力）
    sankey        桑葚图（levels 硬编码白名单；节点名带层前缀保证全局唯一）
    cost_relation 支付费用关系（散点图：avg_charges vs avg_costs，气泡 = 记录数）
    oop_burden    自付负担（双口径：selfpay1 全额自费有真实金额 / any_layer 仅占比）
    summary       KPI 总览（大屏首页卡片）
口径说明：
    - Self-Pay 在支付 1/2/3 层均有出现（26,310 / 153,374 / 198,359 条），
      selfpay1 口径 = 支付方式1为 Self-Pay（全额自费，有真实费用）；
      any_layer 口径 = 任一层为 Self-Pay（保险自付部分，无法从本数据推断金额，仅给占比）。
"""
from ._shared import payment_bp
from . import (composition, cost_relation, cross, oop_burden, sankey, summary)

__all__ = ["payment_bp"]
