<#
.SYNOPSIS
    One-line Paperwik bootstrap. Hosted on GitHub Pages for easy remote
    execution: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`

.DESCRIPTION
    Runs six install commands in sequence:
        1. Install Git for Windows (provides git + git-bash, required by Claude Code)
        2. Install Claude Code CLI via Anthropic's official script
        3. Install Claude Desktop (general chat GUI; not the plugin entry point)
        4. Install Obsidian (winget preferred, direct download as fallback)
        5. Install Microsoft Visual C++ 2015-2022 Redistributable (x64) —
           required by onnxruntime + spaCy native extensions that Paperwik's
           retrieval stack (fastembed + flashrank + spaCy) links against.
           Missing on fresh Windows Sandbox / minimal Windows installs.
        6. Install uv (Python runner used by Paperwik's retrieval scripts)

    Does NOT install the plugin itself — plugin install requires Claude Code's
    own /plugin marketplace + /plugin install slash commands, which only work
    inside the CLI. The installer walks the user through those during the
    day-one session.

    NOTE: Paperwik's plugin commands run in the Claude Code CLI (launched by
    typing `claude` in PowerShell), NOT in Claude Desktop's "Code" tab.
    Claude Desktop is useful for general chat and is installed for that,
    but the plugin system only exists in the terminal-hosted CLI.

.NOTES
    v0.1.8 — friends-and-family bootstrap. No admin rights required except
    for the VC++ Redist step (which UAC-elevates itself silently via the
    manifest embedded in vc_redist.x64.exe).

    Changes from v0.1.7:
      - NEW Step 5: install Microsoft Visual C++ Redistributable. Fresh
        Windows Sandbox + some minimal Windows installs lack it, which
        causes onnxruntime (fastembed, flashrank) and spaCy's numpy ops
        to fail DLL load with a cryptic message during the first ingest.
        Uses winget (Microsoft.VCRedist.2015+.x64) with direct-download
        fallback from aka.ms/vs/17/release/vc_redist.x64.exe.
      - Renumbered to 6 total steps (banner + final message updated).
      - Harden step 6 (uv): verify ~/.local/bin/uv.exe actually exists
        after astral's installer runs; if not, download uv directly from
        GitHub releases. (User hit this silent failure on v0.1.7.)
      - Bump Download-File timeout 600s -> 1200s for slow networks.
      - Add MSIX detection to Test-ClaudeDesktopInstalled (avoid trying
        to reinstall when Claude Desktop was previously installed via
        winget's MSIX path rather than the user-scope .exe).
      - Rewrite final "what happens next" message. v0.1.5 pointed users
        at Claude Desktop's "Code" tab for plugin install, which is wrong
        — that tab doesn't support /plugin. The plugin commands require
        the terminal CLI. New message says: open PowerShell, type claude,
        run the plugin commands, restart.

    Changes from v0.1.6:
      - Fix Claude Desktop installing an ancient 0.14.10 stub instead of
        the actual latest release. Two traps overlapped:
          (a) The storage.googleapis.com/osprey-downloads-... Squirrel
              bucket is frozen at 0.14.10 and does NOT auto-update.
          (b) Anthropic's own "latest redirect" endpoint
              (claude.ai/api/desktop/win32/x64/setup/latest/redirect) is
              behind a Cloudflare bot challenge that blocks scripted
              fetches - curl and Invoke-WebRequest both get 403. So we
              can't use it as the download source.
        Fix: at install time, fetch the microsoft/winget-pkgs manifest
        folder for Anthropic.Claude from the GitHub contents API, pick
        the highest [version]-parseable subfolder, fetch its installer
        YAML from raw.githubusercontent.com, extract the x64 .exe
        user-scope InstallerUrl, and download directly from
        downloads.claude.ai (plain CDN, no bot challenge). The manifest
        trails real latest by hundreds of builds but Claude Desktop
        auto-updates itself on first launch, so lag is cosmetic.
        winget stays on as a last-resort fallback.
        New helper: Get-LatestClaudeDesktopUrl.
        Step 3 order flipped: direct-from-manifest first, winget second.

    Changes from v0.1.5:
      - Pre-empt the Anthropic installer's "add ~/.local/bin to your PATH
        manually" warning. Previously v0.1.2 added the PATH entry AFTER the
        installer ran, which worked but left the user staring at a scary
        "open System Properties -> Environment Variables ..." instruction
        they didn't need to follow. Now we create the dir and add it to
        PATH (both User registry and current session) BEFORE calling the
        installer, so its PATH check passes and it stays quiet.

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
Write-Host "  I'll install six small tools. About 5 minutes total." -ForegroundColor Cyan
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
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -UserAgent 'Paperwik-Installer/0.1.8' -TimeoutSec 1200
}

function Get-LatestClaudeDesktopUrl {
    # Return @{ Version; Url } for the most recent x64 .exe user-scope
    # Claude Desktop build, sourced from the microsoft/winget-pkgs manifest
    # repo. Why this path:
    #   * Anthropic's own "latest redirect" endpoint
    #     (claude.ai/api/desktop/win32/x64/setup/latest/redirect) sits
    #     behind a Cloudflare bot challenge that blocks scripted fetches,
    #     so we can't rely on it in an installer.
    #   * The legacy Squirrel bucket (storage.googleapis.com/osprey-
    #     downloads-.../Claude-Setup-x64.exe) is frozen at an ancient
    #     0.14.x stub that does NOT auto-update, so we must avoid it.
    #   * winget-pkgs trails real latest by a few hundred builds but is
    #     stable and anonymous-fetchable. Claude Desktop auto-updates
    #     itself after install, so the small lag is harmless.
    # The actual file lives on downloads.claude.ai, which is plain CDN
    # (no Cloudflare challenge for the binary itself).
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $headers = @{ 'User-Agent' = 'Paperwik-Installer/0.1.7'; 'Accept' = 'application/vnd.github+json' }

    $apiUrl = 'https://api.github.com/repos/microsoft/winget-pkgs/contents/manifests/a/Anthropic/Claude'
    $dirs = Invoke-RestMethod -Uri $apiUrl -Headers $headers -UseBasicParsing -TimeoutSec 30
    $versionNames = @($dirs | Where-Object { $_.type -eq 'dir' } | ForEach-Object { $_.name })
    if (-not $versionNames) { throw "No Anthropic.Claude version folders in winget-pkgs" }
    $parsed = @($versionNames | ForEach-Object {
        try { [pscustomobject]@{ Name = $_; Version = [version]$_ } } catch { $null }
    } | Where-Object { $_ })
    if (-not $parsed) { throw "Could not parse any Anthropic.Claude version strings" }
    $latest = ($parsed | Sort-Object -Property Version -Descending | Select-Object -First 1).Name

    $yamlUrl = "https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/a/Anthropic/Claude/$latest/Anthropic.Claude.installer.yaml"
    $yaml = Invoke-RestMethod -Uri $yamlUrl -Headers $headers -UseBasicParsing -TimeoutSec 30

    # Target the single line that declares the x64 .exe installer. The
    # manifest has 4 installer entries (x64 msix, arm64 msix, x64 exe,
    # arm64 exe); the URL pattern uniquely identifies the x64 exe.
    $urlLine = ($yaml -split "`n") | Where-Object {
        $_ -match 'InstallerUrl:\s*https://downloads\.claude\.ai/releases/win32/x64/[\d\.]+/Claude-[a-f0-9]+\.exe\s*$'
    } | Select-Object -First 1
    if (-not $urlLine -or $urlLine -notmatch 'InstallerUrl:\s*(\S+)') {
        throw "x64 .exe installer URL not found in Anthropic.Claude $latest manifest"
    }
    return @{ Version = $latest; Url = $Matches[1] }
}

# -----------------------------------------------------------------------------
# Step 1 — Git for Windows (provides git + git-bash; Claude Code requires bash)
# -----------------------------------------------------------------------------
Write-Host "[1/6] Setting up Git for Windows (Claude Code needs git-bash)..." -ForegroundColor Yellow

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
Write-Host "[2/6] Setting up Claude Code (the engine that powers Paperwik)..." -ForegroundColor Yellow

# The Anthropic installer drops claude.exe into ~/.local/bin and, if that
# folder isn't in PATH, prints a scary "Add it by opening System Properties
# -> Environment Variables ..." note telling the user to edit environment
# variables by hand. Pre-empt it: create the folder, make sure it's in both
# the persisted User PATH and this session's PATH, THEN run their installer.
# With the PATH check already satisfied, the warning never fires.
$claudeLocalBin = Join-Path $env:USERPROFILE ".local\bin"
if (-not (Test-Path $claudeLocalBin)) {
    New-Item -ItemType Directory -Path $claudeLocalBin -Force | Out-Null
}
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathEntries = if ($userPath) { $userPath -split ';' | Where-Object { $_ } } else { @() }
$alreadyPresent = $pathEntries | Where-Object { $_.TrimEnd('\') -eq $claudeLocalBin.TrimEnd('\') }
if (-not $alreadyPresent) {
    $newUserPath = if ($userPath) { "$userPath;$claudeLocalBin" } else { $claudeLocalBin }
    [Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
}
if (($env:PATH -split ';') -notcontains $claudeLocalBin) {
    $env:PATH = "$env:PATH;$claudeLocalBin"
}

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

# -----------------------------------------------------------------------------
# Step 3 — Claude Desktop (GUI app for general chat; not the Paperwik entry point)
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] Setting up Claude Desktop (great for general chat; Paperwik runs in PowerShell)..." -ForegroundColor Yellow

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
    # Per-user Squirrel .exe install
    foreach ($candidate in $claudeDesktopCandidates) {
        if (Test-Path $candidate) { return $true }
    }
    # MSIX install (winget sometimes prefers this path on admin installs) —
    # lands under C:\Program Files\WindowsApps\Claude_<version>_x64__<publisher>\
    try {
        $appx = Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -like '*Claude*' -and $_.Publisher -match 'Anthropic'
        } | Select-Object -First 1
        if ($appx) { return $true }
    } catch { }
    return $false
}

if (Test-ClaudeDesktopInstalled) {
    Write-Host "      Already on your computer, moving on." -ForegroundColor Green
} else {
    $installed = $false

    # Primary: resolve the current x64 .exe installer URL via the
    # winget-pkgs manifest on GitHub, then download directly from
    # downloads.claude.ai (plain CDN, no auth, no bot challenge). See
    # Get-LatestClaudeDesktopUrl for why we skip Anthropic's official
    # "latest redirect" endpoint and the frozen osprey bucket.
    try {
        Write-Host "      Looking up the latest Claude Desktop release..." -ForegroundColor Yellow
        $latest = Get-LatestClaudeDesktopUrl
        Write-Host "      Downloading Claude Desktop $($latest.Version) (~200 MB, takes a minute)..." -ForegroundColor Yellow
        $claudeExe = Join-Path $env:TEMP "Claude-$($latest.Version).exe"
        Download-File -Url $latest.Url -Destination $claudeExe
        Write-Host "      Installing silently..." -ForegroundColor Yellow
        # --silent is the documented silent switch per the winget manifest
        $proc = Start-Process -FilePath $claudeExe -ArgumentList '--silent' -Wait -PassThru
        Start-Sleep -Seconds 5
        if (Test-ClaudeDesktopInstalled) {
            $installed = $true
            Write-Host "      Claude Desktop $($latest.Version) ready." -ForegroundColor Green
        }
    } catch {
        Write-Host "      Couldn't resolve latest release ($($_.Exception.Message)), trying winget..." -ForegroundColor Yellow
    }

    # Fallback: winget install, which ends up using the same manifest
    # but goes through winget's own download+install machinery. Only
    # relevant if GitHub is unreachable or the manifest parse failed.
    if (-not $installed) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            try {
                winget install -e --id Anthropic.Claude --accept-package-agreements --accept-source-agreements --silent
                Start-Sleep -Seconds 3
                if (Test-ClaudeDesktopInstalled) {
                    $installed = $true
                    Write-Host "      Claude Desktop ready (via winget; auto-updates on first launch)." -ForegroundColor Green
                }
            } catch {
                Write-Host "      winget fallback also didn't work." -ForegroundColor Yellow
            }
        }
    }

    if (-not $installed) {
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

# -----------------------------------------------------------------------------
# Step 4 — Obsidian
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/6] Setting up Obsidian (where you'll read your notes)..." -ForegroundColor Yellow

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
# Step 5 — Microsoft Visual C++ 2015-2022 Redistributable (x64)
# -----------------------------------------------------------------------------
# onnxruntime (used by fastembed + flashrank) and spaCy's compiled numpy ops
# link against vcruntime140.dll + msvcp140.dll. Fresh Windows Sandbox and some
# minimal Windows installs ship without them, which causes cryptic DLL load
# failures during the first ingest. Install unconditionally - the Microsoft
# installer is idempotent and exits quickly if already present.
Write-Host ""
Write-Host "[5/6] Setting up Visual C++ Redistributable (needed by the search engine)..." -ForegroundColor Yellow

function Test-VCRedistInstalled {
    (Test-Path "$env:WINDIR\System32\vcruntime140.dll") -and (Test-Path "$env:WINDIR\System32\msvcp140.dll")
}

if (Test-VCRedistInstalled) {
    Write-Host "      Already on your computer, skipping." -ForegroundColor Green
} else {
    $installed = $false
    # Try winget first (cleaner, self-updating)
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            winget install --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements
            Start-Sleep -Seconds 2
            if (Test-VCRedistInstalled) {
                $installed = $true
                Write-Host "      VC++ Redist ready (via winget)." -ForegroundColor Green
            }
        } catch {
            Write-Host "      winget install didn't work, falling back to direct download..." -ForegroundColor Yellow
        }
    }
    if (-not $installed) {
        try {
            Write-Host "      Downloading the redistributable..." -ForegroundColor Yellow
            $vc = Join-Path $env:TEMP "vc_redist.x64.exe"
            Download-File -Url 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -Destination $vc
            Write-Host "      Installing silently..." -ForegroundColor Yellow
            # /install /quiet /norestart - Microsoft's silent-install flags for this installer
            $proc = Start-Process -FilePath $vc -ArgumentList '/install','/quiet','/norestart' -Wait -PassThru
            Remove-Item $vc -ErrorAction SilentlyContinue
            # Exit codes: 0 = success, 3010 = success but reboot recommended. Both OK.
            if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
                throw "vc_redist installer returned exit code $($proc.ExitCode)"
            }
            if (Test-VCRedistInstalled) {
                Write-Host "      VC++ Redist ready." -ForegroundColor Green
            } else {
                throw "Installer ran (exit $($proc.ExitCode)) but vcruntime140.dll / msvcp140.dll not found"
            }
        } catch {
            Write-Host "      VC++ Redist install failed: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "      The retrieval stack won't load without it. Please install manually from:" -ForegroundColor Red
            Write-Host "        https://aka.ms/vs/17/release/vc_redist.x64.exe" -ForegroundColor Red
            Start-Process "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            exit 1
        }
    }
}

# -----------------------------------------------------------------------------
# Step 6 — uv (Python runner used by Paperwik's retrieval scripts)
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[6/6] Setting up uv (a helper that runs Paperwik's search tools)..." -ForegroundColor Yellow

$uvExe = Join-Path $env:USERPROFILE ".local\bin\uv.exe"

function Test-UvAvailable {
    if (Test-CommandExists "uv") { return $true }
    if (Test-Path $uvExe) { return $true }
    return $false
}

if (Test-UvAvailable) {
    Write-Host "      Already on your computer, great." -ForegroundColor Green
} else {
    # First try Astral's official installer. It sometimes calls `exit` at the
    # end which closes the hosting PowerShell process, so we isolate it in a
    # child process via Start-Process.
    $installerRan = $false
    try {
        Start-Process powershell -Wait -ArgumentList `
            '-NoProfile','-ExecutionPolicy','Bypass', `
            '-Command','irm https://astral.sh/uv/install.ps1 | iex' | Out-Null
        Start-Sleep -Seconds 2
        $installerRan = $true
    } catch {
        Write-Host "      Astral installer didn't run cleanly: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    # Astral's script silently no-ops on some sandboxes. Verify uv.exe actually
    # landed, and fall back to direct binary download from GitHub if not.
    if (-not (Test-Path $uvExe)) {
        if ($installerRan) {
            Write-Host "      Astral installer didn't drop uv.exe at the expected path; pulling the binary directly..." -ForegroundColor Yellow
        } else {
            Write-Host "      Downloading uv binary directly from GitHub releases..." -ForegroundColor Yellow
        }
        try {
            $zipUrl = 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'
            $zip    = Join-Path $env:TEMP "uv.zip"
            $dest   = Join-Path $env:USERPROFILE ".local\bin"
            New-Item -ItemType Directory -Path $dest -Force | Out-Null
            Download-File -Url $zipUrl -Destination $zip
            Expand-Archive -Path $zip -DestinationPath $dest -Force
            Remove-Item $zip -ErrorAction SilentlyContinue
        } catch {
            Write-Host "      Direct uv download also failed: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "      Please install uv manually from https://astral.sh/uv" -ForegroundColor Red
            exit 1
        }
    }

    if (Test-Path $uvExe) {
        Write-Host "      uv ready at $uvExe." -ForegroundColor Green
    } else {
        Write-Host "      uv is still not where we expected after install." -ForegroundColor Red
        Write-Host "      Please install it manually from https://astral.sh/uv and re-run this bootstrap." -ForegroundColor Red
        exit 1
    }

    # Make uv visible to this session so any follow-up work in the same shell sees it
    if (($env:PATH -split ';') -notcontains (Split-Path -Parent $uvExe)) {
        $env:PATH = "$env:PATH;$(Split-Path -Parent $uvExe)"
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
Write-Host "Here's what happens next:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Close this PowerShell window."
Write-Host "  2. Open a fresh PowerShell (press Win, type 'powershell', hit Enter)."
Write-Host "  3. Paste these three lines (one at a time, Enter after each):"
Write-Host ""
Write-Host "        cd ~" -ForegroundColor Yellow
Write-Host "        claude" -ForegroundColor Yellow
Write-Host ""
Write-Host "     The first time, Claude will open a browser for you to sign in."
Write-Host "     Click Approve and come back to the window."
Write-Host ""
Write-Host "  4. At the Claude prompt, paste these two commands:"
Write-Host ""
Write-Host "        /plugin marketplace add s0phak1ng/paperwik" -ForegroundColor Yellow
Write-Host "        /plugin install paperwik@paperwik" -ForegroundColor Yellow
Write-Host ""
Write-Host "  5. Type '/exit' to quit, then run 'claude' again."
Write-Host "     On this second launch, your Knowledge vault gets built (30-60s)."
Write-Host ""
Write-Host "  6. When you see 'Welcome - your knowledge vault is ready', open"
Write-Host "     Obsidian and pick 'Open folder as vault' to point at:"
Write-Host "        C:\Users\$env:USERNAME\Knowledge"
Write-Host ""
Write-Host "  Note: use PowerShell (not Claude Desktop's Code tab) for the plugin"
Write-Host "        commands. Claude Desktop is great for general chat, but the"
Write-Host "        plugin system only works in the terminal CLI."
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
