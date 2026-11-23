# 启动 Celery worker（消费 Redis 队列）
#
# 用法（项目根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\worker.ps1
#
# 说明：
#   Windows 必须用 --pool=solo（prefork 不兼容）
#   关闭：Ctrl+C；后端与 worker 需要同时运行

param(
    [string]$Python = "",
    [string]$LogLevel = "info"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# 自动选择 Python：显式参数 > 项目 conda 环境 > PATH 中的 python
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
    Write-Host "找不到可用的 Python 解释器，请用 -Python 指定。" -ForegroundColor Red
    exit 1
}

$backendDir = Join-Path $root 'backend'
Write-Host "使用 Python：$Python" -ForegroundColor DarkGray
Write-Host "==> 启动 Celery worker（Redis 队列）" -ForegroundColor Cyan

Push-Location $backendDir
try {
    & $Python -m celery -A app.workers.celery_app:celery_app worker --loglevel=$LogLevel --pool=solo
}
finally {
    Pop-Location
}
