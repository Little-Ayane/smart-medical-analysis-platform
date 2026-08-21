# 3.AI交互 <-> 2.分析服务 (cost module) end-to-end integration test.
# This script is intentionally 100% ASCII so Windows PowerShell 5.1 (which reads
# .ps1 as the system ANSI/GBK codepage) never mis-parses Chinese in the source.
# Questions live in cost_questions.json and are read with explicit UTF-8.
#
# Usage (run inside 3.AI交互 folder):
#   powershell -ExecutionPolicy Bypass -File test_cost_chat.ps1
# Prereq: P3 (app.py :5000) and P4 (agent.py :5001) are both running.

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Base = "http://127.0.0.1:5001"
$Enc  = New-Object System.Text.UTF8Encoding($false)
$Dir  = $PSScriptRoot   # resolve all file I/O relative to this script's folder

Write-Host "===== Health ====="
curl.exe "$Base/api/health"

Write-Host "===== Loading questions from cost_questions.json ====="
$raw   = [System.IO.File]::ReadAllText((Join-Path $Dir "cost_questions.json"))
$items = $raw | ConvertFrom-Json

$i = 0
foreach ($item in $items) {
    $i++
    $name = $item.name
    $q    = $item.q
    Write-Host ("===== [" + $i + "/" + $items.Count + "] " + $name + " =====")
    Write-Host ("Q: " + $q)

    try {
        # Build body as UTF-8 (no BOM) and let curl read it from a file.
        # This avoids passing Chinese on the command line (PowerShell -> native
        # exe non-ASCII argument loss) AND avoids console encoding issues.
        $json = '{"question":"' + $q + '"}'
        $bodyPath = Join-Path $Dir "body.json"
        [System.IO.File]::WriteAllText($bodyPath, $json, $Enc)

        $resp = & curl.exe -s -X POST "$Base/api/chat" -H "Content-Type: application/json" -d "@$bodyPath" 2>&1
        $exit = $LASTEXITCODE

        # Persist raw response so you can open it in any editor (no console garble).
        [System.IO.File]::WriteAllText((Join-Path $Dir ("resp_" + $i + "_" + $name + ".json")), ($resp -join "`n"), $Enc)

        try {
            $obj  = ($resp -join "") | ConvertFrom-Json
            $code = $obj.code
            $hint = $obj.intent.chart_hint
            $ctype = $obj.chart.chart_type
            $src   = $obj.intent._source
            $ans   = $obj.answer
            $agentOut = $null
            if ($obj.meta -and $obj.meta.agent_output) { $agentOut = $obj.meta.agent_output }

            Write-Host ("  -> code=" + $code + "  chart_hint=" + $hint + "  chart_type=" + $ctype + "  intent=" + $src)

            # Clean, readable dump of the actual reply so you can judge LLM quality.
            $txt = "Q: " + $q + "`n"
            $txt += "intent_source: " + $src + "`n"
            $txt += "chart_hint: " + $hint + "  chart_type: " + $ctype + "`n`n"
            $txt += "----- answer (user-facing, reliable) -----`n"
            $txt += $ans + "`n"
            if ($agentOut) {
                $txt += "`n----- agent_output (LangChain free-form, hallucination risk) -----`n"
                $txt += $agentOut + "`n"
            }
            [System.IO.File]::WriteAllText((Join-Path $Dir ("answer_" + $i + "_" + $name + ".txt")), $txt, $Enc)

            # Console preview (may mojibake in GBK consoles; open the .txt for clean text).
            $preview = $ans
            if ($preview.Length -gt 400) { $preview = $preview.Substring(0, 400) + " ..." }
            Write-Host ("  answer: " + $preview)
            if ($agentOut) { Write-Host ("  agent_output: " + $agent_out) }
        } catch {
            Write-Host ("  -> (response not JSON-parsed; see resp_" + $i + "_" + $name + ".json) curl_exit=" + $exit)
        }
    } catch {
        Write-Host ("  ERROR: " + $_.Exception.Message)
    } finally {
        Remove-Item (Join-Path $Dir "body.json") -ErrorAction SilentlyContinue
    }
}

Write-Host "===== Done. Open answer_*.txt for readable replies; resp_*.json for raw JSON. ====="
