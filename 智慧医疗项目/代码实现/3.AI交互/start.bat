@echo off
REM ============================================================
REM  P4 AI 交互服务 · Windows 启动脚本
REM  用法：
REM    .\start.bat                启动 P4 Flask 服务（默认端口 5001，读 .env）
REM    .\start.bat --self-check   不启动服务，只做语法 + 依赖 + 配置自检
REM    .\start.bat --selftest     不启动服务，直接跑 handle_question 打印结果
REM  安全提示：真实密钥请写到 同目录 .env.local 文件（该文件已被 .gitignore 忽略），
REM           或直接设置系统环境变量 / K8s Secret，不要在本脚本里写死 sk-xxx
REM ============================================================

setlocal
cd /d "%~dp0"

REM ---------- Step 1: 检查 Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] ❌ 找不到 python，请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
)
echo [OK] ✅ Python 存在： & where python

REM ---------- Step 2: 检查 python-dotenv（可选，缺失给出提示） ----------
python -c "import dotenv" >nul 2>nul
if errorlevel 1 (
    echo [提示] ⚠️  未安装 python-dotenv，脚本会尝试自动安装（失败也不阻塞启动）：
    python -m pip install --quiet python-dotenv
    if errorlevel 1 (
        echo [提示] pip install python-dotenv 失败，继续以「不自动读 .env」方式运行……
    ) else (
        echo [OK] ✅ python-dotenv 安装成功
    )
) else (
    echo [OK] ✅ python-dotenv 已安装
)

REM ---------- Step 3: 检查其他依赖（flask/flask-cors/requests） ----------
python -c "import flask, flask_cors, requests" >nul 2>nul
if errorlevel 1 (
    echo [安装] 📦 发现缺失依赖（flask / flask-cors / requests），正在安装 requirements …
    REM 如果上级有 requirements.txt 就用，否则直接 pip
    if exist "..\..\..\requirements.txt" (
        python -m pip install -r "..\..\..\requirements.txt"
    ) else (
        python -m pip install flask flask-cors requests
    )
    if errorlevel 1 (
        echo [错误] ❌ 依赖安装失败，请手动 pip install flask flask-cors requests python-dotenv
        pause
        exit /b 1
    )
) else (
    echo [OK] ✅ flask / flask-cors / requests 依赖已就绪
)

REM ---------- Step 4: 检查密钥（不打印、只校验存在性） ----------
python -c "import os; k=os.getenv('LLM_API_KEY',''); import sys; sys.exit(0 if k else 2)" >nul 2>nul
if errorlevel 2 (
    echo [提示] ⚠️  LLM_API_KEY 未设置，系统会以「规则引擎 + 模板兜底」模式运行。
    echo        如需开启 LLM 能力，请在本目录创建 .env.local，写入一行 LLM_API_KEY=sk-你的真实Key
) else (
    echo [OK] ✅ 检测到 LLM_API_KEY 已注入（来自 .env 或系统环境变量；不会打印任何真实字符）
)

REM ---------- Step 5: 分支执行 ----------
if "%~1" == "--self-check" goto SELF_CHECK
if "%~1" == "--selftest"   goto SELFTEST_QUESTION
goto RUN_FLASK


:SELF_CHECK
echo.
echo ============================================================
echo  🩺  配置自检（不启动服务）
echo ============================================================
python -c "import os, sys; sys.path.insert(0,'.'); import agent; 
print('dotenv 加载文件:', agent._DOTENV_LOADED_FROM or '未加载');
print('LLM_ENABLED      :', agent.LLM_ENABLED);
print('LLM_SMALL_ENABLED:', agent.LLM_SMALL_ENABLED);
print('SESSION_BACKEND  :', agent.SESSION_BACKEND);
print('CORS_ORIGINS     :', agent.CORS_ORIGINS);
print('FLASK_DEBUG      :', agent.FLASK_DEBUG);
print('ANALYSIS_API     :', agent.ANALYSIS_API);
print('P4_PORT          :', os.getenv('P4_PORT','5001'));
print('缓存启用         :', agent.INTENT_CACHE_ENABLED);
print('异步报告 TTL(s)  :', agent.ASYNC_REPORT_TTL_SECONDS);
"
if errorlevel 1 (
    echo [错误] ❌ 自检失败，请查看上面的报错。
) else (
    echo.
    echo [完成] ✅ 所有关键配置读取正常。
)
pause
exit /b 0


:SELFTEST_QUESTION
echo.
echo ============================================================
echo  🧪 本地自测（不启动 Flask，直接跑 handle_question）
echo ============================================================
python agent.py --selftest
pause
exit /b 0


:RUN_FLASK
echo.
echo ============================================================
echo  🚀 启动 P4 AI 交互 Flask 服务...
echo ============================================================
REM 设置 PYTHONUNBUFFERED=1 让 Flask 输出不被缓存，方便看日志
set PYTHONUNBUFFERED=1
python agent.py
REM 服务异常退出时提示
echo.
echo [提示] P4 服务已退出。如果是异常退出，请查看上面的错误日志。
pause
endlocal
exit /b 0
