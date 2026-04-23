<#
.SYNOPSIS
    Weekly retrieval-quality eval runner. Invoked by Windows Task Scheduler.

.DESCRIPTION
    Runs the retrieval eval harness against the user's eval.json and logs
    results + any week-over-week drops to Documents\Paperwik-Diagnostics.log.
    Never surfaces a UI — this runs in the background.

    Fallback: if Task Scheduler isn't registered, SessionStart logic in the
    scaffolder can invoke this on every launch if >7 days since last run.

.NOTES
    Requires: uv on PATH, knowledge.db exists, eval.json has ≥1 question.
#>

$ErrorActionPreference = "Stop"

try {
    $vaultRoot = Join-Path $env:USERPROFILE "Paperwik"
    $evalPath = Join-Path $vaultRoot "eval.json"
    $dbPath = Join-Path $vaultRoot "knowledge.db"

    $documents = [Environment]::GetFolderPath("MyDocuments")
    $diagLog = Join-Path $documents "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"

    # Guard: vault exists?
    if (-not (Test-Path $evalPath) -or -not (Test-Path $dbPath)) {
        Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] skip — vault not scaffolded yet" -ErrorAction SilentlyContinue
        exit 0
    }

    # Guard: eval.json has questions?
    try {
        $evalJson = Get-Content -Path $evalPath -Raw | ConvertFrom-Json
        if (-not $evalJson.questions -or $evalJson.questions.Count -lt 1) {
            Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] skip — eval.json has no questions yet (dad needs to fill in 20 during training)" -ErrorAction SilentlyContinue
            exit 0
        }
    } catch {
        Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] skip — eval.json unparseable: $($_.Exception.Message)" -ErrorAction SilentlyContinue
        exit 0
    }

    # Guard: uv available?
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] skip — uv not on PATH" -ErrorAction SilentlyContinue
        exit 0
    }

    # Resolve plugin root
    $pluginRoot = $env:CLAUDE_PLUGIN_ROOT
    if ([string]::IsNullOrWhiteSpace($pluginRoot)) {
        # Task Scheduler invocations don't see CLAUDE_PLUGIN_ROOT — infer from this script's location
        $pluginRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
    }
    $evalScript = Join-Path $pluginRoot "scripts\retrieval_eval.py"

    if (-not (Test-Path $evalScript)) {
        Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] skip — retrieval_eval.py missing at $evalScript" -ErrorAction SilentlyContinue
        exit 0
    }

    Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] starting eval run"

    # Run it — output is captured into the diagnostic log
    $env:CLAUDE_PLUGIN_ROOT = $pluginRoot
    $output = & uv run $evalScript 2>&1
    $exitCode = $LASTEXITCODE

    foreach ($line in ($output | Out-String -Stream)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] $line" -ErrorAction SilentlyContinue
    }
    Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] finished exit=$exitCode" -ErrorAction SilentlyContinue

    exit 0

} catch {
    try {
        $documents = [Environment]::GetFolderPath("MyDocuments")
        $diagLog = Join-Path $documents "Paperwik-Diagnostics.log"
        $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
        Add-Content -Path $diagLog -Value "[$timestamp] [weekly-eval-cron] HOOK_CRASH: $($_.Exception.Message)" -ErrorAction SilentlyContinue
    } catch { }
    exit 0
}
