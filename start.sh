#!/usr/bin/env bash
# ============================================================
# 智慧医疗平台 · 一键启动脚本（mode7）
# 依次启动：MySQL → Flask(5000) → core(8000) → drg(8001) → agent(5001) → 前端(5173)
# 用法：bash start.sh
# 日志：/tmp/ 下各服务 *.log
# ============================================================
set -u

MYSQL_BIN=/opt/mysql/bin/mysql
MYSQLADMIN=/opt/mysql/bin/mysqladmin
MYSQL_SOCK=/opt/mysql/mysql.sock
PY=python3.11
BASE="$(cd "$(dirname "$0")" && pwd)"
ANALYSIS="$BASE/backend/智慧医疗项目/代码实现/2.分析服务"
FRONTEND="$BASE/frontend/medical-frontend"
AI="$BASE/backend/智慧医疗项目/代码实现/3.AI交互"

log()  { echo "[$(date +%H:%M:%S)] $*"; }

# ---------- 1. MySQL ----------
if ! "$MYSQLADMIN" --socket="$MYSQL_SOCK" -u root status >/dev/null 2>&1; then
  log "启动 MySQL..."
  /opt/mysql/bin/mysqld_safe --defaults-file=/opt/mysql/my.cnf >/tmp/mysqld_safe.log 2>&1 &
  for _ in $(seq 1 30); do
    "$MYSQLADMIN" --socket="$MYSQL_SOCK" -u root status >/dev/null 2>&1 && break
    sleep 1
  done
fi
"$MYSQLADMIN" --socket="$MYSQL_SOCK" -u root status >/dev/null 2>&1 \
  && log "MySQL 已就绪 (3306)" || { log "MySQL 启动失败，见 /tmp/mysqld_safe.log"; exit 1; }

# ---------- 2. Flask P3 (5000) ----------
if ! (ss -tln 2>/dev/null | grep -q ':5000 '); then
  (cd "$ANALYSIS" && nohup "$PY" app.py >/tmp/flask5000.log 2>&1 &)
  log "Flask 分析服务 (5000) 已启动"
else
  log "Flask (5000) 已在运行"
fi

# ---------- 3. FastAPI core (8000) ----------
if ! (ss -tln 2>/dev/null | grep -q ':8000 '); then
  (cd "$ANALYSIS" && nohup "$PY" -m uvicorn modules.core.main:app --host 0.0.0.0 --port 8000 >/tmp/core8000.log 2>&1 &)
  log "核心分析服务 (8000) 已启动"
else
  log "核心分析 (8000) 已在运行"
fi

# ---------- 4. FastAPI drg (8001) ----------
if ! (ss -tln 2>/dev/null | grep -q ':8001 '); then
  (cd "$ANALYSIS" && nohup "$PY" -m uvicorn modules.drg.main:app --host 0.0.0.0 --port 8001 >/tmp/drg8001.log 2>&1 &)
  log "DRG 分析服务 (8001) 已启动"
else
  log "DRG (8001) 已在运行"
fi

# ---------- 5. AI agent P4 (5001) ----------
if ! (ss -tln 2>/dev/null | grep -q ':5001 '); then
  (cd "$AI" && nohup "$PY" agent.py >/tmp/agent5001.log 2>&1 &)
  log "AI agent (5001) 已启动"
else
  log "AI agent (5001) 已在运行"
fi

# ---------- 6. 前端 Vite (5173) ----------
if ! (ss -tln 2>/dev/null | grep -q ':5173 '); then
  (cd "$FRONTEND" && nohup npm run dev >/tmp/vite.log 2>&1 &)
  log "前端 Vite (5173) 已启动"
else
  log "前端 (5173) 已在运行"
fi

# ---------- 7. 预热持久化缓存（后台异步；首次慢、之后秒级） ----------
# 缓存结果落盘 medical_db.api_cache，跨重启存活。WARM_CACHE=0 可跳过。
if [ "${WARM_CACHE:-1}" != "0" ] && command -v python3.11 >/dev/null 2>&1; then
  # 等 Flask/core/drg 就绪后再打，避免一启动就请求失败
  ( sleep 5
    cd "$BASE/database" && python3.11 warm_cache.py >/tmp/warm_cache.log 2>&1 ) &
  log "缓存预热已在后台启动（日志 /tmp/warm_cache.log）"
fi

echo
echo "================ 启动完成 ================"
echo "  前端访问: http://localhost:5173"
echo "  Flask 文档: http://localhost:5000 (无 Swagger)"
echo "  core 文档: http://localhost:8000/docs"
echo "  drg  文档: http://localhost:8001/docs"
echo "  日志目录: /tmp/{flask5000,core8000,drg8001,agent5001,vite}.log"
