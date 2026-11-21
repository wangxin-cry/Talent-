# 启动开发环境（后端 + 前端）
#
# 用法（项目根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -NoFrontend
#
# 说明：
#   后端在新窗口启动（uvicorn --reload）
#   前端在当前窗口启动（vite，可 Ctrl+C 停止）
#   关闭后端：关掉新开的那个窗口即可

param(
    [string]$Python = "D:\ProgramData\miniconda3\envs\py311\python.exe",
    [switch]$NoFrontend
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "找不到 Python：$Python" -ForegroundColor Red
    Write-Host "请用 -Python 指定解释器路径，例如：" -ForegroundColor Yellow
    Write-Host '  -Python "C:\path\to\python.exe"' -ForegroundColor Yellow
    exit 1
}

$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'

# 确保 data 目录存在
New-Item -ItemType Directory -Force -Path (Join-Path $root 'data') | Out-Null

Write-Host "==> 启动后端 http://localhost:8000  (docs: /docs)" -ForegroundColor Cyan
Start-Process -FilePath $Python `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000') `
    -WorkingDirectory $backendDir

Start-Sleep -Seconds 3

if ($NoFrontend) {
    Write-Host "已跳过前端启动" -ForegroundColor Yellow
    exit 0
}

Write-Host "==> 启动前端 http://localhost:5173" -ForegroundColor Cyan
Push-Location $frontendDir
try {
    if (-not (Test-Path 'node_modules')) {
        Write-Host "首次运行，安装前端依赖（可能几分钟）..." -ForegroundColor Yellow
        & npm.cmd install
    }
    & npm.cmd run dev
}
finally {
    Pop-Location
}
