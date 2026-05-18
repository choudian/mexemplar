<#
.SYNOPSIS
  Exemplar 开发环境一键启动脚本（前后端联调模式）
#>

$ErrorActionPreference = "Stop"

$HostAddr = "127.0.0.1"
$Port = 18080
$FrontendPort = 1420
$Token = "dev"
$ApiBase = "http://${HostAddr}:${Port}"
$Root = $PSScriptRoot
$BackendScript = Join-Path $env:TEMP "exemplar-backend-dev.ps1"
$FrontendScript = Join-Path $env:TEMP "exemplar-frontend-dev.ps1"

function Test-PortListening {
    param([int]$LocalPort)
    return @(Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue).Count -gt 0
}

function Get-PortProcessIds {
    param([int]$LocalPort)
    return @(Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { $_ -and $_ -gt 0 })
}

function Wait-PortReleased {
    param(
        [int]$LocalPort,
        [int]$TimeoutMs = 5000
    )

    $waited = 0
    while ($waited -lt $TimeoutMs) {
        if (-not (Test-PortListening $LocalPort)) { return $true }
        Start-Sleep -Milliseconds 200
        $waited += 200
    }

    return -not (Test-PortListening $LocalPort)
}

function Wait-PortListening {
    param(
        [int]$LocalPort,
        [int]$TimeoutMs = 10000
    )

    $waited = 0
    while ($waited -lt $TimeoutMs) {
        if (Test-PortListening $LocalPort) { return $true }
        Start-Sleep -Milliseconds 250
        $waited += 250
    }

    return Test-PortListening $LocalPort
}

function Start-DevWindow {
    param([string]$ScriptPath)
    Start-Process -FilePath "pwsh" -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$ScriptPath`"")
}

function Start-Backend {
    Write-Host "[backend] Starting Python sidecar..." -ForegroundColor Yellow
    @"
`$env:MEXEMPLAR_DESKTOP_TOKEN='$Token'
Set-Location '$Root'
Write-Host '[backend] Sidecar on $ApiBase' -ForegroundColor Green
uv run python -m src.desktop_api --host $HostAddr --port $Port --verbose
"@ | Set-Content $BackendScript -Encoding UTF8
    Start-DevWindow $BackendScript
}

function Start-Frontend {
    Write-Host "[frontend] Starting Vite dev server..." -ForegroundColor Yellow
    @"
`$env:VITE_MEXEMPLAR_API_BASE_URL='$ApiBase'
`$env:VITE_MEXEMPLAR_SESSION_TOKEN='$Token'
Set-Location '$Root\frontend'
Write-Host '[frontend] Vite connecting to $ApiBase' -ForegroundColor Green
npm run dev
"@ | Set-Content $FrontendScript -Encoding UTF8
    Start-DevWindow $FrontendScript
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Exemplar Dev Environment" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Backend : $ApiBase" -ForegroundColor Gray
Write-Host "  Token   : $Token" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$mutex = [System.Threading.Mutex]::new($false, "Exemplar.Dev.Startup")
$hasMutex = $false
try {
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) {
        Write-Host "[dev] Another dev.ps1 startup is already in progress; skipping this run." -ForegroundColor DarkYellow
        return
    }

    $backendUp = Test-PortListening $Port
    $frontendUp = Test-PortListening $FrontendPort
    $startFrontend = (-not $backendUp) -and (-not $frontendUp)

    # ---- 后端：如果端口被占用就先杀掉，然后启动 ----
    if ($backendUp) {
        $oldPids = Get-PortProcessIds $Port
        foreach ($procId in $oldPids) {
            Write-Host "[backend] Killing PID $procId (tree) on port $Port" -ForegroundColor DarkYellow
            taskkill /PID $procId /T /F 2>$null
            if (-not $?) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
        }

        if (-not (Wait-PortReleased $Port 5000)) {
            Write-Host "[backend] WARNING: port $Port still in use after 5s" -ForegroundColor Red
        }
    }

    Start-Backend

    # ---- 前端：只在脚本入口时两个端口都空闲的冷启动场景启动 ----
    if ($startFrontend) {
        if (-not (Wait-PortListening $Port 10000)) {
            Write-Host "[backend] WARNING: port $Port did not start listening within 10s; starting frontend anyway." -ForegroundColor DarkYellow
        }
        Start-Frontend
    } elseif ($frontendUp) {
        Write-Host "[frontend] Already running on port $FrontendPort, skipping." -ForegroundColor DarkGray
    } else {
        Write-Host "[frontend] Skipping because this run is a backend restart." -ForegroundColor DarkGray
    }
} finally {
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

Write-Host ""
