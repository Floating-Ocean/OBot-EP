# OBot-EP launcher (API + already-built frontend served by FastAPI).
#
#   .\start.ps1                  # http://127.0.0.1:8000
#   .\start.ps1 -Port 9000       # custom port
#   .\start.ps1 -Rebuild         # force a fresh frontend build first
#   .\start.ps1 -NoBrowser       # do not open a browser
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
    [switch]$Rebuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$webDir = Join-Path $root 'web'
$distDir = Join-Path $webDir 'dist'
$distIndex = Join-Path $distDir 'index.html'

function Test-Port([int]$p) {
    # A failed probe must NOT be read as "port free": doing that is what makes a
    # second instance start and then die with a raw socket error.
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect('127.0.0.1', $p)
            return $true
        } finally {
            $client.Close()
        }
    } catch {
        if ($_.Exception.InnerException -and $_.Exception.InnerException.SocketErrorCode -eq 'ConnectionRefused') {
            return $false
        }
        Write-Host "[x] Could not probe port ${p}: $($_.Exception.Message)" -ForegroundColor Red
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

if (Test-Port $Port) {
    Write-Host "[x] Port $Port is already in use (maybe a backend is already running)." -ForegroundColor Red
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
    Start-Job -ScriptBlock {
        param($url)
        Start-Sleep -Seconds 3
        Start-Process $url
    } -ArgumentList "http://127.0.0.1:$Port" | Out-Null
}

Write-Host ''
Write-Host "[*] Starting backend on http://127.0.0.1:$Port ..." -ForegroundColor Cyan
Write-Host "    Frontend (open this) : http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "    API docs             : http://127.0.0.1:$Port/docs" -ForegroundColor DarkGray
Write-Host '    The initial admin password is printed below on first run.' -ForegroundColor DarkGray
Write-Host '    Ctrl+C stops the server.' -ForegroundColor DarkGray
Write-Host ''

try {
    & $venvPython -m uvicorn server.app:app --host 127.0.0.1 --port $Port --reload
} finally {
    Get-Job | Where-Object { $_.State -eq 'Running' } | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
}
