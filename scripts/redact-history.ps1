<#
.SYNOPSIS
    Permanently redacts files from a Paperwik vault AND its git history.

.DESCRIPTION
    Called by the redact-history skill after the agent has walked the user
    through the multi-step confirmation flow. Performs:

        1. Pattern sanitation  (block .. traversal, absolute paths, protected dirs)
        2. Vault shape validation (must be under Paperwik/ with .git/ and .obsidian/)
        3. Enumerate matched files (dry-run support)
        4. Timestamped .git backup to %TEMP% (belt-and-braces before rewrite)
        5. git filter-repo --invert-paths --path <each matched> --force
        6. Belt-and-braces reflog expire + aggressive gc
        7. Write tombstone line to <vault>/.claude/tombstones.jsonl
        8. Write audit line to Documents\Paperwik-Audit.log (SEPARATE log)
        9. Emit key=value status lines on stdout for the calling skill

.PARAMETER TargetPattern
    Vault-relative glob or path the skill resolved.

.PARAMETER ConfirmationToken
    The literal phrase the user typed, or "DRYRUN" for preview-only.

.NOTES
    Emits key=value lines; always exits 0 (status lives in the output).
    Requires: bundled git-filter-repo.exe in plugin bin/ (built by the
    maintainer per BUILD-GIT-FILTER-REPO.md).
#>

param(
    [Parameter(Mandatory=$true)] [string] $TargetPattern,
    [Parameter(Mandatory=$true)] [string] $ConfirmationToken
)

$ErrorActionPreference = "Stop"

# --------------------------------------------------------------------------- #
#  Paths
# --------------------------------------------------------------------------- #

$VaultRoot = Join-Path $env:USERPROFILE "Paperwik"
$PluginRoot = $env:CLAUDE_PLUGIN_ROOT
if ([string]::IsNullOrWhiteSpace($PluginRoot)) {
    $PluginRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}
$FilterRepoExe = Join-Path $PluginRoot "bin\git-filter-repo.exe"
$DocumentsPath = [Environment]::GetFolderPath("MyDocuments")
$DiagLog = Join-Path $DocumentsPath "Paperwik-Diagnostics.log"
$AuditLog = Join-Path $DocumentsPath "Paperwik-Audit.log"
$TombstonePath = Join-Path $VaultRoot ".claude\tombstones.jsonl"

$AuditId = [guid]::NewGuid().ToString("N").Substring(0, 12)
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")

# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

function Write-Diag {
    param([string]$Msg, [string]$Level = "INFO")
    try {
        Add-Content -Path $DiagLog -Value ("[{0}] [{1}] [redact-history] [audit={2}] {3}" -f $Timestamp, $Level, $AuditId, $Msg) -ErrorAction SilentlyContinue
    } catch { }
}

function Emit {
    param([hashtable]$Fields)
    foreach ($key in $Fields.Keys) {
        $val = $Fields[$key]
        if ($null -ne $val) {
            # Flatten newlines in values so each pair stays on one stdout line
            $flat = ($val.ToString()) -replace "`r?`n", " | "
            Write-Output ("{0}={1}" -f $key, $flat)
        }
    }
}

function Emit-Refusal {
    param([string]$Reason, [string]$Detail = "")
    Write-Diag ("REFUSED: {0} {1}" -f $Reason, $Detail) "WARN"
    Emit @{
        status = "refused"
        reason = $Reason
        detail = $Detail
        target = $TargetPattern
        vault = $VaultRoot
        audit_id = $AuditId
        timestamp = $Timestamp
    }
    exit 0
}

function Emit-Error {
    param([string]$Err)
    Write-Diag "ERROR: $Err" "ERROR"
    try {
        $auditLine = "timestamp=$Timestamp audit_id=$AuditId vault=`"$VaultRoot`" target=`"$TargetPattern`" tool=none files_count=0 success=false error=`"$Err`""
        Add-Content -Path $AuditLog -Value $auditLine -ErrorAction SilentlyContinue
    } catch { }
    Emit @{
        status = "error"
        error_text = $Err
        target = $TargetPattern
        vault = $VaultRoot
        audit_id = $AuditId
        timestamp = $Timestamp
    }
    exit 0
}

# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

try {
    Write-Diag ("Invoked. target={0} token_kind={1}" -f $TargetPattern, $(if ($ConfirmationToken -eq 'DRYRUN') { 'dryrun' } else { 'live' }))

    # 1. Pattern sanitation
    if ([string]::IsNullOrWhiteSpace($TargetPattern)) {
        Emit-Refusal "pattern_empty" "Target pattern was empty."
    }
    if ($TargetPattern -match '\.\.') {
        Emit-Refusal "pattern_traversal" "Pattern contains '..'."
    }
    if ($TargetPattern -match '^[A-Za-z]:[\\/]' -or $TargetPattern.StartsWith('/') -or $TargetPattern.StartsWith('\')) {
        Emit-Refusal "pattern_traversal" "Pattern is absolute."
    }
    $forbiddenInternal = @('.git', '.gitignore', '.gitattributes', '.claude', '.obsidian', 'knowledge.db')
    foreach ($f in $forbiddenInternal) {
        if ($TargetPattern.ToLowerInvariant() -like "*$f*") {
            Emit-Refusal "pattern_internal" "Pattern targets protected path '$f'."
        }
    }

    # 2. Vault shape
    if (-not (Test-Path $VaultRoot)) {
        Emit-Refusal "not_a_vault" "Vault root does not exist: $VaultRoot"
    }
    $claudeDir = Join-Path $VaultRoot ".claude"
    $obsidianDir = Join-Path $VaultRoot ".obsidian"
    $gitDir = Join-Path $VaultRoot ".git"
    if (-not (Test-Path $claudeDir) -or -not (Test-Path $obsidianDir)) {
        Emit-Refusal "not_a_vault" "Missing .claude or .obsidian under $VaultRoot"
    }
    if (-not (Test-Path $gitDir)) {
        Emit-Refusal "not_a_git_repo" "No .git directory in vault — nothing to rewrite."
    }

    # 3. Tools
    if (-not (Test-Path $FilterRepoExe)) {
        Emit-Refusal "tool_missing" "git-filter-repo.exe not found at $FilterRepoExe — build per BUILD-GIT-FILTER-REPO.md."
    }
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        Emit-Refusal "tool_missing" "git not on PATH."
    }

    # Prepend the plugin's bin dir so `git filter-repo` subcommand resolves the frozen exe
    $env:PATH = (Join-Path $PluginRoot "bin") + ";" + $env:PATH

    # 4. Enumerate matches
    $matched = @()
    Push-Location $VaultRoot
    try {
        if ($TargetPattern -match '[\*\?]') {
            # Glob-ish pattern — convert to regex and walk the tree
            $escaped = [System.Text.RegularExpressions.Regex]::Escape($TargetPattern)
            $regexPattern = $escaped.Replace('\*\*', '.*').Replace('\*', '[^\\/]*').Replace('\?', '.')
            $regex = "^$regexPattern$"

            $candidates = Get-ChildItem -Path $VaultRoot -Recurse -File -Force -ErrorAction SilentlyContinue
            foreach ($f in $candidates) {
                $rel = $f.FullName.Substring($VaultRoot.Length).TrimStart('\', '/').Replace('\', '/')
                if ($rel -like '.git/*' -or $rel -like '.claude/*' -or $rel -like '.obsidian/*') { continue }
                if ($rel -match $regex) {
                    $matched += $rel
                }
            }
        } else {
            $candidate = Join-Path $VaultRoot $TargetPattern
            if (Test-Path $candidate -PathType Leaf) {
                $matched += ($TargetPattern -replace '\\', '/')
            } elseif (Test-Path $candidate -PathType Container) {
                $files = Get-ChildItem -Path $candidate -Recurse -File -Force -ErrorAction SilentlyContinue
                foreach ($f in $files) {
                    $matched += $f.FullName.Substring($VaultRoot.Length).TrimStart('\', '/').Replace('\', '/')
                }
            }
        }
    } finally {
        Pop-Location
    }

    if ($matched.Count -eq 0) {
        Emit @{
            status = "refused"
            reason = "no_matches"
            target = $TargetPattern
            vault = $VaultRoot
            audit_id = $AuditId
            timestamp = $Timestamp
        }
        exit 0
    }

    # 5. Commit count for preview
    Push-Location $VaultRoot
    try {
        $commitList = & git log --pretty=format:%H -- $matched 2>$null
    } finally {
        Pop-Location
    }
    $commitsToRewrite = if ($commitList) { @($commitList).Count } else { 0 }
    Push-Location $VaultRoot
    try {
        $commitShasBefore = (& git rev-list --all 2>$null) -join ','
    } finally {
        Pop-Location
    }

    # 6. Dry-run early return
    if ($ConfirmationToken -eq "DRYRUN") {
        Emit @{
            status = "dryrun_ok"
            target = $TargetPattern
            vault = $VaultRoot
            wiki_name = "Paperwik"
            matched_files = $matched.Count
            matched_list = ($matched -join ';')
            commits_to_rewrite = $commitsToRewrite
            audit_id = $AuditId
            timestamp = $Timestamp
        }
        exit 0
    }

    if ($ConfirmationToken.Trim().Length -lt 4) {
        Emit-Refusal "confirmation_missing" "Token too short."
    }

    # 7. Backup .git to %TEMP%
    $backupZip = Join-Path $env:TEMP ("Paperwik-git-backup-" + $AuditId + ".zip")
    try {
        Compress-Archive -Path $gitDir -DestinationPath $backupZip -Force -ErrorAction Stop
        Write-Diag "Git backup written to $backupZip"
    } catch {
        Write-Diag "Git backup failed (non-fatal): $($_.Exception.Message)" "WARN"
    }

    # 8. Execute filter-repo
    Write-Diag "EXECUTING redaction on $($matched.Count) files, ~$commitsToRewrite commits."
    $frArgs = @('filter-repo', '--force', '--invert-paths')
    foreach ($m in $matched) {
        $frArgs += @('--path', $m)
    }

    Push-Location $VaultRoot
    try {
        $frOut = & git @frArgs 2>&1
        $frExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    if ($frExit -ne 0) {
        Emit-Error ("git filter-repo failed (exit $frExit): " + ($frOut -join ' '))
    }

    # 9. Belt-and-braces gc (filter-repo usually handles this but rerun is idempotent)
    Push-Location $VaultRoot
    try {
        & git reflog expire --expire=now --all 2>&1 | Out-Null
        & git gc --prune=now --aggressive 2>&1 | Out-Null
        $commitShasAfter = (& git rev-list --all 2>$null) -join ','
    } finally {
        Pop-Location
    }

    # 10. Tombstone
    $tombstoneLine = @{
        timestamp = $Timestamp
        audit_id = $AuditId
        target_pattern = $TargetPattern
        file_count_purged = $matched.Count
        commit_count_rewritten = $commitsToRewrite
        requester_confirmation_phrase = $ConfirmationToken
        wiki_name = "Paperwik"
    } | ConvertTo-Json -Compress
    Add-Content -Path $TombstonePath -Value $tombstoneLine

    # 11. Audit log (SEPARATE file from diagnostics)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $shaBefore = [System.BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($commitShasBefore))).Replace('-', '').Substring(0, 16)
        $shaAfter = [System.BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($commitShasAfter))).Replace('-', '').Substring(0, 16)
    } finally {
        $sha256.Dispose()
    }
    $confEsc = $ConfirmationToken -replace '"', '\"'
    $auditLine = "timestamp=$Timestamp audit_id=$AuditId vault=`"$VaultRoot`" wiki=`"Paperwik`" target=`"$TargetPattern`" tool=git-filter-repo files_count=$($matched.Count) files=`"$($matched -join '|')`" commits_rewritten=$commitsToRewrite shas_before_hash=$shaBefore shas_after_hash=$shaAfter confirmation=`"$confEsc`" backup=`"$backupZip`" success=true error=`"`""
    Add-Content -Path $AuditLog -Value $auditLine

    # 12. Success
    Emit @{
        status = "ok"
        target = $TargetPattern
        vault = $VaultRoot
        wiki_name = "Paperwik"
        files_purged = $matched.Count
        commits_rewritten = $commitsToRewrite
        tombstone_path = $TombstonePath
        audit_log_path = $AuditLog
        git_backup = $backupZip
        audit_id = $AuditId
        tool = "git-filter-repo"
        timestamp = $Timestamp
    }
    Write-Diag "SUCCESS files=$($matched.Count) commits=$commitsToRewrite"
    exit 0

} catch {
    Emit-Error ("Unhandled: " + $_.Exception.Message + " @ " + $_.InvocationInfo.PositionMessage)
    exit 0
}
