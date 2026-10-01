# OBot-EP live-preview launcher: FastAPI (8000) + Vite dev server (5173).
#
#   .\dev.ps1                 # start both, open http://127.0.0.1:5173
#   .\dev.ps1 -NoBrowser      # do not open a browser
#   .\dev.ps1 -BackendPort 8010 -WebPort 5174
#   .\dev.ps1 -BindAddress 0.0.0.0   # expose the dev preview to the network
#
# Open the Vite URL (5173), NOT :8000 — in dev mode :8000 only serves /api,
# Vite serves the frontend and proxies /api to the backend.
#
# Editing anything under web/src hot-reloads in place; backend edits under
# server/ reload thanks to uvicorn --reload.
#
# SECURITY: the Vite dev server is a *development* server. It has no
# authentication of its own and serves un-minified sources plus the whole
# node_modules tree. -BindAddress 0.0.0.0 hands all of that to the network, so
# it is off by default; use it only on a trusted LAN and never leave it running.
#
# NOTE: keep every message in this script ASCII/English so terminals without
# CJK fonts do not print mojibake.

param(
    [int]$BackendPort = 8000,
    [int]$WebPort = 5173,
    [string]$BindAddress = '127.0.0.1',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$webDir = Join-Path $root 'web'
$bind = $BindAddress

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
    # 上一次 dev.ps1 被强杀（关终端、任务管理器结束进程）时，taskkill 没机会跑，
    # Vite 会留在后台占着端口。此时下一句话如果只是「端口被占用」，人只会更懵。
    Write-Host '    A previous dev.ps1 that was killed the hard way leaves Vite behind. Stop it with:' -ForegroundColor DarkGray
    Write-Host "      Get-NetTCPConnection -LocalPort $WebPort -State Listen |" -ForegroundColor DarkGray
    Write-Host '        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }' -ForegroundColor DarkGray
    exit 1
}

# Vite dev server first, in the background of THIS process, so it dies with it.
if (-not $webUp) {
    Write-Host "[*] Starting Vite dev server on http://${bind}:$WebPort ..." -ForegroundColor Cyan
    $env:OBOT_EP_API = "http://127.0.0.1:$BackendPort"
    $env:OBOT_EP_WEB_PORT = "$WebPort"
    $env:OBOT_EP_WEB_HOST = "$bind"
    $vite = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', 'npm run dev' `
        -WorkingDirectory $webDir `
        -PassThru -NoNewWindow
}

if ($bind -ne '127.0.0.1') {
    Write-Host ''
    Write-Host "    [!] Dev preview bound to $bind - exposed to the network." -ForegroundColor Yellow
    Write-Host '        The Vite dev server has no authentication and serves raw sources.' -ForegroundColor Yellow
    Write-Host '        Stop it when you are done. Use the -Local start.ps1 build for real use.' -ForegroundColor Yellow
}

if (-not $NoBrowser) {
    $browseHost = if ($bind -eq '0.0.0.0') { '127.0.0.1' } else { $bind }
    Start-Job -ScriptBlock {
        param($url)
        Start-Sleep -Seconds 4
        Start-Process $url
    } -ArgumentList "http://${browseHost}:$WebPort" | Out-Null
}

Write-Host ''
Write-Host "    Frontend (open this) : http://${bind}:$WebPort" -ForegroundColor Green
Write-Host "    API (proxied)        : http://${bind}:$WebPort/api" -ForegroundColor DarkGray
Write-Host "    Backend direct       : http://127.0.0.1:$BackendPort/api" -ForegroundColor DarkGray
Write-Host ''
Write-Host '    Ctrl+C stops both.' -ForegroundColor DarkGray
Write-Host ''

try {
    if (-not $backendUp) {
        # 后端始终只绑回环：开发时浏览器走 Vite 代理，不需要把 API 也暴露出去。
        #
        # BIND_HOST 必须显式设成回环地址：应用自己看不到 socket 绑定地址，只认这个
        # 环境变量，拿不到它就一律按「正在对网络提供服务」处理。少了这一行，每一次
        # dev 启动都会刷一整块「Traffic is PLAIN HTTP / anyone can register」的告警 ——
        # 而那是假的，这里根本没有对外监听。
        $env:OBOT_EP_BIND_HOST = '127.0.0.1'
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
