<#
.SYNOPSIS
    One-line Paperwik bootstrap. Hosted on GitHub Pages for easy remote
    execution: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`

.DESCRIPTION
    Runs seven install commands in sequence:
        1. Install Git for Windows (provides git + git-bash, required by Claude Code)
        2. Install Claude Code CLI via Anthropic's official script
        3. Install Claude Desktop (general chat GUI; not the plugin entry point)
        4. Install Obsidian (winget preferred, direct download as fallback)
        5. Install Microsoft Visual C++ 2015-2022 Redistributable (x64)
        6. Install uv (Python runner used by Paperwik's retrieval scripts)
        7. Install and pre-register the Paperwik plugin, build the Paperwik
           vault, so the user's first `claude` launch has everything ready —
           no manual /plugin marketplace add or /plugin install required.

    Claude Code reads ~/.claude/settings.json on startup. By pre-cloning the
    plugin repo to ~/.claude/plugins/marketplaces/paperwik/ and registering
    it in extraKnownMarketplaces + enabledPlugins, we eliminate the need for
    the user to type any slash commands. The scaffolder runs at install time
    (we already have uv + plugin repo on disk) so ~/Paperwik/ exists before
    Claude Code is even opened.

    NOTE: Paperwik runs in the Claude Code CLI (terminal, launched by typing
    `claude` in PowerShell), NOT in Claude Desktop's "Code" tab. Claude
    Desktop is installed for general chat but the plugin system only exists
    in the terminal-hosted CLI.

.NOTES
    v0.2.8 — friends-and-family bootstrap. Fixes two issues in v0.2.7's
    silent auto-archive implementation discovered during the first
    real end-to-end test.

    Issue 1 (critical): Auto-Commit hook timed out during initial
    snapshot. On a fresh vault, `git add -A` stages knowledge.db
    (~50 MB binary) plus source files plus the full template tree.
    With the hook's 5s timeout budget, this was killed mid-operation,
    leaving a stale .git/index.lock that wedged all future git calls.
    Every subsequent hook run also failed ("Another git process seems
    to be running in this repository, or the lock file may be stale").

    Issue 2 (silent): Chat-Archive hook produced no output on real
    Desktop sessions — chat-history/ remained empty. Manual invocation
    with a synthetic payload worked, suggesting Desktop may not be
    piping the hook payload through stdin the same way the CLI does,
    OR the hook was silently hitting one of several early-exit paths.
    No log entries from the hook itself to distinguish.

    Changes from v0.2.7:
      - install.ps1 step 7(c3): NEW. Initialize git repo + first
        snapshot inside ~/Paperwik after scaffolder + settings
        refresh. No time pressure here — user is watching install
        progress, not a hook timeout. Hook's only job going forward
        is incremental commits, which are fast. Idempotent: skipped
        if .git already exists from a prior install.
      - Auto-Commit.ps1: REMOVED the init-in-hook branch. If .git is
        missing when hook fires, skip with a diagnostic log entry
        instead of trying to init (would just wedge again). ADDED
        stale-lock recovery: delete .git/index.lock if older than
        30 seconds (safely assumes no live git operation in flight).
        Prevents permanent wedge if a timeout ever does hit.
      - .gitignore template: added .claude/chat-history/ to the
        existing ignores. Chat transcript mirror is re-written every
        turn; no version-control value per-revision. Keeps commits
        small and fast.
      - hooks.json: bumped Auto-Commit + Chat-Archive timeouts from
        5s to 15s. Cheap insurance.
      - Chat-Archive.ps1: added Append-DiagLog calls on every
        early-exit path (no stdin, bad JSON, missing transcript_path,
        transcript file not found). Also FIRED log on successful
        processing. Next test will either tell us exactly why the
        hook bailed or confirm it's running silently as designed.
      - plugin.json + marketplace.json bumped 0.2.7 -> 0.2.8.
      - No install.ps1 core flow changes beyond the new 7(c3) step.

    Upgrade path: run the one-liner again OR
        git -C $HOME\.claude\plugins\marketplaces\paperwik pull
        rm -rf $HOME\Paperwik\.git   # if previous install left a broken one
        # then in Claude Desktop: + -> Plugins -> paperwik -> Update
    After Update, Desktop reloads the new hooks.json + scripts.

    Changes from v0.2.6:
      - NEW hook: PostToolUse -> Auto-Commit.ps1. After any Write /
        Edit / MultiEdit / NotebookEdit, runs `git add -A && git commit`
        inside ~/Paperwik/. Initializes the repo on first run. Gives
        the user an Undo capability via git log / git revert. Silent.
      - NEW hook: Stop -> Chat-Archive.ps1. After every assistant turn:
        (a) mirrors the full session transcript from Claude Code's
            cache into ~/Paperwik/.claude/chat-history/<session>.jsonl
            so the complete chat is always in the vault on disk;
        (b) regex-scans the turn's user+assistant text for decision
            language ("let's go with X", "we decided", "final answer",
            "I'll use X", "going forward", "settle on X", etc.) and
            silently appends matches to ~/Paperwik/decisions.md.
            Never asks. Never prompts. Non-blocking.
      - REMOVED: skills/auto-file-chat/ (replaced by Chat-Archive hook).
      - REMOVED: skills/decision-logger/ (replaced by silent regex in
        Chat-Archive hook). The old skill asked the user before logging;
        the new hook logs automatically per the "never ask" directive.
      - CLAUDE.md template gains a "Silent auto-archive" section that
        tells the agent these hooks run every turn and it should not
        duplicate their work (don't manually update decisions.md, don't
        try to file chat to disk — hooks handle it).
      - plugin.json + marketplace.json bumped 0.2.6 -> 0.2.7.
      - No install.ps1 code changes — fix lands through plugin git pull.

    Changes from v0.2.5:
      - templates/paperwik/.claude/settings.json:
          defaultMode: "dontAsk" -> "bypassPermissions" (Anthropic's
              documented strict-yolo mode; stronger than dontAsk)
          allow: added Bash(*) so ordinary shell commands auto-approve
          deny: expanded with format, diskpart, shutdown, taskkill /F,
              del /f /s /q, rmdir /S /Q, rm -fr, Remove-Item * -Recurse
      - install.ps1 step 7(c2): NEW migration step that unconditionally
        refreshes the vault's .claude/settings.json from the template
        on every install run. The scaffolder is sentinel-gated so it
        only writes settings.json once; without this explicit refresh,
        existing installs would keep their old narrow permissions
        after a plugin update. The user's previous settings.json is
        backed up to settings.json.bak-<timestamp> before overwrite.
      - plugin.json + marketplace.json bumped to 0.2.6.

    Deny list still blocks destructive ops: C:/** writes, .obsidian/,
    .git/, CLAUDE.md, knowledge.db, git push --force, git reset --hard,
    git branch -D, git filter-branch/repo, rm -rf, Remove-Item -Recurse,
    format, diskpart, shutdown, taskkill /F, del /f /s /q, rmdir /S /Q.
    The PreToolUse-Governor.ps1 hook remains a second safety gate.

    Changes from v0.2.4:
      - All user-facing SKILL.md files (ingest, lint, redact,
        rebuild-index, measure-retrieval) now use a bash fallback
        pattern at the top of each invocation:
            PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
            uv run "$PAPERWIK_PLUGIN/scripts/X.py"
        Works whether or not Claude Code exposes the env var.
      - CLAUDE.md template gains a "Plugin files location" section
        that tells the agent exactly where the Python scripts live
        (`$HOME/.claude/plugins/marketplaces/paperwik/scripts/`) and
        warns against searching for them under `~/Paperwik/scripts/`
        (which does not exist on a standard install).
      - plugin.json + marketplace.json versions bumped 0.2.0 -> 0.2.5
        so Claude Code sees this as a new version to re-fetch.
      - No code changes in install.ps1 itself. Shipping v0.2.5 so
        existing users reinstalling pick up the new plugin content.

    Changes from v0.2.3:
      - Final-message step 2 now warns: "If Claude was already open
        during install, FULLY QUIT IT FIRST (tray icon -> Quit), then
        reopen." Addresses the case where the user had Claude open
        when they ran the installer.
      - Final-message step 5 gains a fallback paragraph: "If you don't
        see 'Personal' at all, fully quit Claude and reopen." Addresses
        the case where even a clean first-launch fails to surface the
        plugin until a second launch.
      - No code changes. Text-only.

    Changes from v0.2.2:
      - Fix the extraKnownMarketplaces source shape written to
        ~/.claude/settings.json. v0.2.2 wrote:
            "source": { "source": "github", "repo": "s0phak1ng/paperwik" }
        which the Claude Code CLI accepts but Claude Desktop's Plugin UI
        silently ignores. v0.2.3 writes the canonical form used by
        anthropics/claude-plugins-official and accepted by both CLI and
        Desktop:
            "source": { "source": "git",
                        "url": "https://github.com/s0phak1ng/paperwik.git" }
        Verified empirically: with the github/repo shape, paperwik is
        invisible in Desktop's + → Plugins browser AND Manage plugins list.
        With the git/url shape, paperwik appears under Personal and can be
        enabled.
      - Update the installer's final message to walk the user through the
        one-click enablement step inside Desktop's Plugin UI. Even with
        the correct marketplace shape pre-registered, Desktop still
        requires an explicit user click at:
            Claude Desktop → Code tab → + button → Plugins → paperwik →
            (the + / enable control in the plugin detail panel)
        before the plugin's skills surface in the / autocomplete and
        auto-trigger on natural language. The CLI does not need this
        click - the enabledPlugins flag in settings.json is sufficient
        there. This is a Desktop-specific UX gate we cannot yet pre-fill
        from the installer (investigated: the click does not modify
        settings.json or ~/.claude.json visibly, so the state is either
        in-memory or in a private Desktop store we haven't located).
        Flagged in decision #309 for future investigation.

    Changes from v0.2.1:
      - Renamed the plugin's internal identifier from "paperwik" to "pw".
        Brand + marketplace + GitHub repo + install URL all still say
        "paperwik". Only the plugin id (which drives slash-command
        namespacing) is short, so slash commands become /pw:ingest,
        /pw:lint, etc. instead of /paperwik:ingest-source.
          * plugin.json: name -> "pw", version bumped to 0.2.0
          * marketplace.json: plugins[].name -> "pw"
          * install.ps1: settings.json enabledPlugins key is now
            "pw@paperwik". Also scrubs any stale "paperwik@paperwik" entry
            from existing installs (migration) so Claude Code doesn't warn
            about a missing plugin named "paperwik".
      - Renamed 4 user-facing skills to short imperative verbs:
          ingest-source  -> ingest
          lint-wiki      -> lint
          redact-history -> redact
          revert-state   -> undo
        Background-only skills (auto-file-chat, decision-logger,
        measure-retrieval, proactive-reauth, rebuild-index) keep their
        descriptive names - user never invokes those directly.
      - Reverted the 👑 emoji prefix from all skill names. Per the
        code.claude.com/docs/en/skills schema, skill `name:` fields are
        restricted to lowercase letters, digits, and hyphens. Emoji names
        were silently rejected, which is why they didn't appear in /
        autocomplete AND why auto-trigger wasn't firing.

    Changes from v0.1.20:
      - Two-layer filesystem:
          ~/Paperwik/           system root (Claude Code cwd)
              CLAUDE.md, index.md, log.md, eval.json, knowledge.db
              .claude/
              Vault/            Obsidian's vault (user-facing)
                  Welcome.md
                  .obsidian/
                  Inbox/        drop zone (was _Inbox)
                  Projects/     all topical project folders nest here
        User opens Obsidian and sees only 3 things: Welcome, Inbox,
        Projects. Zero system clutter.
      - DROPPED: Windows Terminal install step. No longer needed because
        Claude Desktop's Code tab IS Claude Code with a GUI (per
        code.claude.com/docs/en/desktop). Plugins, hooks, skills all work
        there natively. From 8 steps to 7.
      - DROPPED: Paperwik.lnk Desktop + Start menu shortcuts. The Claude
        Desktop icon is the entry point.
      - DROPPED: WT Paperwik profile + Catppuccin color scheme.
      - DROPPED: PNG -> ICO conversion (no shortcut to put icon on).
      - DROPPED: _Archive/ folder and the ARCHIVE_AFTER_DAYS /
        auto_archive_inactive() router logic. YAGNI for dad's scale; can
        add back in a later version if users actually hit the churn.
      - RENAMED: _Inbox/ -> Inbox/ (no reason for the underscore now that
        Projects/ is the main bucket).
      - Scaffolder always refreshes Vault/.obsidian/ from the template on
        each run, so template fixes (app.json changes etc.) reach existing
        installs without forcing a full re-scaffold. User content is
        preserved.
      - Obsidian vault registration now points at ~/Paperwik/Vault, not
        ~/Paperwik. Obsidian opens the user-facing layer only.
      - Final message rewritten: "Open Claude, click Code, New session,
        pick C:\\Users\\<you>\\Paperwik". No more Paperwik icon, no more
        cd/claude terminal instructions.

    Changes from v0.1.18:
      - templates/vault/.claude/settings.json: open up WebFetch from
        domain-restricted (github.com, huggingface.co, anthropic.com) to
        wildcard. Paperwik's whole point is "drop a URL, get it ingested";
        a narrow allow list contradicts that.
      - Same file: replaced Write(Paperwik/**) and Edit(Paperwik/**) with
        Write(**) / Edit(**). The original Write(Knowledge/**) pattern
        was scoped to the vault root; the v0.1.16 sed rename mangled it
        into Write(Paperwik/**), which is a dead pattern when cwd IS
        ~/Paperwik. Wildcard write is fine because the deny list still
        blocks system paths, .obsidian, .git, .claude/settings.json,
        knowledge.db, and (newly) CLAUDE.md.
      - Added WebSearch to allow list.

    Changes from v0.1.17:
      - Fix `enabledPlugins` shape in settings.json. Claude Code 2.1.118+
        rejects the array-of-objects form we'd been writing since v0.1.9
        with "Expected record, but received array" and SKIPS THE ENTIRE
        SETTINGS FILE on every launch (so paperwik never loads, the
        scaffolder hook is unregistered, etc). Correct shape:
            "enabledPlugins": { "<plugin>@<marketplace>": true }
        For us: "paperwik@paperwik": true. Legacy array entries (from
        prior Paperwik installs that wrote the wrong shape) are
        discarded on re-run since they were invalid the whole time.

    Changes from v0.1.16:
      - Step 7 (Windows Terminal) now degrades gracefully instead of
        exiting on failure. v0.1.16 tried to fall back to a Microsoft Store
        URI when winget wasn't available, but that URI fails on Windows
        Sandbox (no Store) and stripped enterprise images, leaving the
        installer dead at step 7. Now: if WT can't be auto-installed,
        we skip it and continue with a $useWindowsTerminal=$false flag.
      - Step 8 branches the shortcut creation on $useWindowsTerminal:
          * WT path: shortcut TargetPath = wt.exe -p Paperwik (themed
            window with the Paperwik color scheme + profile)
          * No-WT path: shortcut TargetPath = powershell.exe with the
            same auto-cd-and-run-claude logic baked into Arguments
        Same Paperwik icon, same auto-launch UX, just stock console
        colors instead of the themed window. The user gets a working
        clickable Paperwik shortcut either way.
      - WT settings.json merge block also wrapped in if($useWindowsTerminal)
        so we don't try to create a profile in a settings file that
        doesn't exist.

    Changes from v0.1.15:
      - Renamed the vault folder from ~/Knowledge to ~/Paperwik so the
        product name and the folder name match. (knowledge.db filename
        unchanged - it's a generic type, not branding.) ~25 files touched.
      - Removed Starter Project from the template tree (placeholder cruft).
      - Added userIgnoreFilters to .obsidian/app.json so Obsidian hides
        CLAUDE.md, index.md, log.md, knowledge.db, etc. - end user only
        sees their actual content pages.
      - NEW Step 7: install Windows Terminal. Already preinstalled on
        Win 11 22H2+; for older Windows we install via winget with a Store
        link as fallback. WT is the polished launcher window we use to
        make the terminal experience feel like an app.
      - Step 8 (Paperwik) extended with three new sub-actions:
          * Convert plugin's bundled assets/paperwik-icon.png into
            paperwik-icon.ico via System.Drawing (one-time per machine,
            cached at %LOCALAPPDATA%\Paperwik\paperwik-icon.ico)
          * Add a "Paperwik" profile + Catppuccin-style color scheme to
            Windows Terminal's settings.json. Profile auto-runs claude
            at ~/Paperwik on launch, soft dark theme, 13pt Cascadia Code,
            clean padding, hidden scrollbar.
          * Create Paperwik shortcuts in BOTH the Start menu and on the
            Desktop. Each launches `wt.exe -p Paperwik` so one click
            opens the themed window with claude already running. Custom
            icon if PNG-to-ICO conversion succeeded; falls back to
            Claude Desktop's icon otherwise.
          * Register ~/Paperwik in %APPDATA%\obsidian\obsidian.json with
            open=true so Obsidian opens directly into the vault on first
            launch (no "create vault" / "open folder as vault" dialog).
      - Renumbered to 8 total steps. Final-message rewritten - now just:
        "Click the Paperwik icon on your desktop". No more cd-and-claude
        instructions. Non-technical users never see PowerShell after install.

    Changes from v0.1.11:
      - Apply the same native-command-stderr fix to the `uv run scaffolder`
        call that v0.1.11 applied to git. uv prints Python-download progress
        ("Downloading cpython-3.14... (21.3MiB)") to stderr, which with
        ErrorActionPreference=Stop PS treated as a terminating error and
        killed the child process mid-download - scaffolder never completed,
        no Paperwik folder. Fix: locally relax ErrorActionPreference to
        Continue around the uv call, check $LASTEXITCODE, and additionally
        use filesystem truth (~/Paperwik/.claude/.scaffolded sentinel) as
        the authoritative success signal.
      - Show a clear manual-retry command in the output if the scaffolder
        call still hits a real failure, so the user can recover without
        reopening this script.

    Changes from v0.1.10:
      - Fix Test-Path $path -and (...) parse bug in step 7. PowerShell 5.1
        parses `Test-Path $var -and $other` as `Test-Path -and` where `-and`
        is a parameter to Test-Path, not a boolean operator. Now parenthesized
        correctly. This was what produced the "A parameter cannot be found
        that matches parameter name 'and'" error observed during v0.1.10
        sandbox test.
      - Fix git clone stderr false-alarm. Git prints normal progress to
        stderr ("Cloning into '...'", etc.). Combined with
        ErrorActionPreference="Stop" this was landing in the catch block
        even when the clone itself succeeded. Now passes --quiet to all git
        commands, temporarily relaxes ErrorActionPreference around native
        calls, and checks $LASTEXITCODE instead of relying on try/catch.
      - If a re-run's git fetch+reset fails (e.g. network blip), fall
        through to a fresh git clone automatically instead of aborting the
        step.

    Changes from v0.1.9:
      - Obsidian silent-install verification is now retry-based. electron-
        builder NSIS finalize timing is unpredictable on Sandbox and slow
        disks - sometimes the .exe shows up in 2 seconds, sometimes 20+.
        The previous fixed 5-second sleep failed for the second group.
        New Wait-ForObsidianInstall helper polls every 5s for up to 45s.
      - Test-ObsidianInstalled now also checks the Start-menu shortcut
        (%APPDATA%\Microsoft\Windows\Start Menu\Programs\Obsidian.lnk) as
        a secondary signal - NSIS creates the shortcut reliably and often
        before the .exe has finished unpacking, so this catches the cases
        where the file-based check would otherwise fail.
      - Honest timing: banner now says "Expect 8-10 minutes on typical
        home internet" (was "About 5 minutes"). Real observed times on
        fresh Sandbox: 8-12 minutes end to end with the step 7 scaffolder
        included.
      - Obsidian detection failure now prints every path it checked so
        support diagnosis doesn't require guessing.

    Changes from v0.1.8:
      - NEW Step 7: zero-manual-step plugin install. Previously the final
        message told users to type /plugin marketplace add + /plugin install
        after the bootstrap. Now:
          (a) git clone https://github.com/s0phak1ng/paperwik.git to
              ~/.claude/plugins/marketplaces/paperwik/ (Claude Code's cache
              path for registered marketplaces)
          (b) merge extraKnownMarketplaces.paperwik + enabledPlugins into
              ~/.claude/settings.json (preserves any other user settings via
              PSCustomObject round-trip)
          (c) run scripts/scaffold-vault.py directly via uv to create
              ~/Paperwik/ with full vault template + knowledge.db schema
        User's first `claude` launch sees the plugin pre-enabled and the
        vault already present — no /plugin commands, no waiting for the
        SessionStart hook to build the vault.
      - Renumbered to 7 total steps. Final-message rewrite drops the
        /plugin lines entirely; new flow is just: Obsidian point-at-vault,
        PowerShell claude, OAuth, try an ingest.

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
Write-Host "  Setting up in 7 steps. Expect 8-10 minutes on typical home internet." -ForegroundColor Cyan
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
Write-Host "[1/7] Setting up Git for Windows (Claude Code needs git-bash)..." -ForegroundColor Yellow

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
Write-Host "[2/7] Setting up Claude Code (the engine that powers Paperwik)..." -ForegroundColor Yellow

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
Write-Host "[3/7] Setting up Claude Desktop (general chat app; Paperwik runs separately)..." -ForegroundColor Yellow

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
Write-Host "[4/7] Setting up Obsidian (where you'll read your notes)..." -ForegroundColor Yellow

$obsidianCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Obsidian\Obsidian.exe"),  # electron-builder default (per-user)
    (Join-Path $env:LOCALAPPDATA "Obsidian\Obsidian.exe"),            # legacy path
    (Join-Path $env:ProgramFiles "Obsidian\Obsidian.exe"),            # all-users install
    "${env:ProgramFiles(x86)}\Obsidian\Obsidian.exe"                  # 32-bit, rare
)

function Test-ObsidianInstalled {
    # Primary: Obsidian.exe at one of the known install paths
    foreach ($candidate in $obsidianCandidates) {
        if (Test-Path $candidate) { return $true }
    }
    # Secondary: Start menu shortcut (electron-builder NSIS creates this reliably,
    # sometimes before the main .exe has finished unpacking on slow disks)
    $shortcutCandidates = @(
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Obsidian.lnk"),
        (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\Obsidian.lnk")
    )
    foreach ($lnk in $shortcutCandidates) {
        if (Test-Path $lnk) { return $true }
    }
    # Tertiary: uninstall-registry entry (NSIS writes one; many subkeys lack
    # DisplayName, so guard every property access)
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

function Wait-ForObsidianInstall {
    # electron-builder NSIS finalize timing is unpredictable on Sandbox/slow
    # disks — sometimes 2 seconds, sometimes 20+. Retry up to ~45 seconds.
    param([int]$TimeoutSeconds = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $attempt = 0
    while ((Get-Date) -lt $deadline) {
        $attempt++
        if (Test-ObsidianInstalled) {
            Write-Host "      Detected Obsidian after $attempt check(s)." -ForegroundColor DarkGray
            return $true
        }
        Start-Sleep -Seconds 5
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
            $exitCode = $proc.ExitCode
            Write-Host "      Installer exited with code $exitCode. Waiting for filesystem to settle..." -ForegroundColor DarkGray
            # electron-builder NSIS finalize is racy; retry detection for up to 45s
            if (Wait-ForObsidianInstall -TimeoutSeconds 45) {
                Write-Host "      Obsidian ready." -ForegroundColor Green
            } else {
                # Print every path we checked so support diagnostics are easy
                $checkedPaths = $obsidianCandidates + @(
                    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Obsidian.lnk")
                )
                Write-Host "      None of these paths exist yet:" -ForegroundColor Red
                foreach ($p in $checkedPaths) { Write-Host "        $p" -ForegroundColor Red }
                throw "Installer ran (exit $exitCode) but no Obsidian.exe or Start-menu shortcut materialized within 45s"
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
Write-Host "[5/7] Setting up Visual C++ Redistributable (needed by the search engine)..." -ForegroundColor Yellow

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
Write-Host "[6/7] Setting up uv (a helper that runs Paperwik's search tools)..." -ForegroundColor Yellow

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
# Step 7 — Paperwik plugin + vault + Obsidian vault registration
# -----------------------------------------------------------------------------
# Three related actions, all so the user's first launch is fully functional:
#
#   (a) git clone the plugin repo to ~/.claude/plugins/marketplaces/paperwik/
#   (b) merge extraKnownMarketplaces + enabledPlugins into ~/.claude/settings.json
#       so Claude Code auto-loads the plugin without /plugin commands
#   (c) run scripts/scaffold-vault.py to create ~/Paperwik/ (system root) +
#       ~/Paperwik/Vault/ (Obsidian's view), with knowledge.db schema initialized
#   (d) register ~/Paperwik/Vault in %APPDATA%\obsidian\obsidian.json so
#       Obsidian opens directly into the vault on first launch
#
# We deliberately do NOT install Windows Terminal or create a desktop launcher
# anymore — the user opens Claude Desktop's "Code" tab and points it at
# ~/Paperwik. Plugins, hooks, skills, and CLAUDE.md all load automatically
# because Claude Desktop's Code tab IS Claude Code with a GUI (per Anthropic
# docs at code.claude.com/docs/en/desktop).
Write-Host ""
Write-Host "[7/7] Setting up Paperwik (plugin, vault, Obsidian)..." -ForegroundColor Yellow

$claudeDir = Join-Path $env:USERPROFILE ".claude"
$settingsPath = Join-Path $claudeDir "settings.json"
$marketplacesDir = Join-Path $claudeDir "plugins\marketplaces"
$paperwikDir = Join-Path $marketplacesDir "paperwik"

# Ensure the folder tree exists
foreach ($d in @($claudeDir, (Join-Path $claudeDir "plugins"), $marketplacesDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# --- (a) Clone (or update) the plugin repo -----------------------------------
if (-not (Test-CommandExists "git")) {
    Write-Host "      git isn't on PATH (step 1 should have installed it) - skipping clone." -ForegroundColor Yellow
    Write-Host "      You'll need to run /plugin marketplace add s0phak1ng/paperwik manually." -ForegroundColor Yellow
} else {
    # Git uses stderr for its normal progress output ("Cloning into '...'",
    # "Enumerating objects...", etc.). Combined with ErrorActionPreference="Stop"
    # that PS sees as a terminating error and jumps to catch even when the
    # clone succeeded. Two defenses:
    #   (a) Pass --quiet so git suppresses the progress chatter.
    #   (b) Temporarily relax ErrorActionPreference + check $LASTEXITCODE
    #       instead of trusting try/catch for native commands.
    $prevErrActPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if (Test-Path (Join-Path $paperwikDir ".git")) {
            # Previously installed: pull the latest so re-runs get fresh code
            & git -C $paperwikDir fetch --quiet --depth 1 origin main 2>&1 | Out-Null
            $fetchExit = $LASTEXITCODE
            & git -C $paperwikDir reset --quiet --hard origin/main 2>&1 | Out-Null
            $resetExit = $LASTEXITCODE
            if ($fetchExit -eq 0 -and $resetExit -eq 0) {
                Write-Host "      Plugin files updated to latest main." -ForegroundColor DarkGray
            } else {
                Write-Host "      Plugin update hit a snag (fetch=$fetchExit, reset=$resetExit). Falling back to fresh clone..." -ForegroundColor Yellow
                Remove-Item -Recurse -Force $paperwikDir -ErrorAction SilentlyContinue
                & git clone --quiet --depth 1 "https://github.com/s0phak1ng/paperwik.git" $paperwikDir 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "git clone exit code $LASTEXITCODE" }
                Write-Host "      Plugin files cloned." -ForegroundColor DarkGray
            }
        } else {
            if (Test-Path $paperwikDir) {
                # Folder exists but isn't a git repo — wipe and re-clone for a clean slate
                Remove-Item -Recurse -Force $paperwikDir -ErrorAction SilentlyContinue
            }
            & git clone --quiet --depth 1 "https://github.com/s0phak1ng/paperwik.git" $paperwikDir 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "git clone exit code $LASTEXITCODE" }
            Write-Host "      Plugin files cloned." -ForegroundColor DarkGray
        }
    } catch {
        Write-Host "      git clone failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "      You can fall back to manual install: /plugin marketplace add s0phak1ng/paperwik" -ForegroundColor Yellow
    } finally {
        $ErrorActionPreference = $prevErrActPref
    }
}

# --- (b) Register + enable in ~/.claude/settings.json ------------------------
# Claude Code merges our entries with anything already there. We use
# PSCustomObject round-trip to preserve any other fields the user might have
# set (theme, model, etc.) without forcing us to know their schema.
$settings = [PSCustomObject]@{}
if (Test-Path $settingsPath) {
    try {
        $raw = Get-Content $settingsPath -Raw -ErrorAction SilentlyContinue
        if ($raw -and $raw.Trim()) {
            $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
            if ($parsed -is [PSCustomObject]) { $settings = $parsed }
        }
    } catch {
        Write-Host "      Warning: existing settings.json wasn't valid JSON. Replacing." -ForegroundColor Yellow
    }
}

# extraKnownMarketplaces.paperwik
$marketplacesProp = $settings.PSObject.Properties['extraKnownMarketplaces']
if ($null -eq $marketplacesProp -or $null -eq $settings.extraKnownMarketplaces) {
    $settings | Add-Member -NotePropertyName 'extraKnownMarketplaces' -NotePropertyValue ([PSCustomObject]@{}) -Force
}
$paperwikMarketplace = [PSCustomObject]@{
    source = [PSCustomObject]@{
        source = 'git'
        url    = 'https://github.com/s0phak1ng/paperwik.git'
    }
}
$settings.extraKnownMarketplaces | Add-Member -NotePropertyName 'paperwik' -NotePropertyValue $paperwikMarketplace -Force

# enabledPlugins is a record/object keyed by "<plugin>@<marketplace>" with
# boolean values:
#     "enabledPlugins": { "pw@paperwik": true }
# Earlier versions (pre-v0.2.0) used "paperwik@paperwik" since the plugin
# name was "paperwik". In v0.2.2 we renamed the plugin's internal id to
# "pw" for a shorter slash-command prefix (/pw:ingest instead of
# /paperwik:ingest). If the stale "paperwik@paperwik" key is present, drop
# it - the plugin.json now reports name=pw so Claude Code won't match the
# old key anyway, and leaving it causes "plugin paperwik not found" noise.
#
# Pre-v0.1.18 versions wrote enabledPlugins as an array of {name, marketplace}
# objects, which Claude Code 2.1.118+ rejects with "Expected record, but
# received array". If we find that legacy shape, we discard it - invalid
# schema, no user state to preserve.
$enabledMap = @{}
if ($settings.PSObject.Properties['enabledPlugins'] -and $settings.enabledPlugins) {
    $existing = $settings.enabledPlugins
    if ($existing -is [PSCustomObject]) {
        # Carry forward any other plugins the user had enabled
        foreach ($p in $existing.PSObject.Properties) {
            # Skip legacy paperwik@paperwik (superseded by pw@paperwik)
            if ($p.Name -eq 'paperwik@paperwik') { continue }
            $enabledMap[$p.Name] = $p.Value
        }
    }
    # else: array (legacy/invalid) or scalar - discard
}
$enabledMap['pw@paperwik'] = $true
$settings | Add-Member -NotePropertyName 'enabledPlugins' -NotePropertyValue $enabledMap -Force

# Write without BOM so the Claude Code JSON parser doesn't choke
try {
    $json = $settings | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($settingsPath, $json, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "      Registered paperwik in ~/.claude/settings.json." -ForegroundColor DarkGray
} catch {
    Write-Host "      Failed to write settings.json: $($_.Exception.Message)" -ForegroundColor Red
}

# --- (c) Run the scaffolder to build ~/Paperwik now -------------------------
# Same native-command-stderr trap as git: uv prints download progress
# ("Downloading cpython-3.14... (21.3MiB)") to stderr, which with
# ErrorActionPreference="Stop" looks like a terminating error to PS and kills
# the child process mid-download. Relax ErrorActionPreference locally and use
# $LASTEXITCODE + filesystem verification as the success signal.
$scaffolder = Join-Path $paperwikDir "scripts\scaffold-vault.py"
$vaultRoot = Join-Path $env:USERPROFILE "Paperwik"
$sentinel = Join-Path $vaultRoot ".claude\.scaffolded"
if (Test-Path $scaffolder) {
    $env:CLAUDE_PLUGIN_ROOT = $paperwikDir
    # uv was installed in step 6; make sure its bin dir is on PATH for this call
    $uvBinDir = Join-Path $env:USERPROFILE ".local\bin"
    if ((Test-Path $uvBinDir) -and (($env:PATH -split ';') -notcontains $uvBinDir)) {
        $env:PATH = "$env:PATH;$uvBinDir"
    }
    Write-Host "      Building your Paperwik vault (first run takes ~30-60 seconds while uv fetches Python)..." -ForegroundColor Yellow
    $prevErrActPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & uv run $scaffolder 2>&1 | Out-Null
        $uvExit = $LASTEXITCODE
    } catch {
        # Should not hit this with ErrorActionPreference=Continue, but just in case
        $uvExit = -1
        Write-Host "      uv run threw: $($_.Exception.Message)" -ForegroundColor Yellow
    } finally {
        $ErrorActionPreference = $prevErrActPref
    }
    # Filesystem-based truth: if the sentinel exists, the scaffolder completed
    # regardless of what uv's exit code said.
    if (Test-Path $sentinel) {
        Write-Host "      Paperwik vault ready at $vaultRoot." -ForegroundColor Green
    } elseif ($uvExit -eq 0) {
        Write-Host "      uv reported success but sentinel is missing. Run again or launch Claude Code to retry." -ForegroundColor Yellow
    } else {
        Write-Host "      Scaffolder exited $uvExit. Launching Claude Code once will retry via the SessionStart hook." -ForegroundColor Yellow
        Write-Host "      Or you can re-run the scaffolder manually:" -ForegroundColor DarkGray
        Write-Host "        `$env:CLAUDE_PLUGIN_ROOT = '$paperwikDir'" -ForegroundColor DarkGray
        Write-Host "        uv run '$scaffolder'" -ForegroundColor DarkGray
    }
} else {
    Write-Host "      Scaffolder script not found (plugin clone may have failed). Launching Claude Code will try again." -ForegroundColor Yellow
}

# --- (c2) Migrate vault .claude/settings.json from template on every run ----
# The scaffolder is sentinel-gated; it only writes the vault's settings.json
# once (first run). When we ship a new permissions/allow/deny scheme in a
# plugin update, the template improves but existing vaults keep their old
# settings.json. Overwrite unconditionally so v0.2.6+ users get the broader
# Bash(*) allow + bypassPermissions mode without manual intervention.
#
# Back up first so a user with hand-edited settings can recover.
$templateSettings = Join-Path $paperwikDir "templates\paperwik\.claude\settings.json"
$vaultSettings    = Join-Path $vaultRoot   ".claude\settings.json"
if ((Test-Path $templateSettings) -and (Test-Path $vaultRoot)) {
    try {
        $vaultClaudeDir = Split-Path -Parent $vaultSettings
        if (-not (Test-Path $vaultClaudeDir)) {
            New-Item -ItemType Directory -Path $vaultClaudeDir -Force | Out-Null
        }
        if (Test-Path $vaultSettings) {
            $backup = "$vaultSettings.bak-$(Get-Date -Format 'yyyyMMddHHmmss')"
            Copy-Item $vaultSettings $backup -Force
        }
        Copy-Item $templateSettings $vaultSettings -Force
        Write-Host "      Refreshed vault permissions from template (bypassPermissions + broad Bash allow + destructive-op deny)." -ForegroundColor Green
    } catch {
        Write-Host "      Couldn't refresh vault settings.json: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# --- (c3) Initialize git repo + first snapshot in ~/Paperwik ----------------
# The PostToolUse Auto-Commit hook (registered in v0.2.7) creates versioned
# snapshots of every agent edit inside ~/Paperwik/ so the user has undo via
# git revert. That hook is time-budgeted (15s) so it must NEVER do an
# initial bulk add on a fresh vault — staging a freshly-scaffolded vault
# with knowledge.db + other large files takes longer than any reasonable
# hook timeout and would leave a stale .git/index.lock wedging future
# commits. We do the init and initial snapshot here, where we can take as
# long as needed. Idempotent: skipped if .git already exists.
$vaultGit = Join-Path $vaultRoot '.git'
if ((Test-Path $vaultRoot) -and (-not (Test-Path $vaultGit))) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Host "      Initializing git history in $vaultRoot..." -ForegroundColor DarkGray
        $prevErr = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        Push-Location $vaultRoot
        try {
            & git init --quiet 2>&1 | Out-Null
            & git config user.name 'Paperwik Agent' 2>&1 | Out-Null
            & git config user.email 'agent@paperwik.local' 2>&1 | Out-Null
            & git add -A 2>&1 | Out-Null
            & git commit --quiet -m 'paperwik: initial snapshot' 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "      Git history initialized (undo via git log/revert inside Paperwik\\)." -ForegroundColor Green
            } else {
                Write-Host "      Git init ran but initial commit exit=$LASTEXITCODE (non-fatal; hook will try on first agent edit)." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "      Git init hit an error: $($_.Exception.Message)" -ForegroundColor Yellow
        } finally {
            Pop-Location
            $ErrorActionPreference = $prevErr
        }
    } else {
        Write-Host "      git not on PATH — skipping vault git init. Auto-Commit hook won't snapshot." -ForegroundColor Yellow
    }
}

# --- (d) Register vault in Obsidian's vault list -----------------------------
# Note: we DROPPED the icon ICO conversion + WT profile + Start menu/Desktop
# shortcut creation that v0.1.x did. The user opens Claude Desktop's Code tab
# directly — no separate Paperwik launcher window needed.

# --- Register vault in Obsidian's vault list ---------------------------------
# Obsidian stores its known vaults at %APPDATA%\obsidian\obsidian.json. Each
# entry is keyed by an arbitrary 16-char hex ID. Setting `open: true` makes
# Obsidian launch directly into that vault. We use a stable ID so re-runs
# update the same entry instead of stacking duplicates.
#
# IMPORTANT (v0.2.0): the vault path is ~/Paperwik/Vault, NOT ~/Paperwik.
# The Vault/ subfolder is what Obsidian opens — it contains only user-facing
# content (Welcome.md, Inbox/, Projects/). System files (CLAUDE.md, log.md,
# index.md, eval.json, knowledge.db, .claude/) live in the parent directory
# and are intentionally hidden from Obsidian's file explorer.
$obsidianJsonPath = Join-Path $env:APPDATA "obsidian\obsidian.json"
$paperwikVaultId = "paperwikvault01"  # stable, paperwik-specific
$paperwikVaultPath = Join-Path $env:USERPROFILE "Paperwik\Vault"

$obsidianJson = [PSCustomObject]@{}
if (Test-Path $obsidianJsonPath) {
    try {
        $raw = Get-Content $obsidianJsonPath -Raw -ErrorAction SilentlyContinue
        if ($raw -and $raw.Trim()) {
            $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
            if ($parsed -is [PSCustomObject]) { $obsidianJson = $parsed }
        }
    } catch {
        Write-Host "      Existing obsidian.json wasn't valid JSON; replacing." -ForegroundColor Yellow
    }
} else {
    $obsidianDir = Split-Path -Parent $obsidianJsonPath
    if (-not (Test-Path $obsidianDir)) {
        New-Item -ItemType Directory -Path $obsidianDir -Force | Out-Null
    }
}

# Ensure vaults object exists
if (-not $obsidianJson.PSObject.Properties['vaults']) {
    $obsidianJson | Add-Member -NotePropertyName 'vaults' -NotePropertyValue ([PSCustomObject]@{}) -Force
}

# Mark all existing vaults as not-open (so Obsidian doesn't try to open
# multiple at once), then add/update Paperwik with open=true.
foreach ($prop in @($obsidianJson.vaults.PSObject.Properties)) {
    $v = $prop.Value
    if ($v -and $v.PSObject.Properties['open']) {
        $v.open = $false
    }
}

$paperwikVaultEntry = [PSCustomObject]@{
    path = $paperwikVaultPath
    ts   = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    open = $true
}
$obsidianJson.vaults | Add-Member -NotePropertyName $paperwikVaultId -NotePropertyValue $paperwikVaultEntry -Force

try {
    $json = $obsidianJson | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($obsidianJsonPath, $json, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "      Registered Paperwik vault in Obsidian (will open automatically)." -ForegroundColor DarkGray
} catch {
    Write-Host "      Couldn't write obsidian.json: $($_.Exception.Message)" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# Finish — tell user what comes next
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host "  Nice! Paperwik is ready to use." -ForegroundColor Green
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Everything is installed and configured. To start:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Close this window." -ForegroundColor White
Write-Host ""
Write-Host "  2. Open Claude (Start menu -> Claude)." -ForegroundColor White
Write-Host "     If Claude was already open during install, FULLY QUIT IT FIRST" -ForegroundColor DarkYellow
Write-Host "     (right-click the Claude icon in the system tray -> Quit)," -ForegroundColor DarkYellow
Write-Host "     then reopen. Claude only sees new plugins on a fresh start." -ForegroundColor DarkYellow
Write-Host ""
Write-Host "  3. Click the Code tab in the left sidebar." -ForegroundColor White
Write-Host ""
Write-Host "  4. Click 'New session' and pick this folder when asked:" -ForegroundColor White
Write-Host "        C:\Users\$env:USERNAME\Paperwik" -ForegroundColor Yellow
Write-Host ""
Write-Host "  5. Turn on Paperwik (one time, takes 5 seconds):" -ForegroundColor White
Write-Host "       - Click the + button to the left of the chat box" -ForegroundColor White
Write-Host "       - Click 'Plugins'" -ForegroundColor White
Write-Host "       - Look for 'Personal' section and click 'paperwik'" -ForegroundColor White
Write-Host "       - Click the + (or Enable) on the paperwik detail page" -ForegroundColor White
Write-Host "     After that, Paperwik's skills appear when you type / in the chat." -ForegroundColor DarkGray
Write-Host ""
Write-Host "     If you don't see the 'Personal' section at all, Claude hasn't" -ForegroundColor DarkYellow
Write-Host "     picked up the new plugin yet. Fully quit Claude (tray icon ->" -ForegroundColor DarkYellow
Write-Host "     Quit) and reopen it, then try again. One restart is enough." -ForegroundColor DarkYellow
Write-Host ""
Write-Host "  6. Type what you want, like:" -ForegroundColor White
Write-Host "        ingest https://example.com/an-article-i-want-saved" -ForegroundColor Yellow
Write-Host "        what do I know about <a topic>?" -ForegroundColor Yellow
Write-Host "        summarize the last few sources I added" -ForegroundColor Yellow
Write-Host ""
Write-Host "  7. To browse your wiki visually, open Obsidian from your Start" -ForegroundColor White
Write-Host "     menu. Your vault opens automatically."
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
