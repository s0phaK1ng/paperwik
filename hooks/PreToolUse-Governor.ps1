<#
.SYNOPSIS
    Dynamic security governor for Paperwik (PreToolUse hook).

.DESCRIPTION
    Intercepts every tool call before execution. Enforces three runtime rules
    that static permissions can't express:

      1. PATH BOUNDARY       — all writes must resolve inside %USERPROFILE%\Paperwik\
      2. COMPOUND COMMANDS   — blocks &&, ||, ;, |, backticks, $() in Bash commands
      3. SAFE GIT SUBSET     — only add/commit/status/log --oneline/checkout HEAD~1 allowed

    On violation: appends a structured audit line to Paperwik-Diagnostics.log,
    writes a SECURITY BOUNDARY EXCEEDED message to stderr (which the agent reads
    back as an error), and exits with code 2 to block the tool call.

    On internal error: fails OPEN (exit 0) so a script bug can't lock the user
    out of the agent entirely. Crashes are logged to the diagnostic file.

.NOTES
    Requires Claude Code >= 2.1.90 payload schema.
    Defensive pattern per Decision #14 (hooks stdout policy = JSON only or empty).
#>

$ErrorActionPreference = "Stop"

try {
    # 1. Parse incoming JSON from Claude Code via stdin
    $inputJson = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($inputJson)) { exit 0 }

    $payload = $inputJson | ConvertFrom-Json
    $toolName = $payload.tool_name
    $toolInput = $payload.tool_input

    $documentsPath = [Environment]::GetFolderPath("MyDocuments")
    $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"

    # 2. Determine vault root (single-vault architecture)
    $vaultRoot = Join-Path -Path $env:USERPROFILE -ChildPath "Paperwik"
    $normalizedVault = $null
    if (Test-Path $vaultRoot) {
        $normalizedVault = (Resolve-Path -Path $vaultRoot).Path
    } else {
        # Vault not yet scaffolded (first session). Fall back to cwd as soft boundary.
        $normalizedVault = $payload.cwd
    }

    # 3. Path-boundary check for Edit/Write
    if ($toolName -match "^(Edit|Write)$") {
        $targetFile = $toolInput.file_path
        if (-not [string]::IsNullOrWhiteSpace($targetFile)) {
            $resolvedTarget = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($payload.cwd, $targetFile))

            if (-not $resolvedTarget.StartsWith($normalizedVault, [System.StringComparison]::OrdinalIgnoreCase)) {
                $entry = "[$timestamp] BLOCK | tool=$toolName | reason=path_boundary_violation | target=$resolvedTarget | vault=$normalizedVault"
                Add-Content -Path $logPath -Value $entry -ErrorAction SilentlyContinue
                [Console]::Error.WriteLine("SECURITY BOUNDARY EXCEEDED: You are restricted to modifying files strictly within the active vault ($normalizedVault). Attempted: $resolvedTarget")
                exit 2
            }
        }
    }

    # 4. Bash-command checks (compound + safe-git subset + approved wrappers)
    if ($toolName -eq "Bash") {
        $command = ""
        if ($toolInput.command) { $command = $toolInput.command.Trim() }
        if ([string]::IsNullOrWhiteSpace($command)) { exit 0 }

        # 4a. Block compound operators / subshells / backticks
        # Note: escaped properly for PowerShell regex:
        #   &&  ||  ;  |  `...`  $(...)
        if ($command -match '(\&\&|\|\||;|\||``|\$\()') {
            $entry = "[$timestamp] BLOCK | tool=Bash | reason=compound_command | command=$command"
            Add-Content -Path $logPath -Value $entry -ErrorAction SilentlyContinue
            [Console]::Error.WriteLine("SECURITY BOUNDARY EXCEEDED: Compound commands, piping, and subshells are prohibited. Write a single-command invocation, or put the compound logic in a script file.")
            exit 2
        }

        # 4b. If it's a git command, enforce safe subset
        if ($command -match '^git\s+') {
            $safePattern = '^git\s+(add\s+.*|commit\s+-m\s+.*|commit\s+--quiet\s+.*|commit\s+--quiet\s+-m\s+.*|status(\s+--porcelain)?|log\s+--oneline(\s+.*)?|checkout\s+HEAD~1\s+--\s+.*|init|diff(\s+.*)?|show(\s+.*)?)$'
            if ($command -notmatch $safePattern) {
                $entry = "[$timestamp] BLOCK | tool=Bash | reason=unsafe_git | command=$command"
                Add-Content -Path $logPath -Value $entry -ErrorAction SilentlyContinue
                [Console]::Error.WriteLine("SECURITY BOUNDARY EXCEEDED: Git operation not in the authorized safe subset. Allowed: add, commit (-m or --quiet), status, log --oneline, checkout HEAD~1 -- <file>, init, diff, show.")
                exit 2
            }
        }
        # 4c. Otherwise must be a known approved wrapper (uv, python -m spacy, or a bundled plugin script)
        elseif ($command -notmatch '^uv\s+run\s+' -and
                $command -notmatch '^python\s+-m\s+spacy\s+download\s+' -and
                $command -notmatch 'hooks[\\/][^\\/]+\.ps1' -and
                $command -notmatch 'scripts[\\/][^\\/]+\.py') {
            $entry = "[$timestamp] BLOCK | tool=Bash | reason=unauthorized_shell | command=$command"
            Add-Content -Path $logPath -Value $entry -ErrorAction SilentlyContinue
            [Console]::Error.WriteLine("SECURITY BOUNDARY EXCEEDED: Arbitrary shell execution is prohibited. Allowed: git (safe subset), uv run, python -m spacy download, or bundled plugin hook/script.")
            exit 2
        }
    }

    # 5. All checks passed — allow the tool call to proceed
    exit 0

} catch {
    # Fail-open: log the crash but let the agent continue. A buggy governor must never lock out the agent.
    $documentsPath = [Environment]::GetFolderPath("MyDocuments")
    $logPath = Join-Path -Path $documentsPath -ChildPath "Paperwik-Diagnostics.log"
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ"
    $msg = $_.Exception.Message
    $pos = $_.InvocationInfo.PositionMessage
    $entry = "[$timestamp] HOOK_CRASH | hook=PreToolUse-Governor | error=$msg | at=$pos"
    try { Add-Content -Path $logPath -Value $entry -ErrorAction Stop } catch { }
    exit 0
}
