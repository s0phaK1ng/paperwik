<#
.SYNOPSIS
    One-line Paperwik bootstrap. Hosted on GitHub Pages for easy remote
    execution: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`

.DESCRIPTION
    Runs three install commands in sequence:
        1. Install Claude Code via Anthropic's official script
        2. Install Obsidian via winget (with browser-fallback if winget absent)
        3. Print the two slash commands the user types inside Claude Code

    Does NOT install the plugin itself — plugin install requires Claude Code's
    own /plugin marketplace + /plugin install slash commands, which only work
    inside the CLI. The installer walks the user through those during the day-one session.

.NOTES
    v1.0 — friends-and-family bootstrap. No admin rights required.
#>

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Hello! Welcome to Paperwik.                                 ║" -ForegroundColor Cyan
Write-Host "║   I'll install three small tools. About 3 minutes total.      ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------------
# Step 1 — Claude Code
# -----------------------------------------------------------------------------
Write-Host "[1/3] Setting up Claude Code (it lives inside Claude Desktop)..." -ForegroundColor Yellow

$claudeInstalled = $null -ne (Get-Command claude -ErrorAction SilentlyContinue)
if ($claudeInstalled) {
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
# Step 2 — Obsidian
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/3] Setting up Obsidian (where you'll read your notes)..." -ForegroundColor Yellow

$winget = Get-Command winget -ErrorAction SilentlyContinue
$obsidianExe = Join-Path $env:LOCALAPPDATA "Obsidian\Obsidian.exe"

if (Test-Path $obsidianExe) {
    Write-Host "      Already on your computer — perfect." -ForegroundColor Green
} elseif ($winget) {
    try {
        winget install -e --id Obsidian.Obsidian --accept-package-agreements --accept-source-agreements
        Write-Host "      Obsidian ready." -ForegroundColor Green
    } catch {
        Write-Host "      That one didn't work — let's do it by hand. Opening Obsidian's download page..." -ForegroundColor Yellow
        Start-Process "https://obsidian.md/download"
        Write-Host "      Install Obsidian from the browser window that just opened." -ForegroundColor Yellow
        Write-Host "      When you're done, run this installer again — it'll pick up where we left off." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "      Your Windows version is a little older than winget needs." -ForegroundColor Yellow
    Write-Host "      No worries — opening Obsidian's download page for you..." -ForegroundColor Yellow
    Start-Process "https://obsidian.md/download"
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Your Windows version is a little older than winget needs (we look for Win10 21H2 or newer).`n`nObsidian's download page just opened in your browser. Install it, then come back and your installer can help with the rest.",
        "Obsidian — manual install",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
    exit 0
}

# -----------------------------------------------------------------------------
# Step 3 — uv (Python runner used by plugin scripts)
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/3] Setting up uv (a helper that runs Paperwik's search tools)..." -ForegroundColor Yellow

$uvInstalled = $null -ne (Get-Command uv -ErrorAction SilentlyContinue)
if ($uvInstalled) {
    Write-Host "      Already on your computer — great." -ForegroundColor Green
} else {
    try {
        Invoke-Expression (Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing)
        Write-Host "      uv ready." -ForegroundColor Green
        Write-Host "      (Heads up: you'll want to close this window and open a new one so it sees the new setup.)" -ForegroundColor Yellow
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
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Nice! The setup is done." -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
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
Write-Host "  7. First-time setup runs itself — it takes about 3-5 minutes"
Write-Host "     while the search pieces download. After that, you're ready."
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
