# -*- coding: utf-8 -*-
"""P3 调用容错加固单元测试（不依赖真实 LLM / P3 服务）。

验证 agent.py 对 P3 接口异常的健壮性（核心目标：P3 出问题时返回结构化错误体
+ 友好提示，而不是把异常抛到 Flask 层变成 500）：

  1. _make_p3_error / _is_p3_logical_error 辅助函数
  2. _call_p3_api（Agent 路径）：超时 / 连接失败 / 非JSON / 业务错误信封 / 成功 / 重试
  3. call_analysis_api（旧管道）：同样六类场景，验证返回错误体而非抛异常
  4. _finalize_result：错误体产出友好 answer；空 data 仍提示"未查询到"

用法：python test_fault_tolerance.py
"""
import json
import os
import sys
from unittest import mock

import agent


# 默认关闭重试，保证单测确定；重试场景在用例内临时开启
os.environ.setdefault("P3_API_RETRIES", "0")
# 关闭 LLM，避免测试触发真实网络调用（LLM 路径与本次容错无关）
agent.LLM_ENABLED = False


class FakeResp:
    """可配置的伪响应对象。"""
    def __init__(self, status=200, payload=None, raise_on_json=False,
                 raise_on_status=None):
        self.status_code = status
        self._payload = payload
        self._raise_on_json = raise_on_json
        self._raise_on_status = raise_on_status

    def raise_for_status(self):
        if self._raise_on_status is not None:
            raise self._raise_on_status

    def json(self):
        if self._raise_on_json:
            raise ValueError("No JSON object could be decoded")
        return self._payload


def _timeout():
    return agent.requests.exceptions.Timeout("timed out")


def _connerr():
    return agent.requests.exceptions.ConnectionError("refused")


# ============ 1. 辅助函数 ============
def test_make_p3_error():
    failed = 0
    r = agent._make_p3_error("top_diagnoses", "timeout")
    ok = (r.get("error") == "timeout"
          and r.get("data") == []
          and r.get("meta", {}).get("chart_hint") == "top_diagnoses")
    if not ok:
        print(f"[FAIL] _make_p3_error 结构异常: {r!r}")
        failed += 1
    else:
        print("[PASS] _make_p3_error 结构正确")

    r2 = agent._make_p3_error(None, "connection_failed", "detail-xyz")
    if r2.get("meta", {}).get("chart_hint") is not None \
            or r2.get("meta", {}).get("error_detail") != "detail-xyz":
        print(f"[FAIL] _make_p3_error detail/chart_hint 异常: {r2!r}")
        failed += 1
    else:
        print("[PASS] _make_p3_error 支持 detail + chart_hint=None")
    return failed


def test_is_p3_logical_error():
    failed = 0
    cases = [
        ({"error": "x"}, True, "含 error 键"),
        ({"success": False}, True, "success=false"),
        ({"code": 1}, True, "code=1"),
        ({"code": 0}, False, "code=0 视为成功"),
        ({"data": []}, False, "仅 data 空不算业务错误"),
        ({"message": "x"}, False, "仅 message 不算"),
        ("not dict", False, "非 dict"),
        (None, False, "None"),
    ]
    for payload, expected, desc in cases:
        actual = agent._is_p3_logical_error(payload)
        if actual != expected:
            print(f"[FAIL] _is_p3_logical_error: {desc} -> {actual}")
            failed += 1
        else:
            print(f"[PASS] _is_p3_logical_error: {desc}")
    return failed


# ============ 2. _call_p3_api（Agent 路径）============
def test_call_p3_api_timeout():
    failed = 0
    with mock.patch("agent.requests.get", side_effect=_timeout()):
        r = agent._call_p3_api("top_diagnoses",
                               "/disease/top-diagnoses", {"metric": "count"})
    if r.get("error") != "timeout":
        print(f"[FAIL] _call_p3_api 超时未返回 timeout: {r!r}")
        failed += 1
    else:
        print("[PASS] _call_p3_api 超时 -> {error:timeout}")
    return failed


def test_call_p3_api_connerr():
    failed = 0
    with mock.patch("agent.requests.get", side_effect=_connerr()):
        r = agent._call_p3_api("top_diagnoses",
                               "/disease/top-diagnoses", {"metric": "count"})
    if r.get("error") != "connection_failed":
        print(f"[FAIL] _call_p3_api 连接失败未返回 connection_failed: {r!r}")
        failed += 1
    else:
        print("[PASS] _call_p3_api 连接失败 -> {error:connection_failed}")
    return failed


def test_call_p3_api_nonjson():
    failed = 0
    with mock.patch("agent.requests.get",
                    return_value=FakeResp(200, raise_on_json=True)):
        r = agent._call_p3_api("top_diagnoses",
                               "/disease/top-diagnoses", {"metric": "count"})
    if r.get("error") != "invalid_response":
        print(f"[FAIL] _call_p3_api 非JSON未返回 invalid_response: {r!r}")
        failed += 1
    else:
        print("[PASS] _call_p3_api 非JSON -> {error:invalid_response}")
    return failed


def test_call_p3_api_business_error():
    failed = 0
    with mock.patch("agent.requests.get",
                    return_value=FakeResp(200, {"code": 1,
                                                "message": "db down"})):
        r = agent._call_p3_api("top_diagnoses",
                               "/disease/top-diagnoses", {"metric": "count"})
    if r.get("error") != "p3_error":
        print(f"[FAIL] _call_p3_api 业务错误未返回 p3_error: {r!r}")
        failed += 1
    else:
        print("[PASS] _call_p3_api 业务错误信封 -> {error:p3_error}")
    return failed


def test_call_p3_api_success():
    failed = 0
    payload = {"data": [{"name": "A", "value": 1}],
               "meta": {"total_records": 1}}
    with mock.patch("agent.requests.get",
                    return_value=FakeResp(200, payload)):
        r = agent._call_p3_api("top_diagnoses",
                               "/disease/top-diagnoses", {"metric": "count"})
    if r.get("error") is not None or r.get("data") != payload["data"] \
            or r.get("meta", {}).get("chart_hint") != "top_diagnoses":
        print(f"[FAIL] _call_p3_api 成功路径异常: {r!r}")
        failed += 1
    else:
        print("[PASS] _call_p3_api 成功 -> data + meta.chart_hint")
    return failed


def test_call_p3_api_retry():
    failed = 0
    old = os.environ.get("P3_API_RETRIES")
    os.environ["P3_API_RETRIES"] = "1"
    try:
        with mock.patch("agent.requests.get", side_effect=_timeout()) as m:
            r = agent._call_p3_api("top_diagnoses",
                                   "/disease/top-diagnoses", {"metric": "count"})
        if r.get("error") != "timeout" or m.call_count != 2:
            print(f"[FAIL] _call_p3_api 重试异常: calls={m.call_count}, {r!r}")
            failed += 1
        else:
            print("[PASS] _call_p3_api 超时重试1次 -> 共2次调用且仍 timeout")
    finally:
        if old is None:
            os.environ.pop("P3_API_RETRIES", None)
        else:
            os.environ["P3_API_RETRIES"] = old
    return failed


# ============ 3. call_analysis_api（旧管道）============
def _legacy_intent():
    return {"chart_hint": None, "metric": "count",
            "dimension": "ccsr_diagnosis", "top": 10, "filters": {}}


def test_old_pipeline_timeout_no_raise():
    failed = 0
    try:
        with mock.patch("agent.requests.get", side_effect=_timeout()):
            r = agent.call_analysis_api(_legacy_intent(), question="测试")
        if not isinstance(r, dict) or r.get("error") != "timeout":
            print(f"[FAIL] 旧管道超时未返回错误体: {r!r}")
            failed += 1
        else:
            print("[PASS] 旧管道超时 -> 结构化错误体（未抛异常）")
    except Exception as e:  # noqa
        print(f"[FAIL] 旧管道超时抛出了未捕获异常: {type(e).__name__}: {e}")
        failed += 1
    return failed


def test_old_pipeline_connerr_no_raise():
    failed = 0
    try:
        with mock.patch("agent.requests.get", side_effect=_connerr()):
            r = agent.call_analysis_api(_legacy_intent(), question="测试")
        if not isinstance(r, dict) or r.get("error") != "connection_failed":
            print(f"[FAIL] 旧管道连接失败未返回错误体: {r!r}")
            failed += 1
        else:
            print("[PASS] 旧管道连接失败 -> 结构化错误体（未抛异常）")
    except Exception as e:  # noqa
        print(f"[FAIL] 旧管道连接失败抛出了未捕获异常: {type(e).__name__}: {e}")
        failed += 1
    return failed


def test_old_pipeline_nonjson():
    failed = 0
    with mock.patch("agent.requests.get",
                    return_value=FakeResp(200, raise_on_json=True)):
        r = agent.call_analysis_api(_legacy_intent(), question="测试")
    if r.get("error") != "invalid_response":
        print(f"[FAIL] 旧管道非JSON未返回 invalid_response: {r!r}")
        failed += 1
    else:
        print("[PASS] 旧管道非JSON -> {error:invalid_response}")
    return failed


def test_old_pipeline_business_error():
    failed = 0
    with mock.patch("agent.requests.get",
                    return_value=FakeResp(200, {"code": 1,
                                                "message": "db down"})):
        r = agent.call_analysis_api(_legacy_intent(), question="测试")
    if r.get("error") != "p3_error":
        print(f"[FAIL] 旧管道业务错误未返回 p3_error: {r!r}")
        failed += 1
    else:
        print("[PASS] 旧管道业务错误信封 -> {error:p3_error}")
    return failed


def test_old_pipeline_success():
    failed = 0
    payload = {"data": [{"name": "A", "value": 1}],
               "meta": {"total_records": 1}}
    with mock.patch("agent.requests.get",
                    return_value=FakeResp(200, payload)):
        r = agent.call_analysis_api(_legacy_intent(), question="测试")
    if r.get("error") is not None or r.get("data") != payload["data"] \
            or "chart_hint" not in r.get("meta", {}):
        print(f"[FAIL] 旧管道成功路径异常: {r!r}")
        failed += 1
    else:
        print("[PASS] 旧管道成功 -> data + meta 写入")
    return failed


def test_metric_degraded_warning_written():
    """死代码修复回归：metric 降级警告必须写入 meta.warnings。

    修复前该逻辑位于 try/except 的 return 之后（死代码），用户看不到
    “总成本不支持，已降级为住院人数”等提示。
    """
    failed = 0
    payload = {"data": [{"name": "A", "value": 1}], "meta": {"total_records": 1}}
    intent = {"chart_hint": "top_diagnoses", "metric": "total_costs",
              "top": 10, "filters": {}, "_source": "rules"}
    with mock.patch("agent.requests.get",
                    return_value=FakeResp(200, payload)):
        r = agent.call_analysis_api(intent, question="测试")
    warnings = r.get("meta", {}).get("warnings", [])
    if not warnings or warnings[0].get("type") != "metric_degraded":
        print(f"[FAIL] metric 降级警告未写入 meta.warnings: {r.get('meta')!r}")
        failed += 1
    else:
        print("[PASS] metric 降级警告已写入 meta.warnings（死代码已修复）")
    return failed


# ============ 4. _finalize_result 友好提示 ============
def test_finalize_timeout_message():
    failed = 0
    intent = {"chart_hint": "top_diagnoses", "metric": "count", "top": 10}
    api_result = {"error": "timeout", "data": [], "meta": {}}
    result = agent._finalize_result("测试问题", intent, api_result)
    answer = result.get("answer", "")
    if "超时" not in answer:
        print(f"[FAIL] _finalize_result 超时未给友好提示: {answer!r}")
        failed += 1
    else:
        print("[PASS] _finalize_result 超时 -> 友好提示（含'超时'）")
    return failed


def test_finalize_connerr_message():
    failed = 0
    intent = {"chart_hint": "top_diagnoses", "metric": "count", "top": 10}
    api_result = {"error": "connection_failed", "data": [], "meta": {}}
    result = agent._finalize_result("测试问题", intent, api_result)
    answer = result.get("answer", "")
    if "连接" not in answer:
        print(f"[FAIL] _finalize_result 连接失败未给友好提示: {answer!r}")
        failed += 1
    else:
        print("[PASS] _finalize_result 连接失败 -> 友好提示（含'连接'）")
    return failed


def test_finalize_empty_data_still_no_result():
    failed = 0
    intent = {"chart_hint": "top_diagnoses", "metric": "count", "top": 10}
    # 成功返回但 data 为空（真实"无符合条件的分析结果"）
    api_result = {"data": [], "meta": {"chart_hint": "top_diagnoses",
                                        "total_records": 0}}
    result = agent._finalize_result("测试问题", intent, api_result)
    answer = result.get("answer", "")
    if "未查询到" not in answer:
        print(f"[FAIL] _finalize_result 空data未提示'未查询到': {answer!r}")
        failed += 1
    else:
        print("[PASS] _finalize_result 空data -> '未查询到结果'（区分于服务故障）")
    return failed


def main():
    print("=== 1. 辅助函数 ===")
    f1 = test_make_p3_error()
    f2 = test_is_p3_logical_error()

    print("\n=== 2. _call_p3_api（Agent 路径）===")
    f3 = test_call_p3_api_timeout()
    f4 = test_call_p3_api_connerr()
    f5 = test_call_p3_api_nonjson()
    f6 = test_call_p3_api_business_error()
    f7 = test_call_p3_api_success()
    f8 = test_call_p3_api_retry()

    print("\n=== 3. call_analysis_api（旧管道）===")
    f9 = test_old_pipeline_timeout_no_raise()
    f10 = test_old_pipeline_connerr_no_raise()
    f11 = test_old_pipeline_nonjson()
    f12 = test_old_pipeline_business_error()
    f13 = test_old_pipeline_success()
    f17 = test_metric_degraded_warning_written()

    print("\n=== 4. _finalize_result 友好提示 ===")
    f14 = test_finalize_timeout_message()
    f15 = test_finalize_connerr_message()
    f16 = test_finalize_empty_data_still_no_result()

    failed = (f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8 + f9 + f10
              + f11 + f12 + f13 + f17 + f14 + f15 + f16)
    print()
    if failed:
        print(f"=== {failed} case(s) FAILED ===")
        sys.exit(1)
    else:
        print("=== ALL CASES PASSED ===")


if __name__ == "__main__":
    main()
