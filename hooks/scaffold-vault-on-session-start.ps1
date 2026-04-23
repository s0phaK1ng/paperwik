<#
.SYNOPSIS
    SessionStart(startup) hook — invokes the Python scaffolder on first launch.

.DESCRIPTION
    Thin PowerShell wrapper over scripts/scaffold-vault.py. The Python scaffolder
    is idempotent (checks its own sentinel), so this hook fires every startup
    but exits immediately on second-and-later runs.

    First run: ~30–60 seconds (uv fetches Python 3.12 if absent + runs scaffolder).
    Subsequent runs: <1 second (scaffolder short-circuits on sentinel).

.NOTES
    Requires:
      - uv installed and on PATH (user installs via bootstrap script)
      - ${CLAUDE_PLUGIN_ROOT} env var set by Claude Code when plugin is active
#>

$ErrorActionPreference = "Stop"

try {
    $paperwikRoot = Join-Path -Path $env:USERPROFILE -ChildPath "Paperwik"
    $sentinel = Join-Path -Path $paperwikRoot -ChildPath ".claude\.scaffolded"

    # Fast-path skip (cheaper than spawning Python)
    if (Test-Path $sentinel) {
        exit 0
    }

    # Resolve scaffolder path via CLAUDE_PLUGIN_ROOT if set, else infer from this script's location
    $pluginRoot = $env:CLAUDE_PLUGIN_ROOT
    if ([string]::IsNullOrWhiteSpace($pluginRoot)) {
        $pluginRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
    }
    $scaffolder = Join-Path -Path $pluginRoot -ChildPath "scripts\scaffold-vault.py"

    if (-not (Test-Path $scaffolder)) {
        $documentsPath = [Environment]::GetFolderPath("MyDocuments")
        $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
        $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
        Add-Content -Path $logPath -Value "[$timestamp] HOOK_CRASH | hook=scaffold-vault-on-session-start | error=scaffolder_not_found | path=$scaffolder" -ErrorAction SilentlyContinue
        Write-Output "SYSTEM DIRECTIVE: Vault scaffolder missing. Ask the user to reinstall the Paperwik plugin."
        exit 0
    }

    # Check for uv
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        $documentsPath = [Environment]::GetFolderPath("MyDocuments")
        $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
        $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
        Add-Content -Path $logPath -Value "[$timestamp] HOOK_CRASH | hook=scaffold-vault-on-session-start | error=uv_not_on_path" -ErrorAction SilentlyContinue
        Write-Output "SYSTEM DIRECTIVE: Python runner (uv) not found. Tell the user: 'Please install uv from https://astral.sh/uv and relaunch.' Do not try to proceed without the vault scaffolded."
        exit 0
    }

    # Pass CLAUDE_PLUGIN_ROOT through to the Python process
    $env:CLAUDE_PLUGIN_ROOT = $pluginRoot

    Write-Output "SYSTEM DIRECTIVE: First-time setup in progress (creating your Paperwik vault + initializing retrieval database). This runs once; subsequent launches are instant. When you see the scaffold-complete confirmation, greet the user with: 'Welcome — your knowledge vault is ready. Drop a source into the Inbox folder when you want to start.'"

    & uv run $scaffolder
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $documentsPath = [Environment]::GetFolderPath("MyDocuments")
        $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
        $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
        Add-Content -Path $logPath -Value "[$timestamp] HOOK_CRASH | hook=scaffold-vault-on-session-start | error=scaffolder_exit_$exitCode" -ErrorAction SilentlyContinue
        Write-Output "SYSTEM DIRECTIVE: Scaffolder ran but returned a non-zero exit code. Check Documents\Paperwik-Diagnostics.log. Tell the user: 'Setup hit a snag — I'll show you the diagnostic log in a moment.'"
    }
    exit 0

} catch {
    $documentsPath = [Environment]::GetFolderPath("MyDocuments")
    $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
    $msg = $_.Exception.Message
    $entry = "[$timestamp] HOOK_CRASH | hook=scaffold-vault-on-session-start | error=$msg"
    try { Add-Content -Path $logPath -Value $entry -ErrorAction Stop } catch { }
    Write-Output "SYSTEM DIRECTIVE: First-run scaffold failed unexpectedly. Ask the user to send Documents\Paperwik-Diagnostics.log to their support contact."
    exit 0
}
