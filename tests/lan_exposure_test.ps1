# End-to-end verification over the real network stack (0.0.0.0 bind).
#
# Runs the actual uvicorn process, then talks to it over HTTP on both the
# loopback address and the machine's LAN address, exactly as a browser on
# another machine would. Exercises the security controls added for network
# exposure: CSRF origin guard, session cookie handling, body cap, rate limit.
#
# NOTE: keep every message ASCII/English (no CJK fonts in some terminals).

param(
    [int]$Port = 8123,
    [string]$Password = 'lanadmin12345'
)

$ErrorActionPreference = 'Stop'
# 脚本在 tests\ 下，项目根目录是它的上一级
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$dataDir = Join-Path $env:TEMP 'ep-lan-verify'
$logOut = Join-Path $env:TEMP 'ep-lan-verify-server.out.log'
$logErr = Join-Path $env:TEMP 'ep-lan-verify-server.err.log'

$passed = 0
$failed = 0

function Check([string]$Label, [bool]$Condition, [string]$Detail = '') {
    if ($Condition) {
        Write-Host "  [PASS] $Label"
        $script:passed++
    } else {
        Write-Host "  [FAIL] $Label $Detail" -ForegroundColor Red
        $script:failed++
    }
}

function Get-LanAddress {
    $address = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1 -ExpandProperty IPAddress
    return $address
}

function Invoke-Api {
    # Returns @{ Status = <int>; Body = <string> } and never throws on 4xx/5xx.
    param(
        [string]$Url,
        [string]$Method = 'GET',
        [string]$Body = '',
        [hashtable]$Headers = @{},
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session
    )
    $args = @{
        Uri             = $Url
        Method          = $Method
        UseBasicParsing = $true
        TimeoutSec      = 10
        Headers         = $Headers
    }
    if ($Body) { $args['Body'] = $Body; $args['ContentType'] = 'application/json' }
    if ($Session) { $args['WebSession'] = $Session }
    try {
        $r = Invoke-WebRequest @args
        return @{ Status = [int]$r.StatusCode; Body = $r.Content; Response = $r }
    } catch {
        # PowerShell 7 把错误响应放在 ErrorDetails 上（异常里没有 GetResponseStream）
        $response = $_.Exception.Response
        if (-not $response) {
            return @{ Status = 0; Body = $_.Exception.Message; Response = $null }
        }
        $status = [int]$response.StatusCode
        $text = $_.ErrorDetails.Message
        if (-not $text) {
            try {
                $stream = $response.GetResponseStream()
                $text = (New-Object System.IO.StreamReader($stream)).ReadToEnd()
            } catch {
                $text = ''
            }
        }
        return @{ Status = $status; Body = $text; Response = $response }
    }
}

function Test-RawNonAsciiCookie {
    # 用原始 socket 发一个带高位字节的 Cookie：PowerShell 的 HTTP 客户端自己就会
    # 拒绝非 ASCII 头，只有 raw socket 能真正把这种请求送到服务端。
    param([string]$Target, [int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect($Target, $Port)
        $stream = $client.GetStream()
        $request = "GET /api/auth/me HTTP/1.1`r`nHost: ${Target}:${Port}`r`nCookie: obot_ep_session=YWJj." + [char]0xff + "`r`nConnection: close`r`n`r`n"
        $bytes = [System.Text.Encoding]::GetEncoding(28591).GetBytes($request)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        $reader = New-Object System.IO.StreamReader($stream)
        $response = $reader.ReadToEnd()
        return $response -match '^HTTP/1\.1 401'
    } finally {
        if ($client) { $client.Close() }
    }
}

# ---------------------------------------------------------------- start server
Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$env:OBOT_EP_BIND_HOST = '0.0.0.0'
$env:OBOT_EP_DATA_DIR = $dataDir
$env:OBOT_EP_ADMIN_PASSWORD = $Password
$env:OBOT_EP_SECRET = 'lan-verify-secret'
$env:OBOT_EP_ALLOW_REGISTER = '1'

$server = Start-Process -FilePath $venvPython `
    -ArgumentList @('-m', 'uvicorn', 'server.app:app', '--host', '0.0.0.0', '--port', "$Port") `
    -WorkingDirectory $root -PassThru -NoNewWindow `
    -RedirectStandardOutput $logOut -RedirectStandardError $logErr

try {
    $ready = $false
    foreach ($attempt in 1..40) {
        Start-Sleep -Milliseconds 500
        $probe = Invoke-Api -Url "http://127.0.0.1:$Port/api/health"
        if ($probe.Status -eq 200) { $ready = $true; break }
    }
    if (-not $ready) {
        throw "server did not come up; log:`n$(Get-Content $logErr -Raw -ErrorAction SilentlyContinue)"
    }

    $lan = Get-LanAddress
    Write-Host "`n== Reachability (0.0.0.0 bind, LAN address $lan) =="
    $socket = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    Check 'listening on all interfaces' ($socket.LocalAddress -contains '0.0.0.0') ($socket.LocalAddress -join ',')

    foreach ($target in @('127.0.0.1', $lan)) {
        if (-not $target) { continue }
        $base = "http://${target}:$Port"
        $r = Invoke-Api -Url "$base/api/health"
        Check "health reachable via ${target}" ($r.Status -eq 200) "$($r.Status)"
    }
    $base = "http://${lan}:$Port"

    Write-Host "`n== Docs are not exposed =="
    foreach ($path in @('/docs', '/redoc', '/openapi.json')) {
        $r = Invoke-Api -Url "$base$path"
        $looksLikeSpa = $r.Body -match '<!doctype html>' -and $r.Body -notmatch 'swagger'
        Check "$path is not served as docs" $looksLikeSpa "$($r.Status)"
    }

    Write-Host "`n== SPA is served over the LAN =="
    $r = Invoke-Api -Url "$base/"
    Check 'index.html served' ($r.Status -eq 200 -and $r.Body -match '<div id="app">') "$($r.Status)"
    $asset = [regex]::Match($r.Body, 'src="(/assets/[^"]+)"').Groups[1].Value
    if ($asset) {
        $a = Invoke-Api -Url "$base$asset"
        Check 'hashed JS bundle served' ($a.Status -eq 200) "$($a.Status)"
    } else {
        Check 'hashed JS bundle referenced' $false 'no script tag found'
    }

    Write-Host "`n== Login + session over the LAN =="
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $body = @{ username = 'admin'; password = $Password } | ConvertTo-Json -Compress
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST -Body $body -Session $session `
        -Headers @{ Origin = $base }
    Check 'login succeeds with matching Origin' ($r.Status -eq 200) "$($r.Status) $($r.Body)"
    $cookie = $session.Cookies.GetCookies($base)['obot_ep_session']
    Check 'session cookie issued' ($null -ne $cookie) 'no cookie'
    if ($cookie) {
        Check 'cookie is HttpOnly' ($cookie.HttpOnly) 'HttpOnly not set'
    }

    $r = Invoke-Api -Url "$base/api/meta/info" -Session $session
    Check 'session authenticates a follow-up request' ($r.Status -eq 200) "$($r.Status)"

    Write-Host "`n== CSRF origin guard (network client) =="
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST -Body $body `
        -Headers @{ Origin = 'http://evil.example' }
    Check 'cross-site login rejected' ($r.Status -eq 403) "$($r.Status)"
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST -Body $body `
        -Headers @{ Origin = 'null' }
    Check 'Origin: null rejected' ($r.Status -eq 403) "$($r.Status)"
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST -Body $body `
        -Headers @{ Referer = 'http://evil.example/login' }
    Check 'cross-site referer rejected' ($r.Status -eq 403) "$($r.Status)"

    Write-Host "`n== Abuse paths =="
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST `
        -Body (@{ username = 'admin'; password = 'wrong' } | ConvertTo-Json -Compress)
    Check 'wrong password is 401' ($r.Status -eq 401) "$($r.Status)"
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST `
        -Body (@{ username = 'nobody'; password = 'wrong' } | ConvertTo-Json -Compress)
    Check 'unknown user is 401' ($r.Status -eq 401) "$($r.Status)"

    $huge = 'a' * 300000
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST `
        -Body (@{ username = $huge; password = $huge } | ConvertTo-Json -Compress)
    Check 'oversized body rejected' ($r.Status -eq 413) "$($r.Status)"

    # Unknown username twice more so the per-IP failure budget (default 10) trips
    foreach ($i in 1..12) {
        $r = Invoke-Api -Url "$base/api/auth/login" -Method POST `
            -Body (@{ username = "bruteforce$i"; password = 'wrong' } | ConvertTo-Json -Compress)
        if ($r.Status -eq 429) { break }
    }
    Check 'brute force gets rate limited (429)' ($r.Status -eq 429) "$($r.Status)"

    Write-Host "`n== Malformed input resilience =="
    Check 'non-ASCII cookie is 401, not 500' (Test-RawNonAsciiCookie -Target $lan -Port $Port) 'see raw socket check'
    $r = Invoke-Api -Url "$base/api/auth/login" -Method POST -Body $body `
        -Headers @{ Origin = 'http://x:99999' }
    Check 'malformed Origin is not a 500' ($r.Status -ne 500) "$($r.Status)"

    Write-Host "`n== Exposure warnings in the log =="
    Start-Sleep -Milliseconds 300
    $log = (Get-Content $logErr -Raw -ErrorAction SilentlyContinue)
    Check 'warns about plain HTTP' ($log -match 'PLAIN HTTP') 'missing'
    Check 'warns about open registration' ($log -match 'Self-registration is OPEN') 'missing'
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
    Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
}

Write-Host "`n$('=' * 60)"
Write-Host "passed $passed, failed $failed"
if ($failed -gt 0) { exit 1 }
