# -*- coding: utf-8 -*-
"""可观测日志 + 多轮上下文 单元测试。

运行方式（lc02 venv，含 requests/flask/langchain 0.2.16）：
    python test_observability_multiturn.py

设计：用 unittest.mock 拦截 P3 接口与 LLM 调用，纯函数/纯逻辑验证，
不依赖真实 P3 服务或 LLM_API_KEY。统计计数在 import 后即累加，故测试前
先重置 _RUNTIME_STATS 快照以便断言增量。
"""
import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent  # noqa: E402


def _reset_runtime():
    """把运行态统计清零，便于断言「本次调用产生的增量」。"""
    with agent._RUNTIME_LOCK:
        for k in list(agent._RUNTIME_STATS.keys()):
            if k == "start_ts":
                continue
            if isinstance(agent._RUNTIME_STATS[k], dict):
                agent._RUNTIME_STATS[k] = {}
            else:
                agent._RUNTIME_STATS[k] = 0


class TestObservability(unittest.TestCase):
    """可观测日志：结构化事件 + 运行态统计。"""

    def test_log_event_is_structured_json(self):
        """_log_event 产出单行 JSON，含 event/ts 与自定义字段。"""
        captured = {}
        with patch.object(agent.logger, "info", side_effect=lambda *a, **k: captured.update({"args": a})):
            agent._log_event("p3_result", chart_hint="top_diagnoses", ok=True)
        # logger.info("[OBS] %s", json_str) → args = ("[OBS] %s", json_str)
        self.assertIn("[OBS]", captured["args"][0])
        payload = json.loads(captured["args"][1])
        self.assertEqual(payload["event"], "p3_result")
        self.assertEqual(payload["chart_hint"], "top_diagnoses")
        self.assertTrue(payload["ok"] is True)
        self.assertIn("ts", payload)

    def test_runtime_stats_p3_error_counted(self):
        """_make_p3_error 统一累加 p3_error_total 与按 kind 细分。"""
        _reset_runtime()
        before = agent._RUNTIME_STATS["p3_error_total"]
        agent._make_p3_error("top_diagnoses", "timeout")
        agent._make_p3_error("top_diagnoses", "timeout")
        agent._make_p3_error("trend", "connection_failed")
        after = agent._RUNTIME_STATS["p3_error_total"]
        self.assertEqual(after - before, 3)
        self.assertEqual(agent._RUNTIME_STATS["p3_errors_by_kind"].get("timeout"), 2)
        self.assertEqual(agent._RUNTIME_STATS["p3_errors_by_kind"].get("connection_failed"), 1)

    def test_runtime_stats_derived_metrics(self):
        """_get_runtime_stats 计算命中率/错误率/平均耗时/uptime 等派生指标。"""
        _reset_runtime()
        agent._obs_inc("requests_total", 10)
        agent._obs_inc("agent_path_total", 7)
        agent._obs_inc("p3_calls_total", 4)
        agent._obs_inc("p3_error_total", 1)
        agent._obs_latency("p3_latency_ms_total", 400.0)
        agent._obs_inc("summary_calls_total", 2)
        agent._obs_latency("summary_latency_ms_total", 100.0)
        stats = agent._get_runtime_stats()
        self.assertEqual(stats["agent_hit_rate"], 0.7)
        self.assertEqual(stats["p3_error_rate"], 0.25)
        self.assertEqual(stats["avg_p3_latency_ms"], 100.0)
        self.assertEqual(stats["avg_summary_latency_ms"], 50.0)
        self.assertIn("uptime_seconds", stats)
        self.assertGreaterEqual(stats["uptime_seconds"], 0)

    def test_path_and_intent_source_counted_via_handle_question(self):
        """handle_question 走旧管道时不经 Agent，应累加 legacy_path_total 与 intent_sources。"""
        _reset_runtime()
        fake_result = {
            "question": "测试", "intent": {"chart_hint": None, "_source": "rules",
                                          "dimension": "ccsr_diagnosis", "metric": "count",
                                          "filters": {}, "top": None},
            "answer": "ok", "chart": {}, "meta": {},
        }
        with patch.object(agent, "_LANGCHAIN_AVAILABLE", False), \
             patch.object(agent, "LLM_ENABLED", False), \
             patch.object(agent, "call_analysis_api", return_value={"data": [], "meta": {}}), \
             patch.object(agent, "_finalize_result", return_value=fake_result) as fin:
            agent.handle_question("常见疾病有哪些", use_llm_intent=False)
            # 旧管道分支被走到
            self.assertTrue(fin.called)
        self.assertGreaterEqual(agent._RUNTIME_STATS["legacy_path_total"], 1)
        self.assertGreaterEqual(agent._RUNTIME_STATS["requests_total"], 1)

    def test_agent_fallback_reason_recorded(self):
        """Agent executor 不可用时，应记 agent_fallback_total + reason=executor_unavailable。"""
        _reset_runtime()
        with patch.object(agent, "_get_agent_executor", return_value=None), \
             patch.object(agent, "_LANGCHAIN_AVAILABLE", True), \
             patch.object(agent, "LLM_ENABLED", True):
            res = agent._handle_question_via_agent("常见疾病")
        self.assertIsNone(res)
        self.assertGreaterEqual(agent._RUNTIME_STATS["agent_fallback_total"], 1)
        self.assertGreaterEqual(
            agent._RUNTIME_STATS["agent_fallback_reasons"].get("executor_unavailable", 0), 1)


class TestMultiTurnContext(unittest.TestCase):
    """多轮上下文增强。"""

    def test_format_history_includes_answer(self):
        """_format_history_for_intent 应包含上一轮答案摘要，且不硬编码 3 轮。"""
        history = [
            {"question": "常见疾病", "intent": {"dimension": "ccsr_diagnosis", "metric": "count"},
             "answer": "肺炎排第一，共 1234 例。"},
            {"question": "按年份看", "intent": {"dimension": "ccsr_diagnosis", "metric": "count",
                                             "filters": {"year": 2021}}, "answer": "2021 年数据。"},
        ]
        text = agent._format_history_for_intent(history)
        self.assertIn("回答摘要", text)
        self.assertIn("肺炎排第一", text)
        # 编号基于最近 N 轮连续编号
        self.assertIn("第1轮", text)
        self.assertIn("第2轮", text)

    def test_format_history_empty(self):
        """无历史返回明确占位。"""
        self.assertIn("第一轮", agent._format_history_for_intent([]))

    def test_rules_inherit_after_topic_switch(self):
        """规则引擎：中途换话题（last turn 无 dimension 关键词）后再次追问，应能回溯更早轮继承 dimension。"""
        history = [
            {"question": "各疾病住院人数",
             "intent": {"dimension": "ccsr_diagnosis", "metric": "count",
                        "filters": {"year": 2020}, "top": 10, "chart_hint": "top_diagnoses"}},
            # 中途换话题：问支付方式占比，dimension 变为 payment_typology
            {"question": "支付方式占比",
             "intent": {"dimension": "payment_typology", "metric": "payment_mix",
                        "filters": {}, "top": 10, "chart_hint": "payment_mix"}},
        ]
        # 当前问题"这俩比一下"无任何维度/指标关键词 → 应回溯继承更早轮的 payment_typology
        intent = agent._parse_intent_by_rules("这俩比一下", history)
        self.assertEqual(intent["dimension"], "payment_typology")
        self.assertEqual(intent["metric"], "payment_mix")
        self.assertEqual(intent["filters"].get("year"), 2020)

    def test_rules_intent_overrides_history(self):
        """当前问题明确指定维度时，不继承历史的 dimension（避免误继承）。"""
        history = [
            {"question": "各疾病", "intent": {"dimension": "ccsr_diagnosis",
                                            "metric": "count", "filters": {"year": 2020}}},
        ]
        intent = agent._parse_intent_by_rules("各年龄段住院人数", history)
        self.assertEqual(intent["dimension"], "age_group")  # 当前问题明确 → 不被历史覆盖
        self.assertEqual(intent["filters"].get("year"), 2020)  # 年份未指定 → 继承

    def test_handle_question_writes_history(self):
        """多轮下 handle_question 把本轮写入会话历史，conversation_turn 递增。"""
        import time as _t
        cid = f"ut_{int(_t.time()*1000)}"
        agent.MEMORY.clear(cid)
        p3_ok = {"data": [{"name": "糖尿病", "value": 123}], "meta": {"total_records": 1}}
        with patch.object(agent, "_LANGCHAIN_AVAILABLE", False), \
             patch.object(agent, "LLM_ENABLED", False), \
             patch.object(agent, "call_analysis_api", return_value=p3_ok), \
             patch.object(agent, "generate_text_summary", return_value="摘要"), \
             patch.object(agent, "generate_chart_config", return_value={"type": "bar"}):
            r1 = agent.handle_question("糖尿病top", conversation_id=cid, use_llm_intent=False)
            r2 = agent.handle_question("再按年份", conversation_id=cid, use_llm_intent=False)
        self.assertEqual(r1["conversation_turn"], 1)
        self.assertEqual(r2["conversation_turn"], 2)
        self.assertEqual(len(agent.MEMORY.get_history(cid)), 2)
        agent.MEMORY.clear(cid)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestObservability, TestMultiTurnContext):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print(f"\n==== 断言总数: {result.testsRun} | 失败: {len(result.failures)} | 错误: {len(result.errors)} ====")
    sys.exit(0 if result.wasSuccessful() else 1)
