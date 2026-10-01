# OBot-EP verification gate: run this after ANY change, and before claiming done.
#
#   .\check.ps1              # compact: one line per step, full output only on failure
#   .\check.ps1 -Verbose     # always print each step's full output
#   .\check.ps1 -Fast        # skip the frontend build (backend-only change)
#
# Why one script instead of "run these four commands":
#   a fixed, ordered gate means nobody has to guess which checks exist, and a
#   failure always points at the step that produced it. The compact output keeps
#   a passing run to a handful of lines; a failing run prints the whole log of
#   the step that failed, which is exactly the part worth reading.
#
# NOTE: keep every message in this script ASCII/English so terminals without
# CJK fonts do not print mojibake. The test scripts re-encode their own output.

param(
    [switch]$Fast,
    [switch]$Verbose
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$failures = @()
$step = 0
$total = 0

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body, [switch]$ShowOutput)

    $script:step++
    $script:total++
    Write-Host ("[{0}] {1} ... " -f $script:step, $Name) -NoNewline -ForegroundColor Cyan

    $output = ''
    $ok = $true
    try {
        $output = (& $Body 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) { $ok = $false }
    } catch {
        $ok = $false
        $output += $_ | Out-String
    }

    if ($ok) {
        Write-Host 'ok' -ForegroundColor Green
        if ($ShowOutput) { Write-Host $output }
        return
    }

    Write-Host 'FAILED' -ForegroundColor Red
    Write-Host $output
    $script:failures += $Name
}

# -ShowOutput:$Verbose 而不是让函数去读外层作用域：依赖显式传参，分析器也能看懂
Invoke-Step 'Lint (ruff)' -ShowOutput:$Verbose {
    & uv run ruff check .
}

Invoke-Step 'PowerShell lint (PSScriptAnalyzer)' -ShowOutput:$Verbose {
    if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) {
        # 不是每个环境都装了它，而且装它要联网。缺了就跳过，不能让整个门禁挂掉。
        Write-Host '    PSScriptAnalyzer not installed - skipped.'
        Write-Host '    Install with: Install-Module PSScriptAnalyzer -Scope CurrentUser'
        return
    }
    Import-Module PSScriptAnalyzer
    $findings = @(
        Invoke-ScriptAnalyzer -Path $root -Recurse -Settings (Join-Path $root 'PSScriptAnalyzerSettings.psd1')
    )
    if ($findings.Count -gt 0) {
        $findings | ForEach-Object {
            Write-Host "    $($_.Severity) $($_.RuleName) $($_.ScriptName):$($_.Line)"
            Write-Host "      $($_.Message)"
        }
        throw "$($findings.Count) PowerShell lint finding(s)"
    }
}

Invoke-Step 'Plugin contract (server.inspect check)' -ShowOutput:$Verbose {
    & uv run python -m server.inspect check
}

Invoke-Step 'Scaffold round trip (tests/scaffold_test.py)' -ShowOutput:$Verbose {
    & uv run python tests/scaffold_test.py
}

Invoke-Step 'Backend smoke (tests/smoke_test.py)' -ShowOutput:$Verbose {
    & uv run python tests/smoke_test.py
}

Invoke-Step 'Security (tests/security_test.py)' -ShowOutput:$Verbose {
    & uv run python tests/security_test.py
}

if (-not $Fast) {
    # The backend serves web/dist, so a frontend change is not "done" until it builds.
    Invoke-Step 'Frontend build (npm run build)' -ShowOutput:$Verbose {
        Push-Location (Join-Path $root 'web')
        try {
            & npm run build
        } finally {
            Pop-Location
        }
    }
}

Write-Host ''
if ($failures.Count -eq 0) {
    Write-Host "ALL $total CHECKS PASSED" -ForegroundColor Green
    exit 0
}

Write-Host "FAILED $($failures.Count)/$total : $($failures -join ', ')" -ForegroundColor Red
exit 1
