# 生产模式一键启动：构建前端 + 后端单端口托管（http://127.0.0.1:8000）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Port 8000 -Build
#
# 前置：已安装 backend/requirements.txt 依赖（默认使用 conda 环境 talentmatch）

param(
    [string]$Python = "",
    [int]$Port = 8000,
    [switch]$Build
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    $candidates = @(
        $env:TALENTMATCH_PYTHON,
        "D:\miniconda3\envs\talentmatch\python.exe",
        (Join-Path $env:USERPROFILE "miniconda3\envs\talentmatch\python.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\envs\talentmatch\python.exe"),
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    )
    foreach ($item in $candidates) {
        if ($item -and (Test-Path -LiteralPath $item)) { $Python = $item; break }
    }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    Write-Host "找不到 Python，请先创建 talentmatch 环境并安装依赖。" -ForegroundColor Red
    exit 1
}

$dist = Join-Path $root 'frontend\dist'
if ($Build -or -not (Test-Path -LiteralPath (Join-Path $dist 'index.html'))) {
    Write-Host "构建前端..." -ForegroundColor Cyan
    Push-Location (Join-Path $root 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) { npm.cmd install }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
    } finally {
        Pop-Location
    }
}

if (-not $env:SERVE_FRONTEND) { $env:SERVE_FRONTEND = 'true' }
Write-Host "启动 TalentMatch：http://127.0.0.1:$Port" -ForegroundColor Green
Push-Location (Join-Path $root 'backend')
try {
    & $Python -m uvicorn app.main:app --host 0.0.0.0 --port $Port
} finally {
    Pop-Location
}
