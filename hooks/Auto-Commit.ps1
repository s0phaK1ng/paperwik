<#
.SYNOPSIS
    PostToolUse hook — silent git auto-commit of vault changes.

.DESCRIPTION
    Fires after Write / Edit / MultiEdit / NotebookEdit tool calls. Runs
    `git add -A && git commit` inside ~/Paperwik/ so every agent-side file
    change is captured as a versioned snapshot. Gives the user a Time
    Machine for undoing agent edits (`git log`, `git revert`, `git checkout`).

    Silent: no user-visible output, no prompts. Hook exits 0 even on
    git failures so a bad commit attempt never blocks the agent.

    Scope: agent-initiated edits only (triggered by PostToolUse). Manual
    file changes by the user are not auto-committed — the user's workflow
    in Obsidian doesn't need an audit trail for their own actions.

.NOTES
    Initializes git repo in ~/Paperwik/ on first run if not already present.
    Ignores errors. Budget: <1s wall time per invocation. Timeout 5s in hooks.json.
#>

$ErrorActionPreference = "SilentlyContinue"

try {
    $vault = Join-Path $env:USERPROFILE 'Paperwik'
    if (-not (Test-Path $vault)) { exit 0 }

    # Parse the hook payload for tool name (best-effort; commit still works without it)
    $payloadRaw = $null
    try {
        $payloadRaw = [System.Console]::In.ReadToEnd()
    } catch {}
    $toolName = "edit"
    $targetHint = ""
    if ($payloadRaw) {
        try {
            $payload = $payloadRaw | ConvertFrom-Json
            if ($payload.tool_name) { $toolName = $payload.tool_name }
            if ($payload.tool_input.file_path) {
                $targetHint = Split-Path -Leaf $payload.tool_input.file_path
            } elseif ($payload.tool_input.path) {
                $targetHint = Split-Path -Leaf $payload.tool_input.path
            }
        } catch {}
    }

    Push-Location $vault
    try {
        # The installer is responsible for creating .git and the initial
        # snapshot (install.ps1 step 7(c3)). If .git isn't here, something
        # went wrong in install; don't try to init from the hook — staging
        # a fresh vault takes longer than the hook's timeout budget and
        # would leave a half-initialized repo with a stale index.lock.
        if (-not (Test-Path '.git')) {
            try {
                $docs = [Environment]::GetFolderPath("MyDocuments")
                $log = Join-Path $docs 'Paperwik-Diagnostics.log'
                $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
                Add-Content -Path $log -Value "[$ts] [Auto-Commit] SKIP: .git missing in $vault — expected installer to create it" -ErrorAction SilentlyContinue
            } catch {}
            exit 0
        }

        # Stale-lock recovery. If a previous git operation was killed
        # (hook timeout, power loss, user ctrl-c), index.lock can be left
        # behind, wedging all future git commands. Delete it if it's older
        # than 30s (safely assumes no live git operation is in flight).
        $lock = Join-Path $vault '.git\index.lock'
        if (Test-Path $lock) {
            try {
                $age = (Get-Date) - (Get-Item $lock).LastWriteTime
                if ($age.TotalSeconds -gt 30) {
                    Remove-Item $lock -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }

        # Is there anything to commit? (If the repo was just created by the
        # installer, this is where we pick up agent-side changes.)
        $dirty = (& git status --porcelain 2>$null)
        if (-not $dirty) { exit 0 }

        & git add -A 2>$null | Out-Null
        $msg = if ($targetHint) { "agent: $toolName $targetHint" } else { "agent: $toolName" }
        # Trim message to 72 chars (git convention)
        if ($msg.Length -gt 72) { $msg = $msg.Substring(0, 72) }
        & git commit --quiet -m $msg 2>$null | Out-Null
    } finally {
        Pop-Location
    }
} catch {
    # Never propagate errors — hook must be silent and non-blocking
    try {
        $documentsPath = [Environment]::GetFolderPath("MyDocuments")
        $logPath = Join-Path $documentsPath 'Paperwik-Diagnostics.log'
        $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
        Add-Content -Path $logPath -Value "[$ts] [Auto-Commit] $($_.Exception.Message)" -ErrorAction SilentlyContinue
    } catch {}
}

exit 0
