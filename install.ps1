<#
.SYNOPSIS
    One-line Paperwik bootstrap. Hosted on GitHub Pages for easy remote
    execution: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`

.DESCRIPTION
    Runs five install commands in sequence:
        1. Install Git for Windows (provides git + git-bash, required by Claude Code)
        2. Install Claude Code CLI via Anthropic's official script
        3. Install Claude Desktop (the GUI app end users launch to reach Claude Code)
        4. Install Obsidian (winget preferred, direct download as fallback)
        5. Install uv (Python runner used by Paperwik's retrieval scripts)

    Does NOT install the plugin itself — plugin install requires Claude Code's
    own /plugin marketplace + /plugin install slash commands, which only work
    inside the CLI. The installer walks the user through those during the
    day-one session.

.NOTES
    v0.1.5 — friends-and-family bootstrap. No admin rights required.
    Changes from v0.1.4:
      - Added Claude Desktop install step. Non-technical users launch Claude
        Code from inside Claude Desktop (not PowerShell), so the GUI app is
        the real entry point and needs to be on the machine. Uses winget
        (Anthropic.Claude) with direct-download fallback
        (storage.googleapis.com/.../Claude-Setup-x64.exe, --silent flag).
        Verification checks %LOCALAPPDATA%\AnthropicClaude\Claude.exe.
      - Renumbered to 5 total steps. Banner + final "what next" message
        updated to point the user at Claude Desktop, not PowerShell.

    Changes from v0.1.3:
      - Made registry fallback in Test-ObsidianInstalled defensive — many
        uninstall subkeys don't have a DisplayName property, and with the
        script's ErrorActionPreference=Stop, accessing a missing property
        threw. Now wraps the enumeration in try/catch and checks property
        presence before reading.

    Changes from v0.1.2:
      - Fixed Obsidian "installed at expected location" check — electron-builder
        NSIS installer puts Obsidian at %LOCALAPPDATA%\Programs\Obsidian\, not
        %LOCALAPPDATA%\Obsidian\. Previous path list missed this so silent install
        succeeded but the script reported failure.
      - Added registry fallback check (HKCU Uninstall key) for robustness.
      - Bumped post-install settling time from 2s to 5s.

    Changes from v0.1.1:
      - Fixed Obsidian asset regex to match actual filename pattern
        (Obsidian-1.x.y.exe with hyphen, not dot)
      - Auto-add Claude Code's install dir (~/.local/bin) to user PATH so
        'claude' command works without the user editing environment variables

    Changes from v0.1.0:
      - Added Git for Windows install step (Claude Code needs git-bash)
      - Replaced Unicode banner with ASCII-safe characters
      - Obsidian falls back to direct GitHub-releases download + silent install
        when winget is unavailable (older Windows, Sandbox, etc.)
#>

$ErrorActionPreference = "Stop"

# Force UTF-8 output so any accented characters in error messages render
# correctly across console code pages
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch { }

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host "  Hello! Welcome to Paperwik." -ForegroundColor Cyan
Write-Host "  I'll install five small tools. About 5 minutes total." -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host ""

# Helpers -----------------------------------------------------------------
function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-LatestGithubAsset {
    param(
        [string]$Repo,        # "owner/repo"
        [string]$NamePattern  # regex to match the asset filename
    )
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $headers = @{ 'User-Agent' = 'Paperwik-Installer/0.1.1'; 'Accept' = 'application/vnd.github+json' }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers $headers -UseBasicParsing -TimeoutSec 30
    $asset = $release.assets | Where-Object { $_.name -match $NamePattern } | Select-Object -First 1
    if (-not $asset) { throw "No release asset in $Repo/latest matching /$NamePattern/" }
    return @{
        Name = $asset.name
        Url  = $asset.browser_download_url
        Size = [int64]$asset.size
    }
}

function Download-File {
    param([string]$Url, [string]$Destination)
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -UserAgent 'Paperwik-Installer/0.1.1' -TimeoutSec 600
}

# -----------------------------------------------------------------------------
# Step 1 — Git for Windows (provides git + git-bash; Claude Code requires bash)
# -----------------------------------------------------------------------------
Write-Host "[1/5] Setting up Git for Windows (Claude Code needs git-bash)..." -ForegroundColor Yellow

if (Test-CommandExists "git") {
    Write-Host "      Already on your computer, moving on." -ForegroundColor Green
} else {
    $wingetAvailable = Test-CommandExists "winget"
    if ($wingetAvailable) {
        try {
            winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements --silent
            Write-Host "      Git ready." -ForegroundColor Green
        } catch {
            Write-Host "      winget install hit a snag: $($_.Exception.Message)" -ForegroundColor Red
            $wingetAvailable = $false
        }
    }
    if (-not $wingetAvailable -or -not (Test-CommandExists "git")) {
        Write-Host "      Downloading Git for Windows installer directly..." -ForegroundColor Yellow
        try {
            $asset = Get-LatestGithubAsset -Repo "git-for-windows/git" -NamePattern '^Git-[\d\.]+-64-bit\.exe$'
            $gitExe = Join-Path $env:TEMP $asset.Name
            Write-Host "      Downloading $($asset.Name) (~60 MB)..." -ForegroundColor Yellow
            Download-File -Url $asset.Url -Destination $gitExe
            Write-Host "      Installing silently (takes ~90 seconds)..." -ForegroundColor Yellow
            $gitInstallArgs = @('/VERYSILENT','/NORESTART','/SUPPRESSMSGBOXES','/NOCANCEL','/SP-')
            $proc = Start-Process -FilePath $gitExe -ArgumentList $gitInstallArgs -Wait -PassThru
            if ($proc.ExitCode -ne 0) {
                throw "Git installer exit code $($proc.ExitCode)"
            }
            # Add Git to this session's PATH so the rest of the script can use it
            $gitBinPath = "$env:ProgramFiles\Git\bin"
            if (Test-Path $gitBinPath) { $env:PATH = "$gitBinPath;$env:PATH" }
            $gitCmdPath = "$env:ProgramFiles\Git\cmd"
            if (Test-Path $gitCmdPath) { $env:PATH = "$gitCmdPath;$env:PATH" }
            Write-Host "      Git ready." -ForegroundColor Green
        } catch {
            Write-Host "      Hmm, that didn't work: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "      Please install Git for Windows manually from https://git-scm.com/download/win" -ForegroundColor Red
            Start-Process "https://git-scm.com/download/win"
            exit 1
        }
    }
}

# Let Claude Code auto-discover the git-bash path (some versions need this env var set)
$bashCandidates = @(
    "$env:ProgramFiles\Git\bin\bash.exe",
    "${env:ProgramFiles(x86)}\Git\bin\bash.exe"
)
foreach ($candidate in $bashCandidates) {
    if (Test-Path $candidate) {
        [Environment]::SetEnvironmentVariable('CLAUDE_CODE_GIT_BASH_PATH', $candidate, 'User')
        $env:CLAUDE_CODE_GIT_BASH_PATH = $candidate
        Write-Host "      (Set CLAUDE_CODE_GIT_BASH_PATH=$candidate for your user profile.)" -ForegroundColor DarkGray
        break
    }
}

# -----------------------------------------------------------------------------
# Step 2 — Claude Code
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/5] Setting up Claude Code (the engine that powers Paperwik)..." -ForegroundColor Yellow

if (Test-CommandExists "claude") {
    Write-Host "      Already set up, moving on." -ForegroundColor Green
} else {
    try {
        Invoke-Expression (Invoke-RestMethod -Uri "https://claude.ai/install.ps1" -UseBasicParsing)
        Write-Host "      Claude Code ready." -ForegroundColor Green
    } catch {
        Write-Host "      Hmm, that didn't work: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "      You can try running it directly: irm https://claude.ai/install.ps1 | iex" -ForegroundColor Red
        exit 1
    }
}

# Add Claude Code's install dir to User PATH if it's missing
# (the Anthropic installer warns about this but doesn't fix it automatically)
$claudeLocalBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $claudeLocalBin) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $pathEntries = if ($userPath) { $userPath -split ';' | Where-Object { $_ } } else { @() }
    $alreadyPresent = $pathEntries | Where-Object { $_.TrimEnd('\') -eq $claudeLocalBin.TrimEnd('\') }
    if (-not $alreadyPresent) {
        $newUserPath = if ($userPath) { "$userPath;$claudeLocalBin" } else { $claudeLocalBin }
        [Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
        Write-Host "      (Added $claudeLocalBin to your user PATH.)" -ForegroundColor DarkGray
    }
    # Also patch the current session so later steps (and immediate re-run tests) work
    if (($env:PATH -split ';') -notcontains $claudeLocalBin) {
        $env:PATH = "$env:PATH;$claudeLocalBin"
    }
}

# -----------------------------------------------------------------------------
# Step 3 — Claude Desktop (GUI app; the entry point for non-technical users)
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/5] Setting up Claude Desktop (the app where you'll talk to Claude)..." -ForegroundColor Yellow

# Claude Desktop is a Squirrel/Electron app. Per-user install by default lands
# the launcher stub at %LOCALAPPDATA%\AnthropicClaude\Claude.exe (this is what
# the Start menu shortcut points at — versioned payload lives in subfolders
# like app-<version>\). We check for the stub.
$claudeDesktopCandidates = @(
    (Join-Path $env:LOCALAPPDATA "AnthropicClaude\Claude.exe"),     # per-user Squirrel install (default)
    (Join-Path $env:ProgramFiles "AnthropicClaude\Claude.exe"),     # all-users (rare)
    "${env:ProgramFiles(x86)}\AnthropicClaude\Claude.exe"
)

function Test-ClaudeDesktopInstalled {
    foreach ($candidate in $claudeDesktopCandidates) {
        if (Test-Path $candidate) { return $true }
    }
    return $false
}

if (Test-ClaudeDesktopInstalled) {
    Write-Host "      Already on your computer, moving on." -ForegroundColor Green
} else {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    $installed = $false
    if ($winget) {
        try {
            winget install -e --id Anthropic.Claude --accept-package-agreements --accept-source-agreements --silent
            # Squirrel finalize can take a few seconds after winget returns
            Start-Sleep -Seconds 3
            if (Test-ClaudeDesktopInstalled) {
                $installed = $true
                Write-Host "      Claude Desktop ready (via winget)." -ForegroundColor Green
            }
        } catch {
            Write-Host "      winget install didn't work, falling back to direct download..." -ForegroundColor Yellow
        }
    }
    if (-not $installed) {
        try {
            Write-Host "      Downloading Claude Desktop installer (~130 MB)..." -ForegroundColor Yellow
            # This is the URL claude.ai/download redirects to for Windows x64.
            # It's the stable "latest" asset — no version pinning needed.
            $claudeUrl = "https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-win-x64/Claude-Setup-x64.exe"
            $claudeExe = Join-Path $env:TEMP "Claude-Setup-x64.exe"
            Download-File -Url $claudeUrl -Destination $claudeExe
            Write-Host "      Installing silently..." -ForegroundColor Yellow
            # Squirrel installer: --silent runs without UI, per-user (no admin needed)
            $proc = Start-Process -FilePath $claudeExe -ArgumentList '--silent' -Wait -PassThru
            Start-Sleep -Seconds 5
            if (Test-ClaudeDesktopInstalled) {
                Write-Host "      Claude Desktop ready." -ForegroundColor Green
            } else {
                throw "Installer ran (exit $($proc.ExitCode)) but Claude.exe not found in expected locations"
            }
        } catch {
            Write-Host "      Direct install didn't work: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "      Opening Claude's download page so you can grab it by hand..." -ForegroundColor Yellow
            Start-Process "https://claude.ai/download"
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.MessageBox]::Show(
                "Automatic install didn't work on this machine.`n`nClaude's download page just opened in your browser. Install it manually, then re-run this bootstrap - it'll pick up where we left off.",
                "Claude Desktop - manual install",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
            exit 1
        }
    }
}

# -----------------------------------------------------------------------------
# Step 4 — Obsidian
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/5] Setting up Obsidian (where you'll read your notes)..." -ForegroundColor Yellow

$obsidianCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Obsidian\Obsidian.exe"),  # electron-builder default (per-user)
    (Join-Path $env:LOCALAPPDATA "Obsidian\Obsidian.exe"),            # legacy path
    (Join-Path $env:ProgramFiles "Obsidian\Obsidian.exe"),            # all-users install
    "${env:ProgramFiles(x86)}\Obsidian\Obsidian.exe"                  # 32-bit, rare
)

function Test-ObsidianInstalled {
    foreach ($candidate in $obsidianCandidates) {
        if (Test-Path $candidate) { return $true }
    }
    # Registry fallback: NSIS/electron-builder writes an uninstall entry.
    # Many uninstall subkeys lack DisplayName — guard every property access.
    $uninstallKeys = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $uninstallKeys) {
        if (-not (Test-Path $root)) { continue }
        try {
            $subkeys = Get-ChildItem -Path $root -ErrorAction SilentlyContinue
        } catch {
            continue
        }
        foreach ($sk in $subkeys) {
            try {
                $props = Get-ItemProperty -Path $sk.PSPath -ErrorAction SilentlyContinue
                if ($null -eq $props) { continue }
                # PSObject.Properties gives us safe access without throwing on missing members
                $displayNameProp = $props.PSObject.Properties['DisplayName']
                if ($null -eq $displayNameProp) { continue }
                $displayName = $displayNameProp.Value
                if ($displayName -and $displayName -like 'Obsidian*') {
                    return $true
                }
            } catch {
                continue
            }
        }
    }
    return $false
}

$obsidianInstalled = Test-ObsidianInstalled

if ($obsidianInstalled) {
    Write-Host "      Already on your computer, perfect." -ForegroundColor Green
} else {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    $installed = $false
    if ($winget) {
        try {
            winget install -e --id Obsidian.Obsidian --accept-package-agreements --accept-source-agreements --silent
            $installed = $true
            Write-Host "      Obsidian ready (via winget)." -ForegroundColor Green
        } catch {
            Write-Host "      winget install didn't work, falling back to direct download..." -ForegroundColor Yellow
        }
    }
    if (-not $installed) {
        try {
            Write-Host "      Fetching the latest Obsidian installer..." -ForegroundColor Yellow
            # Matches the standard x64 Windows installer (e.g. "Obsidian-1.12.7.exe").
            # The leading separator after "Obsidian" has been a hyphen in recent releases
            # but was a dot in older releases — accept either.
            $asset = Get-LatestGithubAsset -Repo "obsidianmd/obsidian-releases" -NamePattern '^Obsidian[-\.][\d\.]+\.exe$'
            $obsidianExe = Join-Path $env:TEMP $asset.Name
            Write-Host "      Downloading $($asset.Name) (~100 MB)..." -ForegroundColor Yellow
            Download-File -Url $asset.Url -Destination $obsidianExe
            Write-Host "      Installing silently..." -ForegroundColor Yellow
            # Obsidian uses electron-builder's NSIS installer. /S for silent, /currentuser
            # to force per-user install (no admin). Either works but /currentuser is
            # explicit about where things land.
            $proc = Start-Process -FilePath $obsidianExe -ArgumentList '/S' -Wait -PassThru
            # electron-builder NSIS finalize can take several seconds after the process exits
            Start-Sleep -Seconds 5
            if (Test-ObsidianInstalled) {
                Write-Host "      Obsidian ready." -ForegroundColor Green
            } else {
                throw "Installer ran (exit $($proc.ExitCode)) but Obsidian.exe not found in expected locations"
            }
        } catch {
            Write-Host "      Direct install didn't work: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "      Opening Obsidian's download page so you can grab it by hand..." -ForegroundColor Yellow
            Start-Process "https://obsidian.md/download"
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.MessageBox]::Show(
                "Automatic install didn't work on this machine.`n`nObsidian's download page just opened in your browser. Install it manually, then re-run this bootstrap - it'll pick up where we left off.",
                "Obsidian - manual install",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
            exit 1
        }
    }
}

# -----------------------------------------------------------------------------
# Step 5 — uv (Python runner used by Paperwik's retrieval scripts)
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/5] Setting up uv (a helper that runs Paperwik's search tools)..." -ForegroundColor Yellow

if (Test-CommandExists "uv") {
    Write-Host "      Already on your computer, great." -ForegroundColor Green
} else {
    try {
        Invoke-Expression (Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing)
        Write-Host "      uv ready." -ForegroundColor Green
        Write-Host "      (Heads up: close this window and open a new one so it sees the new setup.)" -ForegroundColor Yellow
    } catch {
        Write-Host "      Hmm, that didn't work: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "      You can try running it directly: irm https://astral.sh/uv/install.ps1 | iex" -ForegroundColor Red
        exit 1
    }
}

# -----------------------------------------------------------------------------
# Finish — tell user what comes next
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host "  Nice! The setup is done." -ForegroundColor Green
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Here's what happens next (your installer will walk you through these):" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Close this window."
Write-Host "  2. Open Claude Desktop from your Start menu."
Write-Host "  3. Start a Claude Code session inside Claude Desktop."
Write-Host "  4. The first time, Claude will open a browser for you to sign in."
Write-Host "     Click Approve and come back."
Write-Host "  5. At the Claude Code prompt, paste these two lines:"
Write-Host ""
Write-Host "        /plugin marketplace add s0phak1ng/paperwik" -ForegroundColor Yellow
Write-Host "        /plugin install paperwik" -ForegroundColor Yellow
Write-Host ""
Write-Host "  6. Restart Claude Code (type '/exit' then start it again)."
Write-Host "  7. First-time setup runs itself - it takes about 3-5 minutes"
Write-Host "     while the search pieces download. After that, you're ready."
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
