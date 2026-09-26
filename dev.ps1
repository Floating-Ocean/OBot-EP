# OBot-EP live-preview launcher: FastAPI (8000) + Vite dev server (5173).
#
#   .\dev.ps1                 # start both, open http://127.0.0.1:5173
#   .\dev.ps1 -NoBrowser      # do not open a browser
#   .\dev.ps1 -BackendPort 8010 -WebPort 5174
#
# Open the Vite URL (5173), NOT :8000 — in dev mode :8000 only serves /api,
# Vite serves the frontend and proxies /api to the backend.
#
# Editing anything under web/src hot-reloads in place; backend edits under
# server/ reload thanks to uvicorn --reload.
#
# NOTE: keep every message in this script ASCII/English so terminals without
# CJK fonts do not print mojibake.

param(
    [int]$BackendPort = 8000,
    [int]$WebPort = 5173,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$webDir = Join-Path $root 'web'

if (-not (Test-Path $venvPython)) {
    Write-Host '[x] .venv not found. Run "uv sync" first.' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
    Write-Host '[x] web/node_modules not found. Run "npm install" in web/ first.' -ForegroundColor Red
    exit 1
}

function Test-Port([int]$Port, [switch]$Quiet) {
    # A failed probe must NOT be read as "port free": doing that is what makes a
    # second instance start and then die with a raw socket error.
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect('127.0.0.1', $Port)
            return $true
        } finally {
            $client.Close()
        }
    } catch {
        if ($_.Exception.InnerException -and $_.Exception.InnerException.SocketErrorCode -eq 'ConnectionRefused') {
            return $false
        }
        if (-not $Quiet) {
            Write-Host "[x] Could not probe port ${Port}: $($_.Exception.Message)" -ForegroundColor Red
        }
        exit 1
    }
}

$backendUp = Test-Port $BackendPort -Quiet
$webUp = Test-Port $WebPort

if ($backendUp) {
    Write-Host "[i] Port $BackendPort is already in use - reusing the running backend." -ForegroundColor Yellow
    Write-Host '    (if it is not this project, Vite will proxy to the wrong thing)' -ForegroundColor DarkGray
}

if ($webUp) {
    Write-Host "[x] Port $WebPort is already in use. Close it, or pass -WebPort." -ForegroundColor Red
    exit 1
}

# Vite dev server first, in the background of THIS process, so it dies with it.
if (-not $webUp) {
    Write-Host "[*] Starting Vite dev server on http://127.0.0.1:$WebPort ..." -ForegroundColor Cyan
    $env:OBOT_EP_API = "http://127.0.0.1:$BackendPort"
    $env:OBOT_EP_WEB_PORT = "$WebPort"
    $vite = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', 'npm run dev' `
        -WorkingDirectory $webDir `
        -PassThru -NoNewWindow
}

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($url)
        Start-Sleep -Seconds 4
        Start-Process $url
    } -ArgumentList "http://127.0.0.1:$WebPort" | Out-Null
}

Write-Host ''
Write-Host "    Frontend (open this) : http://127.0.0.1:$WebPort" -ForegroundColor Green
Write-Host "    API (proxied)        : http://127.0.0.1:$BackendPort/api" -ForegroundColor DarkGray
Write-Host "    API docs             : http://127.0.0.1:$BackendPort/docs" -ForegroundColor DarkGray
Write-Host ''
Write-Host '    Ctrl+C stops both.' -ForegroundColor DarkGray
Write-Host ''

try {
    if (-not $backendUp) {
        & $venvPython -m uvicorn server.app:app --host 127.0.0.1 --port $BackendPort --reload
    } else {
        # Backend already running elsewhere: just keep this process (and Vite) alive.
        while ($true) { Start-Sleep -Seconds 3600 }
    }
} finally {
    if ($vite -and -not $vite.HasExited) {
        Write-Host ''
        Write-Host '[*] Stopping Vite ...' -ForegroundColor DarkGray
        # cmd.exe 会再拉起 node，整个进程树一起收掉
        taskkill /PID $vite.Id /T /F 2>&1 | Out-Null
    }
    Get-Job | Where-Object { $_.State -eq 'Running' } | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
}
