# -*- coding: utf-8 -*-
"""手术谱排行（柱状图）：GET /api/v1/disease/top-procedures
口径：仅 procedure_id 非空的 1,500,426 条（meta.total_records）。
"""
from flask import request

from .._shared import _endpoint, _top_by_dim, disease_bp


@disease_bp.route("/top-procedures")
def top_procedures():
    def handler(args):
        return _top_by_dim("procedure_id", "dim_ccsr_procedure", "procedure_id",
                           args, "ccsr_procedure",
                           ("count", "total_charges", "avg_charges"))
    return _endpoint("top-procedures", request.args, handler)
