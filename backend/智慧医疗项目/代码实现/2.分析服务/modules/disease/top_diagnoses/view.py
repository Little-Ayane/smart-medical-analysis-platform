# -*- coding: utf-8 -*-
"""Top 诊断排行（柱状图 / 词云）：GET /api/v1/disease/top-diagnoses
metric ∈ count/total_charges/avg_charges/avg_los；返回 {code,name,count,value}。
"""
from flask import request

from .._shared import _endpoint, _top_by_dim, disease_bp


@disease_bp.route("/top-diagnoses")
def top_diagnoses():
    def handler(args):
        return _top_by_dim("diagnosis_id", "dim_ccsr_diagnosis", "diagnosis_id",
                           args, "ccsr_diagnosis",
                           ("count", "total_charges", "avg_charges", "avg_los"))
    return _endpoint("top-diagnoses", request.args, handler)
