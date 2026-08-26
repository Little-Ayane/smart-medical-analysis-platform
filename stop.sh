#!/usr/bin/env bash
# ============================================================
# 智慧医疗平台 · 一键停止脚本（mode7）
# 用法：bash stop.sh
# ============================================================
set -u

log() { echo "[$(date +%H:%M:%S)] $*"; }

pkill -f "app.py"                        2>/dev/null && log "已停止 Flask (5000)"
pkill -f "uvicorn modules.core.main"     2>/dev/null && log "已停止 core (8000)"
pkill -f "uvicorn modules.drg.main"      2>/dev/null && log "已停止 drg (8001)"
pkill -f "agent.py"                      2>/dev/null && log "已停止 agent (5001)"
pkill -f "vite"                          2>/dev/null && log "已停止 前端 (5173)"

echo "各应用服务已停止（MySQL 保留运行，如需停止请手动执行 mysqladmin shutdown）"
