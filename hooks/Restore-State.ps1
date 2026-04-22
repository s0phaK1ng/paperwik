<#
.SYNOPSIS
    SessionStart hook with matcher=compact — re-injects saved state after Claude's
    auto-compression has finished.

.DESCRIPTION
    Functionally identical to Rehydrate-Memory.ps1 but with a different directive
    framing: the agent should understand it JUST went through compaction, so any
    apparent gaps in its own recollection are expected and should be filled from
    active_context.md rather than improvised.

    This hook is what turns the 75% → 25% post-compaction compliance drop (measured
    on CoWork) into ~100% recovery.

.NOTES
    Requires Claude Code >= 2.1.90 payload schema.
    Pair with Save-State.ps1 (PreCompact).
#>

$ErrorActionPreference = "Stop"

try {
    $vaultRoot = Join-Path -Path $env:USERPROFILE -ChildPath "Knowledge"
    $statePath = Join-Path -Path $vaultRoot -ChildPath ".claude\skills\state\active_context.md"
    $maxChars = 10000

    if (-not (Test-Path $statePath)) {
        Write-Output "SYSTEM DIRECTIVE: Post-compaction recovery — no saved state file found. Proceed cautiously and ask the user to re-state the current task if anything seems missing."
        exit 0
    }

    $content = Get-Content -Path $statePath -Raw
    if ([string]::IsNullOrWhiteSpace($content)) {
        Write-Output "SYSTEM DIRECTIVE: Post-compaction recovery — saved state file is empty. Ask the user to re-state the current task."
        exit 0
    }

    if ($content.Length -gt $maxChars) {
        $content = "[earlier entries omitted — search archived_index.md for older context]`n`n" + $content.Substring($content.Length - $maxChars)
    }

    Write-Output "SYSTEM DIRECTIVE: POST-COMPACTION RECOVERY. Claude Code just compacted older turns to save context window space — your own internal recollection of recent conversation may be fuzzy. The durable record below is authoritative:`n`n$content"
    Write-Output ""
    Write-Output "SYSTEM DIRECTIVE: Before responding to the next user message, silently re-read the last few wiki pages listed in index.md and the log.md tail so your grounding matches the user's expectations. If anything is unclear, ask ONE clarifying question rather than inventing continuity."
    exit 0

} catch {
    $documentsPath = [Environment]::GetFolderPath("MyDocuments")
    $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
    $msg = $_.Exception.Message
    $entry = "[$timestamp] HOOK_CRASH | hook=Restore-State | error=$msg"
    try { Add-Content -Path $logPath -Value $entry -ErrorAction Stop } catch { }
    Write-Output "SYSTEM DIRECTIVE: Post-compaction recovery failed. Ask the user to re-state the current task."
    exit 0
}
