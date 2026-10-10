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

# ---- PSScriptAnalyzer 配置 ----
#
# 原先放在单独的 PSScriptAnalyzerSettings.psd1 里，但只有这个脚本用它 —— 为一个
# 排除清单多养一个文件不划算，所以内联成哈希表（-Settings 收路径也收哈希表）。
# 排除的规则都是「对这类脚本不适用」，不是「懒得修」——每条都写清楚为什么，
# 这样下一个人（或 Agent）不必重新判断一遍。
$analyzerSettings = @{
    Severity = @('Error', 'Warning')

    ExcludeRules = @(
        # 面向人的交互式启动脚本：彩色输出、-NoNewline 进度、不被管道吞掉，
        # 正是 Write-Host 的用途。改成 Write-Output 反而会把这些行塞进管道。
        'PSAvoidUsingWriteHost'

        # Start-Job 的脚本块用 param() + -ArgumentList 接收参数，这是官方支持的写法，
        # 分析器只认 $using: 那一种，属于误报。
        'PSUseUsingScopeModifierInNewRunspaces'

        # Get-LanAddresses / Get-DuplicatePackageCopies 是脚本内的私有函数，不是导出的
        # cmdlet，单复数约定在这里没有意义（改了反而更难读）。
        'PSUseSingularNouns'

        # 这些文件里的中文只出现在注释，所有输出字符串都是 ASCII 英文。
        # PS 7 默认按 UTF-8 读取，不需要 BOM；加 BOM 反而会让 diff/grep 变脏。
        'PSUseBOMForUnicodeEncodedFile'
    )
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
        Invoke-ScriptAnalyzer -Path $root -Recurse -Settings $analyzerSettings
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
