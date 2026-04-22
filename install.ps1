<#
.SYNOPSIS
    One-line Paperwik bootstrap. Hosted on GitHub Pages for easy remote
    execution: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`

.DESCRIPTION
    Runs four install commands in sequence:
        1. Install Git for Windows (provides git + git-bash, required by Claude Code)
        2. Install Claude Code via Anthropic's official script
        3. Install Obsidian (winget preferred, direct download as fallback)
        4. Install uv (Python runner used by Paperwik's retrieval scripts)

    Does NOT install the plugin itself — plugin install requires Claude Code's
    own /plugin marketplace + /plugin install slash commands, which only work
    inside the CLI. The installer walks the user through those during the
    day-one session.

.NOTES
    v0.1.1 — friends-and-family bootstrap. No admin rights required.
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
Write-Host "  I'll install four small tools. About 4 minutes total." -ForegroundColor Cyan
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
Write-Host "[1/4] Setting up Git for Windows (Claude Code needs git-bash)..." -ForegroundColor Yellow

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
Write-Host "[2/4] Setting up Claude Code (the agent that lives inside Claude Desktop)..." -ForegroundColor Yellow

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
# Step 3 — Obsidian
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Setting up Obsidian (where you'll read your notes)..." -ForegroundColor Yellow

$obsidianCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Obsidian\Obsidian.exe"),
    (Join-Path $env:ProgramFiles "Obsidian\Obsidian.exe")
)
$obsidianInstalled = $false
foreach ($candidate in $obsidianCandidates) {
    if (Test-Path $candidate) { $obsidianInstalled = $true; break }
}

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
            $asset = Get-LatestGithubAsset -Repo "obsidianmd/obsidian-releases" -NamePattern '^Obsidian\.[\d\.]+\.exe$'
            $obsidianExe = Join-Path $env:TEMP $asset.Name
            Write-Host "      Downloading $($asset.Name) (~100 MB)..." -ForegroundColor Yellow
            Download-File -Url $asset.Url -Destination $obsidianExe
            Write-Host "      Installing silently..." -ForegroundColor Yellow
            # Obsidian uses electron-builder's NSIS installer — /S does silent install
            $proc = Start-Process -FilePath $obsidianExe -ArgumentList '/S' -Wait -PassThru
            # Some NSIS builds return 0 even on silent; double-check by looking for the install artifact
            Start-Sleep -Seconds 2
            $foundAfter = $false
            foreach ($candidate in $obsidianCandidates) {
                if (Test-Path $candidate) { $foundAfter = $true; break }
            }
            if ($foundAfter) {
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
                "Automatic install didn't work on this machine.`n`nObsidian's download page just opened in your browser. Install it manually, then re-run this bootstrap — it'll pick up where we left off.",
                "Obsidian - manual install",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
            exit 1
        }
    }
}

# -----------------------------------------------------------------------------
# Step 4 — uv (Python runner used by Paperwik's retrieval scripts)
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Setting up uv (a helper that runs Paperwik's search tools)..." -ForegroundColor Yellow

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
Write-Host "  2. Open Claude Desktop (or a fresh PowerShell, if that's your path)."
Write-Host "  3. Start Claude Code."
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
