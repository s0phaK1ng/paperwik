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
