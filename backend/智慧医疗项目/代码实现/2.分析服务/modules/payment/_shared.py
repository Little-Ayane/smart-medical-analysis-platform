# -*- coding: utf-8 -*-
"""模块二 · 模块内公用：蓝图、统一异常包装。"""
from flask import Blueprint, current_app

from common import BadRequest, error, set_database

payment_bp = Blueprint("payment", __name__, url_prefix="/api/v1/payment")


@payment_bp.before_request
def _use_medical_db():
    """试点：支付模块查询 medical_db（1000万/2020-2024）而非 smart_health。"""
    set_database("medical_db")


@payment_bp.teardown_request
def _clear_db(exc):
    set_database(None)


def _endpoint(path, args, handler):
    try:
        return handler(args)
    except BadRequest as e:
        return error(400, str(e))
    except Exception:
        current_app.logger.exception("[payment/%s] 处理异常", path)
        return error(500, "服务内部错误")
