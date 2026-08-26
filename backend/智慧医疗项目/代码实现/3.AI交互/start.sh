#!/usr/bin/env bash
# ============================================================
# P4 AI 交互服务 · Linux / macOS 启动脚本
# 用法：
#   ./start.sh                启动 P4 Flask 服务（默认端口 5001，读 .env）
#   ./start.sh --self-check   不启动服务，只做语法 + 依赖 + 配置自检
#   ./start.sh --selftest     不启动服务，直接跑 handle_question 打印结果
# ============================================================
# 安全：真实密钥不落地（不写死在这里），读顺序：
#   1) 已经 export 的环境变量 / Kubernetes Secret
#   2) 脚本当前目录的 .env.local / .env / .env.production（通过 agent.py 顶部 load_dotenv）
# ============================================================

set -u          # 未定义变量报错
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log_ok()   { echo "[OK] ✅  $*"; }
log_warn() { echo "[提示] ⚠️  $*"; }
log_err()  { echo "[错误] ❌ $*" 1>&2; }
sep()      { echo "============================================================"; }

# ---------- Step 1: 找 Python ----------
PY_BIN="${PYTHON:-}"
if [ -z "$PY_BIN" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PY_BIN=python3
    elif command -v python >/dev/null 2>&1; then
        PY_BIN=python
    fi
fi
if [ -z "$PY_BIN" ] || ! $PY_BIN -c "import sys; assert sys.version_info >= (3,10)" >/dev/null 2>&1; then
    log_err "未找到 Python >= 3.10。请先安装或设置 PYTHON=/path/to/python"
    exit 1
fi
log_ok "Python 解释器: $($PY_BIN --version 2>&1 | head -1)  ($($PY_BIN -c 'import sys; print(sys.executable)'))"

# ---------- Step 2: python-dotenv 可选依赖 ----------
if ! $PY_BIN -c "import dotenv" >/dev/null 2>&1; then
    log_warn "未安装 python-dotenv，自动安装（失败不阻塞启动）"
    if $PY_BIN -m pip install --quiet python-dotenv; then
        log_ok "python-dotenv 安装成功"
    else
        log_warn "安装失败，启动后将以「不自动读 .env 文件」模式运行（生产推荐直接 export 环境变量）"
    fi
else
    log_ok "python-dotenv 已安装"
fi

# ---------- Step 3: 检查核心依赖 ----------
if ! $PY_BIN -c "import flask, flask_cors, requests" >/dev/null 2>&1; then
    REQ="$(realpath -m "$SCRIPT_DIR/../../../requirements.txt")"
    log_warn "核心依赖 flask/flask-cors/requests 未就绪，尝试安装："
    if [ -f "$REQ" ]; then
        $PY_BIN -m pip install -r "$REQ" || { log_err "依赖安装失败"; exit 1; }
    else
        $PY_BIN -m pip install flask flask-cors requests || { log_err "依赖安装失败"; exit 1; }
    fi
fi
log_ok "flask / flask-cors / requests 依赖已就绪"

# ---------- Step 4: 检查密钥（只看是否存在，不打印值） ----------
if [ -z "${LLM_API_KEY:-}" ]; then
    # 如果没直接 export，试一下从 .env 预读（让后续检查更准确）
    if [ -f .env.local ]; then
        # shellcheck disable=SC1091
        set -a; . ./.env.local 2>/dev/null || true; set +a
    elif [ -f .env ]; then
        # shellcheck disable=SC1091
        set -a; . ./.env 2>/dev/null || true; set +a
    fi
fi
if [ -n "${LLM_API_KEY:-}" ] && [ "$LLM_API_KEY" != "" ]; then
    log_ok "检测到 LLM_API_KEY 已注入（不会打印任何字符）"
else
    log_warn "LLM_API_KEY 未设置 → 系统会以「规则引擎 + 模板兜底」运行。"
    echo "        如需启用 LLM，写入 .env.local： LLM_API_KEY=sk-真实Key"
fi

# ---------- Step 5: 分支执行 ----------
case "${1:-}" in
    --self-check)
        echo
        sep
        echo "  🩺  配置自检（不启动服务）"
        sep
        $PY_BIN - <<'PY'
import os, sys
sys.path.insert(0, ".")
import agent
print(f"dotenv 加载文件  : {agent._DOTENV_LOADED_FROM or '未加载'}")
print(f"LLM_ENABLED      : {agent.LLM_ENABLED}")
print(f"LLM_SMALL_ENABLED: {agent.LLM_SMALL_ENABLED}")
print(f"SESSION_BACKEND  : {agent.SESSION_BACKEND}")
print(f"CORS_ORIGINS     : {agent.CORS_ORIGINS}")
print(f"FLASK_DEBUG      : {agent.FLASK_DEBUG}")
print(f"ANALYSIS_API     : {agent.ANALYSIS_API}")
print(f"P4_PORT          : {os.getenv('P4_PORT','5001')}")
print(f"意图缓存启用     : {agent.INTENT_CACHE_ENABLED}")
print(f"异步报告 TTL(s)  : {agent.ASYNC_REPORT_TTL_SECONDS}")
PY
        RC=$?
        echo
        [ "$RC" = 0 ] && echo "[完成] ✅ 所有关键配置读取正常" || log_err "自检失败"
        exit $RC
        ;;
    --selftest)
        echo
        sep
        echo "  🧪 本地自测（不启动 Flask，直接跑 handle_question）"
        sep
        exec $PY_BIN agent.py --selftest
        ;;
    "")
        echo
        sep
        echo "  🚀 启动 P4 AI 交互 Flask 服务..."
        sep
        export PYTHONUNBUFFERED=1
        exec $PY_BIN agent.py
        ;;
    *)
        echo "用法: $0 [--self-check|--selftest]"
        exit 2
        ;;
esac
