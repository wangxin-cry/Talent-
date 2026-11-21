# Start backend dev server (auto-detects the best Python interpreter)
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1 -Background
#   powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1 -Python "C:\path\python.exe"
#
# Why this script exists:
#   1) --reload on Windows leaves orphan multiprocessing workers holding the port,
#      which shows up as "port is up but routes are old". We clear the port first.
#   2) faiss-cpu lives in a specific conda env. Picking the wrong interpreter
#      silently degrades RAG to numpy. We score interpreters and pick the best.
#
# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 mis-parses UTF-8
#       scripts without BOM, and non-ASCII text breaks quoting.

param(
    [int]$Port = 8000,
    [string]$HostAddr = "127.0.0.1",
    [string]$Python = "",
    [switch]$Background,
    [switch]$Reload
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root 'backend'

function Test-Interpreter {
    param([string]$exe, [string]$tag)
    if (-not $exe) { return $null }
    if (-not (Test-Path -LiteralPath $exe)) { return $null }

    $code = "import importlib.util,sys;mods=['fastapi','sqlalchemy','uvicorn','aiosqlite','asyncpg','minio','loguru','pydantic_settings'];missing=[m for m in mods if importlib.util.find_spec(m) is None];print('%s|%d|%d|%s' % (sys.version.split()[0], int(len(missing)==0), int(importlib.util.find_spec('faiss') is not None), ','.join(missing)))"
    $probe = & $exe -c $code 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $probe) { return $null }

    $parts = ([string]$probe).Trim() -split '\|'
    if ($parts.Count -lt 4) { return $null }

    return [pscustomobject]@{
        Exe      = $exe
        Tag      = $tag
        Version  = $parts[0]
        Complete = ($parts[1] -eq '1')
        Faiss    = ($parts[2] -eq '1')
        Missing  = $parts[3]
    }
}

# ---------------- pick interpreter ----------------
$candidates = @()

if ($Python -ne "") {
    $one = Test-Interpreter -exe $Python -tag "explicit"
    if ($one) { $candidates += $one }
    else {
        Write-Host "ERROR: given python is missing or incomplete: $Python" -ForegroundColor Red
        exit 1
    }
} else {
    $known = @(
        @{ exe = "D:\ProgramData\miniconda3\envs\agent\python.exe"; tag = "conda:agent" },
        @{ exe = "D:\ProgramData\miniconda3\envs\py311\python.exe"; tag = "conda:py311" }
    )
    foreach ($k in $known) {
        $info = Test-Interpreter -exe $k.exe -tag $k.tag
        if ($info) { $candidates += $info }
    }
    $pathPy = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($pathPy) {
        $info = Test-Interpreter -exe $pathPy -tag "PATH"
        if ($info) { $candidates += $info }
    }
}

if (-not $candidates) {
    Write-Host "ERROR: no usable Python found (need fastapi/sqlalchemy/aiosqlite etc.)" -ForegroundColor Red
    Write-Host 'Use -Python "C:\path\to\python.exe" to specify one.' -ForegroundColor Yellow
    exit 1
}

$best = $candidates |
    Sort-Object @{ Expression = { $_.Complete }; Descending = $true },
                  @{ Expression = { $_.Faiss }; Descending = $true } |
    Select-Object -First 1

$Python = $best.Exe
Write-Host "interpreter: $($best.Tag) -> $Python" -ForegroundColor Cyan
Write-Host "  python $($best.Version) | faiss=$($best.Faiss)" -ForegroundColor DarkGray
if (-not $best.Complete) {
    Write-Host "  WARN: missing deps: $($best.Missing)" -ForegroundColor Yellow
}
if (-not $best.Faiss) {
    Write-Host "  WARN: no faiss-cpu here; RAG will fall back to numpy" -ForegroundColor Yellow
}

# ---------------- free the port ----------------
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    foreach ($p in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -eq $p }

        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        $name = 'exited'
        if ($proc) { $name = $proc.ProcessName }
        Write-Host "freeing port $Port : stop PID=$p ($name)" -ForegroundColor Yellow
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue

        foreach ($child in $children) {
            if ($child.ProcessId) {
                Write-Host "  stop child PID=$($child.ProcessId)" -ForegroundColor DarkYellow
                Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Seconds 2

    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'spawn_main|uvicorn' } |
            ForEach-Object {
                Write-Host "  stop orphan PID=$($_.ProcessId)" -ForegroundColor DarkYellow
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        Start-Sleep -Seconds 2
    }
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "ERROR: port $Port is still in use" -ForegroundColor Red
    exit 1
}

# ---------------- start ----------------
New-Item -ItemType Directory -Force -Path (Join-Path $root 'data') | Out-Null

$uvArgs = @('-m', 'uvicorn', 'app.main:app', '--host', $HostAddr, '--port', "$Port")
if ($Reload) { $uvArgs += '--reload' }

Write-Host "starting backend: http://$HostAddr`:$Port  (docs: /docs)" -ForegroundColor Cyan

if ($Background) {
    $proc = Start-Process -FilePath $Python -ArgumentList $uvArgs `
        -WorkingDirectory $backendDir -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5

    try {
        $resp = Invoke-WebRequest -Uri "http://$HostAddr`:$Port/api/v1/healthz" -UseBasicParsing -TimeoutSec 15
        $body = $resp.Content | ConvertFrom-Json
        Write-Host "health: $($body.status) | db=$($body.components.database.ok) storage=$($body.components.storage.ok)" -ForegroundColor Green
        Write-Host "PID=$($proc.Id)  (stop: Stop-Process -Id $($proc.Id) -Force)" -ForegroundColor DarkGray
    } catch {
        Write-Host "WARN: health check failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "run without -Background to see startup logs" -ForegroundColor Yellow
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
