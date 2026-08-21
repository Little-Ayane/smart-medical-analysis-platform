"""验证 agent.py 在 langchain 0.2.x (v02) 路径下的加载与 AgentExecutor 构建。

不发起任何真实 LLM 网络调用——只验证：
  - _LC_AGENT_API == "v02"
  - _TOOLS 含 16 个 StructuredTool
  - _get_agent_executor() 能成功构建 AgentExecutor（ChatOpenAI 构造期不联网）
  - AgentExecutor 正确绑定了 16 个工具
"""
import os
import sys

# 虚拟 key 仅用于让 LLM_ENABLED=True，触发 AgentExecutor 构建路径（构造期不联网）
os.environ.setdefault("LLM_API_KEY", "sk-test-verify-v02-path")
os.environ.setdefault("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
os.environ.setdefault("LLM_MODEL_ID", "Qwen/Qwen2.5-72B-Instruct")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import importlib.util

spec = importlib.util.spec_from_file_location("agent_v02", os.path.join(HERE, "agent.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}")


# 1. API 版本识别
check("_LC_AGENT_API == 'v02'", mod._LC_AGENT_API == "v02")
check("_LANGCHAIN_AVAILABLE is True", mod._LANGCHAIN_AVAILABLE is True)

# 2. 工具数量
check(f"_TOOLS count == 16 (got {len(mod._TOOLS)})", len(mod._TOOLS) == 16)

expected_names = [
    "top_diagnoses", "top_procedures", "severity_profile", "population_diff",
    "pyramid", "heatmap", "region_diff", "payment_composition", "payment_cross",
    "sankey", "cost_relation", "oop_burden", "payment_summary",
    "general_aggregate", "payment_mix", "trend",
]
got_names = [t.name for t in mod._TOOLS]
check("tool names match 16 expected", got_names == expected_names)

# 3. 构建 AgentExecutor（v02: create_tool_calling_agent + AgentExecutor）
executor = mod._get_agent_executor()
check("AgentExecutor built (not None)", executor is not None)
check("is AgentExecutor instance", type(executor).__name__ == "AgentExecutor")
check("agent has 16 tools bound", len(executor.tools) == 16)

# 4. 系统提示词「可用工具」段落恰好列出 16 条工具
prompt_str = mod._AGENT_SYSTEM_PROMPT
lines = prompt_str.splitlines()
start = next(i for i, l in enumerate(lines) if "可用工具及适用场景" in l)
end = next(i for i, l in enumerate(lines) if "筛选条件(filters)" in l)
tool_block = lines[start:end]
numbered = [l.strip() for l in tool_block
            if l.strip() and l.strip()[0].isdigit() and "." in l.strip()[:3]]
check(f"system prompt tool section lists 16 tools (got {len(numbered)})",
      len(numbered) == 16)

# 5. _VALID_TOOL_NAMES 正确初始化
mod._init_valid_tool_names()
check("_VALID_TOOL_NAMES has 16 entries", len(mod._VALID_TOOL_NAMES) == 16)

print("\n" + ", ".join(got_names))
print(f"\n=== {passed} passed, {failed} failed ===")
sys.exit(1 if failed else 0)
