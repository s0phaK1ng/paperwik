<#
.SYNOPSIS
    SessionStart memory rehydration (matcher: startup | resume | clear).

.DESCRIPTION
    Reads the agent's working memory (active_context.md) at session start and
    injects it as a SYSTEM DIRECTIVE the agent sees as its first system message.
    This is how the agent "remembers yesterday" — the file is updated continuously
    by the Stop and PreCompact hooks, so on launch the agent already knows the
    user's recent decisions, current focus, and preferences.

    Hard cap: 10,000 characters (~2,500 tokens). Anything older is searched on
    demand via archived_index.md.

    On first launch (active_context.md missing or empty), emits a friendly
    "new wiki" directive so the agent doesn't pretend to remember what it can't.

.NOTES
    Requires Claude Code >= 2.1.90 payload schema.
    Token budget per Decision #303 + CoWork inbound knowledge §2.3.
#>

$ErrorActionPreference = "Stop"

try {
    $vaultRoot = Join-Path -Path $env:USERPROFILE -ChildPath "Knowledge"
    $statePath = Join-Path -Path $vaultRoot -ChildPath ".claude\skills\state\active_context.md"
    $maxChars = 10000

    if (-not (Test-Path $statePath)) {
        # First-ever launch OR a reset. Don't fake memory.
        Write-Output "SYSTEM DIRECTIVE: This is a new or freshly-reset wiki. No prior working memory exists yet. Introduce yourself briefly and ask what the user wants to work on. Do not pretend to recall prior conversations."
        exit 0
    }

    $content = Get-Content -Path $statePath -Raw
    if ([string]::IsNullOrWhiteSpace($content)) {
        Write-Output "SYSTEM DIRECTIVE: Working memory file exists but is empty. Proceed without prior context."
        exit 0
    }

    # Enforce token budget by truncating oldest content (kept at file HEAD; newest appended at tail)
    if ($content.Length -gt $maxChars) {
        $content = "[earlier entries omitted — search archived_index.md for older context]`n`n" + $content.Substring($content.Length - $maxChars)
    }

    Write-Output "SYSTEM DIRECTIVE: RECENT WORKING MEMORY (from .claude/skills/state/active_context.md). This is your durable cross-session memory — the user will expect you to know this without being told again:`n`n$content"
    Write-Output ""
    Write-Output "SYSTEM DIRECTIVE: For topics older than what's in active_context.md, search .claude/skills/state/archived_index.md or the wiki pages themselves. Never fabricate a memory of something not in these files."
    exit 0

} catch {
    # Fail-open: log and proceed. Memory amnesia is annoying but not blocking.
    $documentsPath = [Environment]::GetFolderPath("MyDocuments")
    $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
    $msg = $_.Exception.Message
    $entry = "[$timestamp] HOOK_CRASH | hook=Rehydrate-Memory | error=$msg"
    try { Add-Content -Path $logPath -Value $entry -ErrorAction Stop } catch { }
    Write-Output "SYSTEM DIRECTIVE: Memory rehydration failed; proceeding without prior context. If the user asks about earlier work, offer to search the wiki directly."
    exit 0
}
