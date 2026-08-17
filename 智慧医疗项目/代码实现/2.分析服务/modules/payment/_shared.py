# -*- coding: utf-8 -*-
"""模块二 · 模块内公用：蓝图、统一异常包装。"""
from flask import Blueprint, current_app

from common import BadRequest, error

payment_bp = Blueprint("payment", __name__, url_prefix="/api/v1/payment")


def _endpoint(path, args, handler):
    try:
        return handler(args)
    except BadRequest as e:
        return error(400, str(e))
    except Exception:
        current_app.logger.exception("[payment/%s] 处理异常", path)
        return error(500, "服务内部错误")
