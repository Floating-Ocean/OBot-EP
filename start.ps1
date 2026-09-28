# OBot-EP launcher (API + already-built frontend served by FastAPI).
#
#   .\start.ps1                        # listen on all interfaces, http://<lan-ip>:8000
#   .\start.ps1 -Local                 # loopback only (http://127.0.0.1:8000)
#   .\start.ps1 -BindAddress 10.0.0.5  # bind one specific interface
#   .\start.ps1 -Port 9000             # custom port
#   .\start.ps1 -Rebuild               # force a fresh frontend build first
#   .\start.ps1 -Reload                # auto-restart on backend edits (development)
#   .\start.ps1 -NoBrowser             # do not open a browser
#
# SECURITY: this tool has no transport encryption of its own. Binding to
# 0.0.0.0 means every password, session cookie and data change travels the
# network in cleartext, and anyone who can reach the port can register an
# account and submit changes (set OBOT_EP_ALLOW_REGISTER=0 to close that).
# Only do it on a network you trust, or put an HTTPS reverse proxy in front
# and run with -Local plus OBOT_EP_TRUST_PROXY=1 and OBOT_EP_COOKIE_SECURE=1.
#
# FastAPI serves BOTH the API and the built SPA from web/dist, so web/dist must
# exist and must match web/src. It is gitignored, which means it does NOT travel
# with a clone/pull: every machine has to build it itself, with the toolchain
# pinned in web/package-lock.json. Serving a dist built elsewhere (older Vite /
# vue-router) is how you end up with a frontend that mounts into a blank page,
# so this script refuses to start on a stale dist instead of guessing.
#
# NOTE: keep every message in this script ASCII/English so terminals without
# CJK fonts do not print mojibake.

param(
    [int]$Port = 8000,
    [string]$BindAddress = '',
    [switch]$Local,
    [switch]$Rebuild,
    [switch]$Reload,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$webDir = Join-Path $root 'web'
$distDir = Join-Path $webDir 'dist'
$distIndex = Join-Path $distDir 'index.html'

if ($BindAddress) {
    $bind = $BindAddress
} elseif ($Local) {
    $bind = '127.0.0.1'
} else {
    $bind = '0.0.0.0'
}

function Get-LanAddresses {
    # Addresses a colleague could actually type into a browser. Link-local
    # 169.254.* (an adapter with no DHCP lease) is useless for that, so skip it.
    try {
        return @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress)
    } catch {
        return @()
    }
}

function Test-Port([int]$p, [string]$Address = '127.0.0.1') {
    # A failed probe must NOT be read as "port free": doing that is what makes a
    # second instance start and then die with a raw socket error.
    #
    # Probe the address we are actually about to bind: with a specific interface
    # address, "free on 127.0.0.1" does not mean "free on that interface", and
    # uvicorn would die with a raw socket error instead of our message.
    $probe = if ($Address -eq '0.0.0.0' -or $Address -eq '::') { '127.0.0.1' } else { $Address }
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect($probe, $p)
            return $true
        } finally {
            $client.Close()
        }
    } catch {
        if ($_.Exception.InnerException -and $_.Exception.InnerException.SocketErrorCode -eq 'ConnectionRefused') {
            return $false
        }
        Write-Host "[x] Could not probe ${probe}:${p}: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

function Get-NewestWriteTime([string[]]$paths) {
    $newest = $null
    foreach ($path in $paths) {
        if (-not (Test-Path $path)) { continue }
        $item = Get-Item $path
        if ($item.PSIsContainer) {
            $inner = Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if (-not $inner) { continue }
            $item = $inner
        }
        if (-not $newest -or $item.LastWriteTime -gt $newest) { $newest = $item.LastWriteTime }
    }
    return $newest
}

function Get-DuplicatePackageCopies([string]$package) {
    # Two installed copies of vue / vue-router produce a bundle that *runs* but has two
    # sets of Symbol() injection keys: install() provides one set, useRoute()/useRouter()
    # look up the other, inject() returns undefined and any component reading route.path
    # dies. The bundle looks normal otherwise, so nothing else catches it.
    $root = Join-Path $webDir ('node_modules\' + $package.Replace('/', '\'))
    if (-not (Test-Path $root)) { return @() }
    $dirs = @((Get-Item $root).FullName)
    $nested = @(Get-ChildItem (Join-Path $webDir 'node_modules') -Recurse -Filter 'package.json' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -like "*\node_modules\$($package.Replace('/', '\'))" -and $_.DirectoryName -ne $dirs[0] } |
        Select-Object -ExpandProperty DirectoryName -Unique)
    return @($dirs + $nested | Select-Object -Unique)
}

# ---- dependency sanity: duplicate vue / vue-router copies silently break routing ----
if (Test-Path (Join-Path $webDir 'node_modules')) {
    foreach ($package in 'vue-router', 'vue') {
        $copies = @(Get-DuplicatePackageCopies $package)
        if ($copies.Count -gt 1) {
            Write-Host "[!] $($copies.Count) copies of '$package' are installed:" -ForegroundColor Yellow
            $copies | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
            Write-Host '    A bundle built with duplicates provides one set of injection symbols and' -ForegroundColor Yellow
            Write-Host '    looks up another, so useRoute()/useRouter() return undefined at runtime' -ForegroundColor Yellow
            Write-Host "    (symptom: TypeError ... reading 'path' after login). Fix it with:" -ForegroundColor Yellow
            Write-Host '      cd web; Remove-Item node_modules -Recurse -Force; git checkout -- package-lock.json; npm ci' -ForegroundColor Yellow
            Write-Host '    Then re-run:  .\start.ps1 -Rebuild' -ForegroundColor Yellow
            exit 1
        }
    }
}

if (-not (Test-Path $venvPython)) {
    Write-Host '[x] .venv not found. Run "uv sync" first.' -ForegroundColor Red
    exit 1
}

if (Test-Port $Port $bind) {
    Write-Host "[x] $bind`:$Port is already in use (maybe a backend is already running)." -ForegroundColor Red
    Write-Host '    Stop it, or pass -Port <other>.' -ForegroundColor DarkGray
    exit 1
}

# ---- frontend build: must exist and must be newer than the sources ----
$sourceStamp = Get-NewestWriteTime @(
    (Join-Path $webDir 'src'),
    (Join-Path $webDir 'index.html'),
    (Join-Path $webDir 'package.json'),
    (Join-Path $webDir 'package-lock.json'),
    (Join-Path $webDir 'vite.config.js')
)
$distStamp = if (Test-Path $distIndex) { (Get-Item $distIndex).LastWriteTime } else { $null }

$needBuild = $Rebuild -or (-not $distStamp) -or ($sourceStamp -and $sourceStamp -gt $distStamp)

if ($needBuild) {
    if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
        Write-Host '[x] web/node_modules not found.' -ForegroundColor Red
        Write-Host '    Run "npm ci" in web\ first (it installs the versions pinned in package-lock.json).' -ForegroundColor DarkGray
        exit 1
    }

    $reason = if ($Rebuild) { 'requested with -Rebuild' }
              elseif (-not $distStamp) { 'web/dist is missing' }
              else { 'web/dist is older than web/src' }
    Write-Host "[*] Building frontend ($reason) ..." -ForegroundColor Cyan

    Push-Location $webDir
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Host '[x] Frontend build failed - not starting the backend.' -ForegroundColor Red
            exit 1
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host '[*] web/dist is up to date with web/src.' -ForegroundColor DarkGray
}

if (-not (Test-Path $distIndex)) {
    Write-Host "[x] $distIndex still missing after the build step." -ForegroundColor Red
    exit 1
}

if (-not $NoBrowser) {
    # 0.0.0.0 is not a browsable address; loop back to 127.0.0.1 for the local window
    $browseHost = if ($bind -eq '0.0.0.0') { '127.0.0.1' } else { $bind }
    Start-Job -ScriptBlock {
        param($url)
        Start-Sleep -Seconds 3
        Start-Process $url
    } -ArgumentList "http://${browseHost}:$Port" | Out-Null
}

Write-Host ''
Write-Host "[*] Starting backend on $bind`:$Port ..." -ForegroundColor Cyan

if ($bind -eq '127.0.0.1') {
    Write-Host "    Frontend (open this) : http://127.0.0.1:$Port" -ForegroundColor Green
    Write-Host '    Loopback only: reachable from this machine.' -ForegroundColor DarkGray
} else {
    $lanAddresses = Get-LanAddresses
    if ($lanAddresses.Count -gt 0) {
        Write-Host '    Frontend (open this) :' -ForegroundColor Green
        foreach ($address in $lanAddresses) {
            Write-Host "        http://${address}:$Port" -ForegroundColor Green
        }
    } else {
        Write-Host "    Frontend (open this) : http://<this-host-ip>:$Port" -ForegroundColor Green
    }
    Write-Host ''
    Write-Host '    [!] Listening on every interface, over plain HTTP.' -ForegroundColor Yellow
    Write-Host '        Passwords, session cookies and data changes are NOT encrypted.' -ForegroundColor Yellow
    Write-Host '        Anyone who can reach this port can register and submit changes.' -ForegroundColor Yellow
    Write-Host '        Use -Local for loopback only, or put an HTTPS reverse proxy in front.' -ForegroundColor Yellow
    Write-Host '        See README "Listen on the network" for the checklist.' -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '    The initial admin password is printed below on first run.' -ForegroundColor DarkGray
Write-Host '    Ctrl+C stops the server.' -ForegroundColor DarkGray
Write-Host ''

try {
    # 让应用自己知道绑在哪个地址上，启动时才能给出「正在对网络提供服务」的告警
    $env:OBOT_EP_BIND_HOST = $bind
    # 长期运行的服务默认不开 --reload：它常驻监视整个项目并在文件变动时重启，
    # 既拖慢请求，也会让任何能写文件的人拥有「重启服务」的能力。开发时用 -Reload。
    $uvicornArgs = @('-m', 'uvicorn', 'server.app:app', '--host', $bind, '--port', "$Port")
    if ($Reload) { $uvicornArgs += '--reload' }
    & $venvPython @uvicornArgs
} finally {
    Get-Job | Where-Object { $_.State -eq 'Running' } | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
}
