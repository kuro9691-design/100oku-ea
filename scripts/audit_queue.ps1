# Independent Astra audit runner. It only receives items already marked 監査役待ち.
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Share = 'C:\Users\user\Documents\100億j_share'
$DriveRoot = 'G:\マイドライブ\100億'
$LogDir = Join-Path $Root 'logs'
$SelectorPromptFile = Join-Path $PSScriptRoot 'audit_select_prompt.md'
$WorkerPromptFile = Join-Path $PSScriptRoot 'audit_prompt.md'
$SchemaFile = Join-Path $PSScriptRoot 'audit_selection_schema.json'
$SelectorModel = 'gpt-6.1-sol'
$AuditorModel = 'gpt-6-astra'

New-Item -ItemType Directory -Force $LogDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Log = Join-Path $LogDir "audit_queue_$Stamp.log"
$Lock = Join-Path $LogDir 'audit_queue.lock'
$Heartbeat = Join-Path $LogDir 'audit_queue_heartbeat.txt'

function Write-Log([string]$Text) {
    $line = "[{0}] [pid {1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID, $Text
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
    Set-Content -LiteralPath $Heartbeat -Value $line -Encoding UTF8
}

function Invoke-Codex([string]$PromptText, [string]$Kind, [string]$Model, [string]$OutputSchema = '') {
    $lastMessage = Join-Path $LogDir ("audit_queue_{0}_{1}_{2}.txt" -f $Kind, $PID, (Get-Date -Format 'HHmmssfff'))
    $arguments = @('exec', '--ephemeral', '--approve-for-me', '-C', $Root, '--add-dir', $Share, '--model', $Model, '-o', $lastMessage)
    if ($OutputSchema) { $arguments += @('--output-schema', $OutputSchema) }
    $arguments += '-'
    $ErrorActionPreference = 'Continue'
    try {
        $output = @($PromptText | & $CodexExe @arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = 'Stop' }
    $output | ForEach-Object { Add-Content -LiteralPath $Log -Value $_ -Encoding UTF8 }
    $final = if (Test-Path -LiteralPath $lastMessage) { Get-Content -Raw -Encoding UTF8 -LiteralPath $lastMessage } else { $output -join "`n" }
    Write-Log "$Kind model=$Model exit=$code"
    return @{ Code = $code; Text = $final }
}

function Get-DriveContext {
    $contextPath = Join-Path $DriveRoot 'CONTEXT.md'
    $progressPath = Join-Path $DriveRoot 'PROGRESS.md'
    $rulesPath = Join-Path $DriveRoot '運用ルール.md'
    if (-not (Test-Path $contextPath) -or -not (Test-Path $progressPath) -or -not (Test-Path $rulesPath)) { throw 'Drive canonical files were not found' }
    return @{ Context = Get-Content -Raw -Encoding UTF8 $contextPath; Progress = Get-Content -Raw -Encoding UTF8 $progressPath; Rules = Get-Content -Raw -Encoding UTF8 $rulesPath }
}

try {
    Write-Log 'startup: resolving codex executable'
    $CodexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($CodexCommand) { $CodexExe = $CodexCommand.Source }
    else {
        $CodexBin = Join-Path $env:USERPROFILE 'AppData\Local\OpenAI\Codex\bin'
        $CodexExe = Get-ChildItem -LiteralPath $CodexBin -Filter codex.exe -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $CodexExe) { throw 'codex.exe was not found' }
    Write-Log "codex executable=$CodexExe"
} catch {
    Write-Log "startup failed: $_"
    throw
}

try { $LockStream = [System.IO.File]::Open($Lock, 'OpenOrCreate', 'ReadWrite', 'None') }
catch { try { Write-Log 'skip: another audit run holds the lock' } catch {}; exit 0 }

try {
    Write-Log 'start: independent Astra audit queue'
    $selectorPrompt = Get-Content -Raw -Encoding UTF8 $SelectorPromptFile
    $selected = Invoke-Codex $selectorPrompt 'selector' $SelectorModel $SchemaFile
    if ($selected.Code -ne 0) { throw "selector failed: $($selected.Code)" }
    $item = $selected.Text | ConvertFrom-Json
    if ($item.status -eq 'empty') { Write-Log 'queue empty'; exit 0 }
    if ($item.status -ne 'item' -or -not $item.page_id -or -not $item.body) { throw "invalid selection: $($item.status) $($item.error)" }
    $drive = Get-DriveContext
    $template = Get-Content -Raw -Encoding UTF8 $WorkerPromptFile
    $prompt = @"
$template

## 選択された唯一の監査対象
- page_id: $($item.page_id)
- page_url: $($item.page_url)
- 題: $($item.title)

### 指示本文
$($item.body)

## Drive正本
### CONTEXT.md
$($drive.Context)

### PROGRESS.md
$($drive.Progress)

### 運用ルール.md
$($drive.Rules)

## Notion現在地
### 末尾10行
$($item.current_tail10)

### 決定ログ
$($item.decision_log)
"@
    $result = Invoke-Codex $prompt 'auditor' $AuditorModel
    if ($result.Code -ne 0) { throw "auditor failed: $($result.Code)" }
    if ($result.Text -notmatch '(?m)^\s*AUDIT_ITEM_(COMPLETE|DEFERRED)\s*$') { throw 'audit protocol marker missing' }
    Write-Log 'completed'
} catch {
    Write-Log "failed: $_"
    throw
} finally {
    if ($LockStream) { $LockStream.Close() }
}
