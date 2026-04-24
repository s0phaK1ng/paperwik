# Troubleshooting

This is a reference sheet. Skim once, keep handy. Most of what follows you'll never need.

---

## "Please sign in again" (roughly once a day)

**What you'll see**: mid-conversation your helper stalls, or a browser window opens asking you to sign in to Claude, or the terminal shows `API Error: 401 ... OAuth token has expired`.

**Why**: Claude's sign-ins last about 24 hours. When the token expires Claude needs a fresh one.

**Fix**:
1. If the browser opened, click **Approve** on claude.ai and return to your helper. It resumes automatically.
2. If no browser opened, type `/login` in the Code tab. That triggers a fresh sign-in.
3. If neither works, fully quit Claude Desktop (tray icon -> Quit) and reopen. The sign-in flow starts automatically.

Takes about 10 seconds either way.

---

## "Please accept our updated Terms" (every few months)

**Why**: Anthropic updates their Terms of Service occasionally. Claude waits for you to acknowledge.

**Fix**: open claude.ai, read or skim the update, click **Accept**, return to the Code tab and continue. Your helper picks up where you left off.

---

## "You've hit your message limit" (during heavy ingest sessions)

**What you'll see**: `API Error: 429 Rate limit reached` or `Stopping -- you've hit your 5-hour message limit. Try again at <time>.`

**Why**: Claude Pro has a rolling 5-hour message window. A burst of ingests (each one makes multiple Claude calls) can exhaust it.

**Fix**:
1. Note the reset time in the error. No retries will work sooner.
2. When you come back, pick up where you left off. Paperwik retries cleanly -- no ingest finishes half-broken.
3. To avoid next time: spread ingests out, or upgrade to Claude Max for a bigger quota.

---

## "Paperwik isn't showing up in the + -> Plugins menu"

**Why**: Claude Desktop caches its plugin list at process startup. If Paperwik was installed or updated while Desktop was running, Desktop won't see the new state until the next launch.

**Fix**:
1. Right-click the Claude icon in the Windows system tray (bottom-right near the clock), click **Quit**. That's a real shutdown -- closing the window isn't enough.
2. Reopen Claude Desktop from the Start menu.
3. Click **+** -> **Plugins**. Paperwik should now appear under **Personal**.

One restart is almost always enough.

---

## "Paperwik shows an old version in Plugins"

**Why**: Claude Desktop reads plugin files at startup and does not auto-reload when the files on disk change. After an update, Desktop keeps running the old version in memory until you explicitly tell it to reload.

**Fix**:
1. **+** button -> **Plugins** -> click **paperwik** under Personal.
2. Click **Update** on the plugin detail page. Desktop reloads from disk.
3. Click **Enable** on the same page even if it already shows enabled -- the version bump resets the enable state.

---

## "The agent is asking me to click Allow over and over"

**What you'll see**: each file write or bash command pops an "Allow once / Allow always" dialog.

**Why in newer versions**: shouldn't happen. Paperwik v0.2.6+ sets `defaultMode: bypassPermissions` and allows `Bash(*)` in the vault's `.claude/settings.json`, so normal operations don't prompt. Destructive operations are still blocked by the deny list.

**Fix if you're seeing it anyway**:
1. Fully quit Claude Desktop (tray -> Quit) and reopen. Desktop's session picks up the permission settings fresh.
2. Click **+** -> **Plugins** -> paperwik -> Update -> Enable. Permissions are reset on every version bump.
3. If prompts still appear, check that `C:\Users\<you>\Paperwik\.claude\settings.json` exists and contains `"defaultMode": "bypassPermissions"`. If not, re-run the installer: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`.

---

## "Ingest runs but then says 'DLL load failed' or 'onnxruntime'"

**Why**: The retrieval stack (fastembed, flashrank, spaCy) depends on the Microsoft Visual C++ 2015-2022 Redistributable. If your machine doesn't have it, the native extensions can't load.

**Fix**: The Paperwik installer step 5 installs this. If it was skipped, install manually:

```powershell
$vc = "$env:TEMP\vc_redist.x64.exe"
Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile $vc -UseBasicParsing
Start-Process -FilePath $vc -ArgumentList '/install','/quiet','/norestart' -Wait
Remove-Item $vc
```

Restart Claude Desktop and retry the ingest.

---

## "I can't find a file I just ingested"

**Where things go after ingest**:
- The original source file moves from `Vault/Inbox/` to `Vault/Projects/<Project>/_sources/<filename>` (same filename, just nested under the project folder).
- A new summary page appears at `Vault/Projects/<Project>/<slug-of-title>.md`.
- Entity pages appear under `Vault/Projects/<Project>/Entities/<Entity Name>.md`.
- `Vault/Inbox/` is meant to stay empty or only hold pending items.

If you don't know which project Paperwik filed it under, ask: **"which project did you put that last ingest in?"** The agent reads `log.md` and tells you.

---

## "Search returns nothing" or "search returns wrong results"

**Fix**:
1. Say **rebuild the index**. This fixes about 80% of search problems. It walks your markdown files and regenerates `knowledge.db` from scratch.
2. If still broken, check that `knowledge.db` exists at `C:\Users\<you>\Paperwik\knowledge.db`. If it doesn't, say **run first-time setup** and Paperwik's scaffolder re-creates it.
3. Measure retrieval quality explicitly: say **run the eval**. If scores dropped sharply since the last run, send the diagnostic log to your installer.

---

## "The research run stopped partway and didn't produce a file"

**What you'll see**: no new file in `Vault/Inbox/` even though you asked for research minutes ago, or a partial run that errored out.

**Why it can happen**:
- Your laptop went to sleep. Paperwik sets a wake-lock at the start of a run, but if your laptop is on battery OR the wake-lock `powercfg` call failed, Windows will still suspend the session mid-run.
- Your Claude Pro 5-hour window filled up mid-run. A research run uses ~30-50 prompts; if you'd already spent most of your window on other work, the run gets throttled halfway.
- A `SubagentStop` hook failed to fire for one of the section writers. Drafts exist but the `ready_to_stitch` sentinel never wrote.

**Fix**:
1. Check `C:\Users\<you>\Documents\Paperwik-Diagnostics.log` for the last 50 lines. Look for `research_status`, `HOOK_CRASH`, or rate-limit errors.
2. Look inside `C:\Users\<you>\Paperwik\.claude\skills\state\deep-research\runs\` -- each run has its own subdirectory. The most recent one will have partial `drafts/s1.md`, `drafts/s2.md` etc. You can open these manually if you want to salvage what was written.
3. If the run just needs to continue: close and reopen Claude Desktop, then say **research [same topic] again**. Paperwik starts fresh; the partial run stays on disk for reference but doesn't merge in.
4. Plug the laptop into AC power before the next run.

---

## "Research burned my whole week's budget"

**What you'll see**: after running research, Claude Pro says you've hit your weekly usage cap and can't do anything else until the window resets.

**Why**: the default is 3 section writers to keep a single run within comfortable Pro-tier limits. But if you asked for a longer document (8-12 sections), or ran research back-to-back, you can exhaust the ~40-80 weekly Sonnet hours.

**Fix**:
1. Wait for the weekly reset (7 days from your first request of the current window). The exact time is shown in the rate-limit error.
2. For future runs, stick to the default 3-section depth unless the topic really warrants more. Say **do a short research on X** to hint at the smaller version.
3. If you have Claude Max (5x or 20x), the weekly budget is much higher -- but most end users don't need to upgrade.
4. If you think the model used Opus for any part of the run, that's ~3x the cost -- check `Documents\Paperwik-Diagnostics.log` for what actually dispatched. Research always pins Sonnet and Haiku explicitly, so this shouldn't happen; if it does, send the log to your installer.

---

## "The research output file didn't appear in Obsidian"

**Why**: the file is written to `C:\Users\<you>\Paperwik\Vault\Inbox\` with a dad-readable name like `Cognitive Health Strategies - 2026-04-24.md`. Obsidian's file tree should refresh automatically, but OneDrive Files On-Demand can cause a delay.

**Fix**:
1. In Obsidian, click the refresh icon in the file explorer pane, OR close and reopen the vault (File -> Open Vault).
2. If the file still doesn't appear, open File Explorer directly to `C:\Users\<you>\Paperwik\Vault\Inbox\` and confirm the file exists there.
3. If the file doesn't exist anywhere, check the diagnostic log -- the run may have failed at the Sanitizer's format-contract validation (YAML frontmatter + H2/H3 + Sources table). That's an intentional block to prevent malformed docs polluting your wiki; re-run the research to try again.

---

## "Where is my chat history?"

Every response you get is mirrored to a per-session JSONL file at `C:\Users\<you>\Paperwik\.claude\chat-history\<session-id>.jsonl`. That's inside the system-root `.claude/` folder, not inside `Vault/`, so Obsidian doesn't surface it -- intentional. You can still ask "what did we discuss about X?" and Paperwik reads its own archive.

Chat history is NOT tracked by git (the `.gitignore` skips `.claude/chat-history/`) -- the files can grow large and rewrite every turn, so snapshotting them would bloat the repo without recovery value.

---

## The diagnostic log (your universal helpline)

Whenever something non-routine happens, Paperwik writes a line to:

```
C:\Users\<you>\Documents\Paperwik-Diagnostics.log
```

If anything feels off:

1. Open that file in Notepad.
2. Copy the last ~50-100 lines.
3. Send it to whoever installed Paperwik for you, plus a sentence about what you saw.

You don't need to understand the log. Don't delete it. Keep it.

---

## "Something's wrong and I don't know what"

In order, first two fix most problems:

1. **Close and reopen Claude Desktop.** Right-click the tray icon -> Quit, then reopen from the Start menu. Half of everything weird is fixed here.
2. **Restart Obsidian.** If the UI looked wrong, this usually does it.
3. **Run `claude /doctor`** -- Claude's built-in check-up command.
4. **Look at the diagnostic log** for `HOOK_CRASH` in the last few minutes.
5. **Say "rebuild the index"** if search feels wrong.
6. **Re-run the installer one-liner**: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`. This refreshes permissions, plugin files, and the vault settings without touching your markdown content.

If none of that works, send the diagnostic log + a screenshot to whoever installed Paperwik for you. Most mysteries resolve with context and patience.
