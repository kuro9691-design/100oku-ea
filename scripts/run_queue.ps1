# Codex continuous queue runner. PowerShell obtains one selected Notion item from a
# small selector session, then gives only that item to one fresh worker session.
param(
    [switch]$DryRun,
    [string[]]$TestSelections = @(),
    [string[]]$TestOutputs = @(),
    [string]$TestHarnessRoot = '',
    [datetimeoffset]$TestNow,
    [ValidateRange(0, 2147483647)][int]$MaxItems = 0,
    [string]$PageId = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Share = 'C:\Users\user\Documents\100億j_share'
$DriveRoot = 'G:\マイドライブ\100億'
$LogDir = Join-Path $Root 'logs'
$StopFile = Join-Path $PSScriptRoot 'STOP_RUN_QUEUE'
$WakeFile = Join-Path $PSScriptRoot 'WAKE_RUN_QUEUE'
$RecoveryFile = Join-Path $LogDir 'queue_recovery.txt'
$QueueEmptyFile = Join-Path $LogDir 'queue_empty_at.txt'
$SelectorPromptFile = Join-Path $PSScriptRoot 'queue_select_prompt.md'
$WorkerPromptFile = Join-Path $PSScriptRoot 'queue_prompt.md'
$SchemaFile = Join-Path $PSScriptRoot 'queue_selection_schema.json'
if ($DryRun -and $TestHarnessRoot) {
    $Share = Join-Path $TestHarnessRoot 'share'
    $DriveRoot = Join-Path $TestHarnessRoot 'drive'
    $LogDir = Join-Path $TestHarnessRoot 'logs'
    $StopFile = Join-Path $TestHarnessRoot 'scripts\STOP_RUN_QUEUE'
    $WakeFile = Join-Path $TestHarnessRoot 'scripts\WAKE_RUN_QUEUE'
    $RecoveryFile = Join-Path $LogDir 'queue_recovery.txt'
    $QueueEmptyFile = Join-Path $LogDir 'queue_empty_at.txt'
}
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Log = Join-Path $LogDir "queue_$Stamp.log"
$Lock = Join-Path $LogDir 'queue.lock'
$Heartbeat = Join-Path $LogDir 'queue_heartbeat.txt'
$CodexExe = $null
if (-not $DryRun) {
    $CodexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($CodexCommand) {
        $CodexExe = $CodexCommand.Source
    } else {
        $CodexBin = Join-Path $env:USERPROFILE 'AppData\Local\OpenAI\Codex\bin'
        $CodexExe = Get-ChildItem -LiteralPath $CodexBin -Filter codex.exe -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $CodexExe) { throw 'codex.exe was not found' }
}

function Get-QueueNow {
    if ($DryRun -and $TestHarnessRoot -and $TestNow -ne [datetimeoffset]::MinValue) {
        return $TestNow
    }
    return [datetimeoffset]::Now
}

function Get-QueueThrottleDecision {
    $raw = if (Test-Path -LiteralPath $QueueEmptyFile) {
        (Get-Content -Raw -Encoding UTF8 -LiteralPath $QueueEmptyFile).Trim()
    } else { '' }
    if (-not $raw) {
        return @{ InvokeSelector = $true; EmptyAt = $null; WakeRequested = $false }
    }

    $emptyAt = [datetimeoffset]::MinValue
    if (-not [datetimeoffset]::TryParse($raw, [ref]$emptyAt)) {
        return @{ InvokeSelector = $true; EmptyAt = $null; WakeRequested = $false }
    }

    $newInstruction = @(Get-ChildItem -LiteralPath $Share -Filter '指示_*.md' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTimeUtc -gt $emptyAt.UtcDateTime }).Count -gt 0
    $wakeRequested = $false
    if (Test-Path -LiteralPath $WakeFile) {
        $wake = Get-Item -LiteralPath $WakeFile
        $wakeRequested = $wake.Length -gt 0 -or $wake.LastWriteTimeUtc -gt $emptyAt.UtcDateTime
    }
    $threeHoursElapsed = (Get-QueueNow) -ge $emptyAt.AddHours(3)
    return @{
        InvokeSelector = $newInstruction -or $wakeRequested -or $threeHoursElapsed
        EmptyAt = $emptyAt
        WakeRequested = $wakeRequested
    }
}

function Clear-QueueEmptyState {
    Set-Content -LiteralPath $QueueEmptyFile -Value '' -Encoding UTF8
}

function Set-QueueEmptyState {
    Set-Content -LiteralPath $QueueEmptyFile -Value ((Get-QueueNow).ToString('o')) -Encoding UTF8
}

function Write-Log([string]$Text) {
    $line = "[{0}] [pid {1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID, $Text
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
    Set-Content -LiteralPath $Heartbeat -Value $line -Encoding UTF8
}

function Invoke-Codex([string]$PromptText, [string]$Kind, [string]$OutputSchema = '') {
    $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $lastMessage = Join-Path $LogDir ("queue_{0}_{1}_{2}.txt" -f $Kind, $PID, (Get-Date -Format 'HHmmssfff'))
    # Drive context is read by this PowerShell process and injected into the
    # prompt. Passing a mapped G: drive to Codex's Windows sandbox causes
    # `setup refresh had errors`, so the worker only receives the share folder.
    $arguments = @('exec', '--ephemeral', '--approve-for-me', '-C', $Root, '--add-dir', $Share, '-o', $lastMessage)
    if ($Kind -eq 'selector') { $arguments += @('-c', 'model_reasoning_effort="low"') }
    if ($OutputSchema) { $arguments += @('--output-schema', $OutputSchema) }
    $arguments += '-'
    Push-Location $Root
    $ErrorActionPreference = 'Continue'
    try {
        $output = @($PromptText | & $CodexExe @arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = 'Stop'
        Pop-Location
    }
    $output | ForEach-Object { Add-Content -LiteralPath $Log -Value $_ -Encoding UTF8 }
    $final = if (Test-Path -LiteralPath $lastMessage) {
        Get-Content -Raw -Encoding UTF8 -LiteralPath $lastMessage
    } else { $output -join "`n" }
    Write-Log "$Kind codex exit code $code"
    return @{ Code = $code; Text = $final; Output = ($output -join "`n") }
}

function Is-UsageLimit([string]$Text) {
    return $Text -match '(?i)usage limit|rate[ _-]?limit|hit your limit|limit reached|limit will reset|resets at|quota exceeded|insufficient_quota'
}

function Get-QueueSelection([int]$Index) {
    if ($DryRun) {
        if ($Index -gt $TestSelections.Count) { return $null }
        return $TestSelections[$Index - 1] | ConvertFrom-Json
    }
    $selectorPrompt = Get-Content -Raw -Encoding UTF8 -LiteralPath $SelectorPromptFile
    $recoveryRequested = $false
    if (Test-Path -LiteralPath $RecoveryFile) {
        $recoveryRequested = (Get-Content -Raw -Encoding UTF8 -LiteralPath $RecoveryFile).Trim() -eq 'RESET_ACTIVE_ITEM_AFTER_USAGE_LIMIT'
    }
    $selectorPrompt += "`n`nPowerShell確認済みの利用上限復旧フラグ: $recoveryRequested"
    if ($PageId) {
        $selectorPrompt += "`n`nテスト対象の指定: page ID $PageId のみを取得し、他の項目を選ばない。"
    }
    $result = Invoke-Codex $selectorPrompt 'selector' $SchemaFile
    if ($result.Code -ne 0) {
        if (Is-UsageLimit ($result.Text + "`n" + $result.Output)) {
            Write-Log 'selector usage limit: ending this launch'
        } else {
            Write-Log "selector failed (exit code $($result.Code)); ending this launch"
        }
        return $null
    }
    try {
        $selection = $result.Text | ConvertFrom-Json
        if ($selection.status -ne 'error' -and $recoveryRequested) {
            Set-Content -LiteralPath $RecoveryFile -Value '' -Encoding UTF8
        }
        return $selection
    } catch {
        Write-Log "selector returned invalid JSON: $($_.Exception.Message)"
        return $null
    }
}

function Get-DriveContext {
    $contextPath = Join-Path $DriveRoot 'CONTEXT.md'
    $progressPath = Join-Path $DriveRoot 'PROGRESS.md'
    if (-not (Test-Path -LiteralPath $contextPath) -or -not (Test-Path -LiteralPath $progressPath)) {
        throw "Drive context files were not found under $DriveRoot"
    }
    return @{
        Context = Get-Content -Raw -Encoding UTF8 -LiteralPath $contextPath
        Progress = Get-Content -Raw -Encoding UTF8 -LiteralPath $progressPath
    }
}

function Build-WorkerPrompt($Selection, $DriveContext) {
    $template = Get-Content -Raw -Encoding UTF8 -LiteralPath $WorkerPromptFile
    return @"
$template

## run_queue が選択した唯一の対象
- page_id: $($Selection.page_id)
- page_url: $($Selection.page_url)
- 題: $($Selection.title)

### 指示本文
$($Selection.body)

## 今回読む共通情報（run_queueが最新版を読み直して添付）
### Drive CONTEXT.md
$($DriveContext.Context)

### Drive PROGRESS.md
$($DriveContext.Progress)

### Notion「現在地」—「いまの現在地」の末尾10行
$($Selection.current_tail10)

### Notion「現在地」—「決定ログ」
$($Selection.decision_log)
"@
}

try {
    $LockStream = [System.IO.File]::Open($Lock, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
    try { Write-Log 'skip: another run holds the lock' } catch {}
    exit 0
}
$LockStream.SetLength(0)
$bytes = [System.Text.Encoding]::ASCII.GetBytes("$PID")
$LockStream.Write($bytes, 0, $bytes.Length)
$LockStream.Flush()

try {
    Write-Log 'start: Codex continuous queue mode (PowerShell-selected item)'
    $throttle = Get-QueueThrottleDecision
    if (-not $throttle.InvokeSelector) {
        Write-Log "skip: queue was empty at $($throttle.EmptyAt.ToString('o')), no new instruction"
        Write-Log 'end'
        return
    }
    Clear-QueueEmptyState
    if ($throttle.WakeRequested) {
        Set-Content -LiteralPath $WakeFile -Value '' -Encoding UTF8
    }
    $driveContext = Get-DriveContext
    $run = 0
    while ($true) {
        if (Test-Path -LiteralPath $StopFile) {
            Write-Log "stop file found: $StopFile"
            break
        }
        $run++
        $selection = Get-QueueSelection $run
        if ($null -eq $selection) { Write-Log 'no valid selection; ending'; break }
        if ($selection.status -eq 'empty') {
            Set-QueueEmptyState
            Write-Log 'queue empty: done'
            break
        }
        if ($selection.status -ne 'item' -or -not $selection.page_id -or -not $selection.body) {
            Write-Log "selector status/error: $($selection.status) $($selection.error)"
            break
        }
        Write-Log "item run $run page=$($selection.page_id) title=$($selection.title)"
        $prompt = Build-WorkerPrompt $selection $driveContext
        if ($DryRun) {
            Write-Log "dry run: worker prompt chars=$($prompt.Length)"
            if ($run -gt $TestOutputs.Count) { Write-Log 'dry run: no worker output'; break }
            $parts = $TestOutputs[$run - 1] -split '\|', 2
            $result = @{ Code = [int]$parts[0]; Text = $parts[1]; Output = $parts[1] }
        } else {
            $result = Invoke-Codex $prompt 'worker'
        }
        if ($result.Code -ne 0) {
            if (Is-UsageLimit ($result.Text + "`n" + $result.Output)) {
                Set-Content -LiteralPath $RecoveryFile -Value 'RESET_ACTIVE_ITEM_AFTER_USAGE_LIMIT' -Encoding UTF8
                Write-Log 'usage limit: recovery marker written; item will be reset on the next launch'
            } else {
                Write-Log "worker failed (exit code $($result.Code)); ending this launch"
            }
            break
        }
        if ($result.Text -notmatch '(?m)^\s*QUEUE_ITEM_(COMPLETE|DEFERRED)\s*$') {
            Write-Log 'protocol marker missing; ending to avoid duplicate execution'
            break
        }
        if ($PageId) { Write-Log 'single PageId target completed'; break }
        if ($MaxItems -gt 0 -and $run -ge $MaxItems) {
            Write-Log "requested cap of $MaxItems item(s) reached"
            break
        }
    }
    Write-Log 'end'
} finally {
    $LockStream.Close()
}
