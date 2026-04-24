<#
.SYNOPSIS
    SessionStart hook -- one-time discovery hint.

.DESCRIPTION
    On the very first session after install, print a single tip telling the
    user they can ask Paperwik for help. Guarded by a sentinel file so it
    never repeats. Silent after first run.

    Research (decision #317) established this as the right discoverability
    pattern: no consumer AI product does proactive "ask me about this app"
    greetings successfully; a one-time sentinel-guarded hook-output hint is
    the sweet spot.

.NOTES
    Budget: <1s wall time. Never blocks the agent. All errors swallowed.
    Sentinel path: %USERPROFILE%\.paperwik\hint-shown
#>

$ErrorActionPreference = "SilentlyContinue"

try {
    $sentinelDir  = Join-Path $env:USERPROFILE '.paperwik'
    $sentinelFile = Join-Path $sentinelDir 'hint-shown'

    if (Test-Path $sentinelFile) { exit 0 }

    if (-not (Test-Path $sentinelDir)) {
        New-Item -ItemType Directory -Path $sentinelDir -Force | Out-Null
    }

    # Create the sentinel BEFORE printing. If the Write-Host fails for any
    # reason we still don't want to repeat the hint on the next session.
    New-Item -ItemType File -Path $sentinelFile -Force | Out-Null

    Write-Output "Tip: ask me 'how do I use Paperwik?' any time -- I will explain."
} catch {
    # Never propagate. Swallow silently.
}

exit 0
