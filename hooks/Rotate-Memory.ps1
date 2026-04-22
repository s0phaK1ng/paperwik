<#
.SYNOPSIS
    Stop hook — rotates active_context.md overflow to archived_index.md once the
    active file exceeds the token budget.

.DESCRIPTION
    active_context.md has a 10,000-character cap (~2,500 tokens). Once exceeded,
    the oldest content moves to archived_index.md (which the agent can Glob/Grep
    on demand but doesn't load at session start).

    Runs silently at end of turn. No agent-visible output unless rotation actually
    happens (then emits a small notice so the agent knows older context is now
    archive-only).

.NOTES
    Requires Claude Code >= 2.1.90 payload schema.
    Pairs with Rehydrate-Memory.ps1 (reader) and Save-State.ps1 (writer).
#>

$ErrorActionPreference = "Stop"

try {
    $vaultRoot = Join-Path -Path $env:USERPROFILE -ChildPath "Knowledge"
    $activePath = Join-Path -Path $vaultRoot -ChildPath ".claude\skills\state\active_context.md"
    $archivePath = Join-Path -Path $vaultRoot -ChildPath ".claude\skills\state\archived_index.md"
    $maxChars = 10000
    $keepChars = 8000   # after rotation, active keeps the most recent 8k chars (headroom)
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"

    if (-not (Test-Path $activePath)) { exit 0 }

    $content = Get-Content -Path $activePath -Raw
    if ([string]::IsNullOrWhiteSpace($content)) { exit 0 }
    if ($content.Length -le $maxChars) { exit 0 }

    # Split: oldest (rotated out) = beginning; newest (kept) = end
    $splitIndex = $content.Length - $keepChars
    $rotatedOut = $content.Substring(0, $splitIndex)
    $kept = $content.Substring($splitIndex)

    # Append rotated content to archive with a dated header
    $archiveHeader = @"


---

## Archived on $timestamp

"@
    Add-Content -Path $archivePath -Value ($archiveHeader + $rotatedOut) -Encoding UTF8

    # Overwrite active with just the kept portion, prefixed by a short marker
    $prefix = "<!-- rotation on $timestamp moved $($rotatedOut.Length) chars to archived_index.md -->`n`n"
    Set-Content -Path $activePath -Value ($prefix + $kept) -Encoding UTF8

    exit 0

} catch {
    $documentsPath = [Environment]::GetFolderPath("MyDocuments")
    $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
    $msg = $_.Exception.Message
    $entry = "[$timestamp] HOOK_CRASH | hook=Rotate-Memory | error=$msg"
    try { Add-Content -Path $logPath -Value $entry -ErrorAction Stop } catch { }
    exit 0
}
