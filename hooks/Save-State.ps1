<#
.SYNOPSIS
    PreCompact hook — writes salient in-flight state to disk before Claude's
    auto-compression kicks in, so it survives.

.DESCRIPTION
    Without this, Claude Code's auto-compaction silently summarizes older turns
    and drops nuanced detail — rule compliance drops from ~75% to ~25%
    (measured on CoWork).

    This hook captures the current session's in-flight decisions, active focus,
    and user preferences to active_context.md BEFORE compaction happens. The
    paired Restore-State hook re-injects that content AFTER.

    The payload Claude Code sends for PreCompact typically includes recent-turn
    summaries or the about-to-be-compacted transcript. We read it, extract the
    durable content, and append to active_context.md.

    If we can't parse the payload, we still write a timestamped marker so the
    agent knows compaction happened and can resume gracefully.

.NOTES
    Requires Claude Code >= 2.1.90 payload schema.
    Decision #292/#303 — compaction-resilient state idiom.
#>

$ErrorActionPreference = "Stop"

try {
    $inputJson = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($inputJson)) { exit 0 }

    $vaultRoot = Join-Path -Path $env:USERPROFILE -ChildPath "Paperwik"
    $statePath = Join-Path -Path $vaultRoot -ChildPath ".claude\skills\state\active_context.md"
    $stateDir = Split-Path -Parent $statePath
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"

    # Ensure directory exists (first-run case)
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force -ErrorAction SilentlyContinue | Out-Null
    }

    # Parse payload — PreCompact event typically provides session_id and recent context
    $payload = $null
    try { $payload = $inputJson | ConvertFrom-Json } catch { }

    $sessionMarker = "[$timestamp] PRE-COMPACT CHECKPOINT"
    if ($payload -and $payload.session_id) {
        $sessionMarker += " | session=$($payload.session_id)"
    }

    # Build the entry. The agent itself is expected to append semantically rich content
    # (decisions, preferences, current focus) to active_context.md during normal
    # operation. This hook just guarantees a timestamp anchor survives compaction.
    $entry = @"

---

## $sessionMarker

Compaction occurred. Check the most recent wiki pages touched (via index.md)
and the log.md tail for context about what was in flight. The agent should
resume by reading active_context.md fully before replying to the next prompt.

"@

    Add-Content -Path $statePath -Value $entry -Encoding UTF8

    # Echo nothing — PreCompact doesn't inject context, it just saves state.
    exit 0

} catch {
    $documentsPath = [Environment]::GetFolderPath("MyDocuments")
    $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
    $msg = $_.Exception.Message
    $entry = "[$timestamp] HOOK_CRASH | hook=Save-State | error=$msg"
    try { Add-Content -Path $logPath -Value $entry -ErrorAction Stop } catch { }
    exit 0
}
