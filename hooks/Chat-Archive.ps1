<#
.SYNOPSIS
    Stop hook — silent chat archival + decision extraction.

.DESCRIPTION
    Fires at the end of every assistant response turn. Does two things,
    both silent, both non-blocking:

    1. Mirror the session's full JSONL transcript into
       ~/Paperwik/.claude/chat-history/<session-id>.jsonl so the complete
       conversation is always on disk and available for later queries.
       (The original transcript lives in Claude Code's project-scoped cache
       and can age out or get archived — mirroring into the vault gives
       the user a durable copy alongside their knowledge base.)

    2. Scan the most recent user message + assistant response for
       decision-making language. If found, append a one-line entry to
       ~/Paperwik/decisions.md silently — no user prompt, no confirmation.

    The user's design directive: "remember everything. don't make me ask."
    This hook implements that. No dialog surfaces; it all happens in the
    background.

.NOTES
    Budget: <1s wall time per turn. Timeout 5s in hooks.json (generous).
    All errors are swallowed to the diagnostic log; this hook must never
    block the agent from returning to the user.
#>

$ErrorActionPreference = "SilentlyContinue"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Append-DiagLog {
    param([string]$Message)
    try {
        $docs = [Environment]::GetFolderPath("MyDocuments")
        $log = Join-Path $docs 'Paperwik-Diagnostics.log'
        $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
        Add-Content -Path $log -Value "[$ts] [Chat-Archive] $Message" -ErrorAction SilentlyContinue
    } catch {}
}

function Extract-TextContent {
    param($Content)
    # Claude Code message content can be a string OR a list of content blocks
    # (e.g. [{"type": "text", "text": "..."}, {"type": "tool_use", ...}]).
    # Return just the concatenated plain text.
    if ($null -eq $Content) { return "" }
    if ($Content -is [string]) { return $Content }
    $parts = @()
    foreach ($block in @($Content)) {
        if ($null -eq $block) { continue }
        if ($block -is [string]) { $parts += $block; continue }
        if ($block.type -eq 'text' -and $block.text) { $parts += $block.text }
    }
    return ($parts -join "`n").Trim()
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

try {
    $vault = Join-Path $env:USERPROFILE 'Paperwik'
    if (-not (Test-Path $vault)) { exit 0 }

    # Read hook payload from stdin
    $payloadRaw = $null
    try { $payloadRaw = [System.Console]::In.ReadToEnd() } catch {}
    if (-not $payloadRaw) { exit 0 }

    $payload = $null
    try { $payload = $payloadRaw | ConvertFrom-Json } catch { exit 0 }
    if (-not $payload) { exit 0 }

    $transcriptPath = $payload.transcript_path
    $sessionId      = $payload.session_id
    if (-not $transcriptPath -or -not (Test-Path $transcriptPath)) { exit 0 }
    if (-not $sessionId) { $sessionId = 'unknown' }

    # ----- 1. Mirror transcript into vault -----
    $archiveDir = Join-Path $vault '.claude\chat-history'
    if (-not (Test-Path $archiveDir)) {
        New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
    }
    $archiveFile = Join-Path $archiveDir "$sessionId.jsonl"
    try {
        Copy-Item -Path $transcriptPath -Destination $archiveFile -Force
    } catch {
        Append-DiagLog "mirror failed: $($_.Exception.Message)"
    }

    # ----- 2. Decision extraction -----
    # Pull the last user + assistant turn out of the transcript.
    # JSONL format: one JSON object per line; each has type=user|assistant and
    # a message with content (string or array of blocks).
    $lines = Get-Content -Path $transcriptPath -Tail 200 -ErrorAction SilentlyContinue
    if (-not $lines) { exit 0 }

    $lastUser      = $null
    $lastAssistant = $null
    foreach ($line in $lines) {
        if (-not $line) { continue }
        $obj = $null
        try { $obj = $line | ConvertFrom-Json } catch { continue }
        if (-not $obj) { continue }
        if ($obj.type -eq 'user' -and $obj.message) { $lastUser = $obj }
        elseif ($obj.type -eq 'assistant' -and $obj.message) { $lastAssistant = $obj }
    }
    if (-not $lastUser -and -not $lastAssistant) { exit 0 }

    $userText      = Extract-TextContent -Content $lastUser.message.content
    $assistantText = Extract-TextContent -Content $lastAssistant.message.content
    $combined      = "$userText`n$assistantText"
    if (-not $combined.Trim()) { exit 0 }

    # Decision phrase patterns. Regex, case-insensitive.
    # Conservative set — matches commitment language, ignores hypotheticals.
    $decisionPatterns = @(
        "let'?s go with\s+(.+?)(?:[\.\n]|$)",
        "(?:we|i)(?:'ve)?\s+decided(?:\s+on)?\s*:?\s*(.+?)(?:[\.\n]|$)",
        "(?:we|i)'?ll\s+(?:use|go with|stick with|choose)\s+(.+?)(?:[\.\n]|$)",
        "going (?:with|forward with)\s+(.+?)(?:[\.\n]|$)",
        "final answer\s*:\s*(.+?)(?:[\.\n]|$)",
        "(?:from now on|henceforth|going forward),?\s+(.+?)(?:[\.\n]|$)",
        "commit(?:ting)? to\s+(.+?)(?:[\.\n]|$)",
        "settl(?:e|ed|ing) on\s+(.+?)(?:[\.\n]|$)"
    )

    $decisions = @()
    foreach ($pat in $decisionPatterns) {
        $matches = [regex]::Matches($combined, $pat, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        foreach ($m in $matches) {
            $detail = $m.Groups[1].Value.Trim()
            if ($detail.Length -lt 3 -or $detail.Length -gt 200) { continue }
            # Clean up: drop markdown link syntax, trailing quotes
            $detail = $detail -replace '[\*\`"]+', ''
            $detail = $detail.Trim()
            if ($detail) { $decisions += $detail }
        }
    }

    if ($decisions.Count -eq 0) { exit 0 }

    # De-duplicate within this turn
    $decisions = $decisions | Select-Object -Unique

    # Append to decisions.md silently
    $decisionsPath = Join-Path $vault 'decisions.md'
    if (-not (Test-Path $decisionsPath)) {
        $header = @"
---
created: $(Get-Date -Format 'yyyy-MM-dd')
tags: [decisions, meta]
auto-maintained: true
---

# Decisions

Append-only log of decisions made in conversation. Auto-captured by the
Chat-Archive Stop hook — no user action required. Entries are timestamped
and keyed to the session so you can trace any decision back to its chat.

"@
        Set-Content -Path $decisionsPath -Value $header -Encoding UTF8
    }

    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm'
    $sessionShort = if ($sessionId.Length -ge 8) { $sessionId.Substring(0, 8) } else { $sessionId }
    $entryLines = @()
    $entryLines += ""
    $entryLines += "## [$ts] session:$sessionShort"
    $entryLines += ""
    foreach ($d in $decisions) {
        $entryLines += "- $d"
    }
    Add-Content -Path $decisionsPath -Value ($entryLines -join "`r`n") -Encoding UTF8

} catch {
    Append-DiagLog $_.Exception.Message
}

exit 0
