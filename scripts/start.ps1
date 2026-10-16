# 一键启动 Personal Agent（Windows）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "缺少 .venv。先: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}
Write-Host "Personal Agent → http://127.0.0.1:8765"
& $py -m src.main
