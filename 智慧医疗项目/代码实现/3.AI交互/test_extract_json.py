# -*- coding: utf-8 -*-
"""#9 单元测试：_extract_json_from_llm_output 公共函数。
覆盖 5 类场景共 12 个用例，纳入 --selftest 自动化测试套件。
用法：python test_extract_json.py
"""
import sys

import agent

CASES = [
    # —— 1. 正常场景：直接 JSON ——
    ("plain object", '{"a": 1, "b": [2, 3]}',
     True, {"a": 1, "b": [2, 3]}, ""),
    ("plain array", '[1, 2, 3]',
     True, [1, 2, 3], ""),
    ("nested object", '{"x": {"y": 2}, "z": 3}',
     True, {"x": {"y": 2}, "z": 3}, ""),
    ("empty object", '{}',
     True, {}, ""),
    ("empty array", '[]',
     True, [], ""),

    # —— 2. markdown 包裹（容错多层嵌套、带语言标签）——
    ("```json block", '```json\n{"summary": "hi", "chart_suggestion": {"title": "t"}}\n```',
     True, {"summary": "hi", "chart_suggestion": {"title": "t"}}, ""),
    ("``` block no lang", '```\n{"a": 1}\n```',
     True, {"a": 1}, ""),
    ("triple nested ```", '````\n```json\n{"a": 1}\n```\n````',
     True, {"a": 1}, ""),

    # —— 3. 带前后文字（LLM 经常加解释语）——
    ("prose before", '好的，这是结果：\n{"summary": "hi"}\n以上',
     True, {"summary": "hi"}, ""),
    ("prose after", '{"summary": "hi"}\n以上是我的回答',
     True, {"summary": "hi"}, ""),

    # —— 4. 错误输入 ——
    ("empty string", '',
     False, None, "空输入"),
    ("pure text", 'not a json at all',
     False, None, None),  # reason 含诊断信息，不严格匹配
    ("None input", None,
     False, None, "空输入"),
    ("number input", '12345',  # 纯数字虽然能 json.loads 但不是 dict/list，不在此场景
     False, None, None),
    ("incomplete json", '{"a": 1, "b":',
     False, None, None),
]


def run():
    failed = 0
    for i, (name, raw, exp_ok, exp_obj, exp_reason_contains) in enumerate(CASES, 1):
        try:
            ok, obj, reason = agent._extract_json_from_llm_output(raw)
        except Exception as e:
            print(f"[FAIL] #{i} {name}: 抛异常 {type(e).__name__}: {e}")
            failed += 1
            continue

        # 校验 ok 标志
        if ok != exp_ok:
            print(f"[FAIL] #{i} {name}: ok expected={exp_ok}, actual={ok}, reason={reason}")
            failed += 1
            continue

        # 校验解析对象（成功时）
        if exp_ok:
            if obj != exp_obj:
                print(f"[FAIL] #{i} {name}: obj expected={exp_obj!r}, actual={obj!r}")
                failed += 1
                continue
            print(f"[PASS] #{i} {name}: ok={ok} obj={obj!r}")
        else:
            # 失败时 obj 应为 None
            if obj is not None:
                print(f"[FAIL] #{i} {name}: 失败时 obj 应为 None，实际={obj!r}")
                failed += 1
                continue
            # 校验 reason 包含期望字符串（如果指定）
            if exp_reason_contains and exp_reason_contains not in reason:
                print(f"[FAIL] #{i} {name}: reason expected contains {exp_reason_contains!r}, "
                      f"actual={reason!r}")
                failed += 1
                continue
            print(f"[PASS] #{i} {name}: ok={ok} reason={reason[:60]}")

    print("-" * 70)
    if failed == 0:
        print(f"[全部通过] {len(CASES)} 个用例全部 PASS")
    else:
        print(f"[有失败] {failed}/{len(CASES)} 个用例失败")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    run()
