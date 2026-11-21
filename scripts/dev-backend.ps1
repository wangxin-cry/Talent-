# 启动后端（自动清理旧进程，避免"改了代码但服务还是旧的"）
#
# 用法（项目根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1 -Background   # 后台启动
#   powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1 -Port 8001
#
# 行为：
#   1) 释放目标端口上已有的进程（含 uvicorn --reload 遗留的 multiprocessing 子进程）
#   2) 用当前代码启动 uvicorn（默认不开 --reload，Windows 下更稳）
#
# 为什么不用 --reload：
#   Windows 下 --reload 的父进程被杀后会留下孤儿 worker 占着端口，
#   表现为"端口还在、但接口是旧的"，排查成本高。

param(
    [int]$Port = 8000,
    [string]$HostAddr = "127.0.0.1",
    [string]$Python = "D:\ProgramData\miniconda3\envs\py311\python.exe",
    [switch]$Background,
    [switch]$Reload
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root 'backend'

if (-not (Test-Path -LiteralPath $Python)) {
    $fallback = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($fallback) {
        $Python = $fallback
        Write-Host "使用 PATH 中的 python：$Python" -ForegroundColor Yellow
    } else {
        Write-Host "找不到 Python：$Python" -ForegroundColor Red
        Write-Host '请用 -Python "C:\path\to\python.exe" 指定' -ForegroundColor Yellow
        exit 1
    }
}

# ---------------- 1) 释放端口 ----------------
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    foreach ($p in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        # 先记录子进程（uvicorn reload 的 worker 是 multiprocessing 子进程）
        $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -eq $p }

        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        $name = '已退出'
        if ($proc) { $name = $proc.ProcessName }
        Write-Host "释放端口 $Port：停止 PID=$p ($name)" -ForegroundColor Yellow
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue

        foreach ($child in $children) {
            if ($child.ProcessId) {
                Write-Host "  清理子进程 PID=$($child.ProcessId)" -ForegroundColor DarkYellow
                Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Seconds 2

    # 仍占用说明还有孤儿 worker，按命令行特征再清一次
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'spawn_main|uvicorn' } |
            ForEach-Object {
                Write-Host "  清理残留进程 PID=$($_.ProcessId)" -ForegroundColor DarkYellow
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        Start-Sleep -Seconds 2
    }
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "端口 $Port 仍被占用，请手动处理后重试" -ForegroundColor Red
    exit 1
}

# ---------------- 2) 启动 ----------------
New-Item -ItemType Directory -Force -Path (Join-Path $root 'data') | Out-Null

$uvArgs = @('-m', 'uvicorn', 'app.main:app', '--host', $HostAddr, '--port', "$Port")
if ($Reload) { $uvArgs += '--reload' }

Write-Host "启动后端：http://$HostAddr`:$Port  （docs: /docs）" -ForegroundColor Cyan

if ($Background) {
    $proc = Start-Process -FilePath $Python -ArgumentList $uvArgs `
        -WorkingDirectory $backendDir -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 4

    try {
        $resp = Invoke-WebRequest -Uri "http://$HostAddr`:$Port/api/v1/healthz" -UseBasicParsing -TimeoutSec 10
        $body = $resp.Content | ConvertFrom-Json
        Write-Host "健康检查：$($body.status) | db=$($body.components.database.ok) storage=$($body.components.storage.ok)" -ForegroundColor Green
        Write-Host "PID=$($proc.Id)（停止：Stop-Process -Id $($proc.Id) -Force）" -ForegroundColor DarkGray
    } catch {
        Write-Host "启动后健康检查失败：$($_.Exception.Message)" -ForegroundColor Red
        Write-Host "可能是启动报错，请改用前台模式查看日志" -ForegroundColor Yellow
        exit 1
    }
} else {
    Push-Location $backendDir
    try {
        & $Python @uvArgs
    } finally {
        Pop-Location
    }
}
