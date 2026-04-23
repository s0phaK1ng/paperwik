# Paperwik — Day-One Training Agenda

**Audience:** The person installing Paperwik + the person it's being
installed for. Whoever runs this script is the "installer" below.
**Duration:** 60 minutes, four 15-minute phases.
**Setup:** In-person or via remote session (Quick Assist / TeamViewer).
**Prerequisite:** User has an active Claude Pro or Claude Max subscription
on their own claude.ai account. Verify this before the session begins.

---

## Phase 1 — Install (minutes 0–15)

### Goal
By end of phase: Claude Code is installed, Obsidian is installed, the
Paperwik plugin is installed, and the vault has been scaffolded.

### Script

1. Set the tone for the user: *"We're going to set up three small
   pieces. You'll watch today; after this, you won't think about them
   again. It's actually shorter than most app installs."*
2. Open PowerShell (not Terminal, not Command Prompt — PowerShell
   specifically). Press Win key, type "powershell", hit Enter.
3. Paste and run the one-line bootstrap:
   `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex`
4. The bootstrap installs Claude Code, Obsidian, and the `uv` Python
   runner. Takes ~3 minutes total.
5. Explain: *"Now we're giving Claude the Paperwik plugin — think of it
   as the instruction manual that teaches Claude how to be your
   archivist."*
6. Type `claude` and hit Enter. Claude Code launches. The first thing it
   does is open the browser for OAuth sign-in. The user clicks **Approve**.
7. Back at the Claude Code prompt, the user types:
   `/plugin marketplace add s0phak1ng/paperwik`
   Press Enter. Wait a second.
8. Then: `/plugin install paperwik`. Press Enter.
9. **Restart Claude Code.** Type `/exit` and then `claude` again.
10. **First run:** the SessionStart hook runs the Python scaffolder.
    The user sees a "first-time setup in progress" message. This takes
    ~30–60 seconds. DO NOT close the window.
11. When the prompt returns, you're ready.

### What the user sees at end of Phase 1

- Obsidian in their taskbar.
- `C:\Users\<them>\Paperwik\` exists with `_Inbox/`, `Starter Project/`,
  `_Archive/`, and several `.md` files visible in File Explorer.
- Claude Code is running in a terminal window, showing a ready prompt.

### What to explain

- **Two windows you'll use:** *"Obsidian is where you'll read and browse
  your notes. Claude Code (inside Claude Desktop) is where you talk to
  the helper. They look at the same files, just in different ways."*
- **The simple division of labor:** *"Your job is to pick what to
  feed it — articles, reports, anything you want remembered. Your
  helper does the writing. Don't try to edit the wiki pages yourself;
  if you do, your helper will probably rewrite them next time it
  visits those topics. Let it do that part — it's surprisingly good at
  it."*

---

## Phase 2 — First ingest (minutes 15–30)

### Goal
User sees a real source become a set of wiki pages, in real time, with the
Obsidian graph view filling in as it happens.

### Script

1. Invite the user: *"Pick something you actually care about — a Gemini
   Deep Research report, a paper, a long article. A real one. Test
   files are no fun and your helper learns better from real sources."*
2. Help them save it as `.md` if it's not already. Deep Research's "Share"
   menu has an export option.
3. Drag the file into `C:\Users\<them>\Paperwik\_Inbox\`.
4. In Obsidian: point out the left sidebar showing the folder tree.
   Open the Graph View (Ctrl+G or click the graph icon).
5. Back in the terminal: the user types `ingest the new source` and Enter.
6. **Watch together:**
   - First ingest triggers a one-time ~3–5 min model download. User sees
     "Loading embedding model..." etc.
   - Agent reports what it's doing: reading the source, routing to a
     project folder, writing a summary page, creating entity pages.
   - **In Obsidian's graph view:** nodes appear and connect as the pages
     get written. This is the "aha" moment. Let the user watch this for
     a minute without narrating.
7. After ingest completes, the agent says something like: "Filed under
   'Cognitive Health' (new project). 1 summary page + 7 entity pages.
   Index updated."
8. **Open Obsidian.** Navigate to the new project folder. Click through
   the summary page, an entity page, a concept page.

### What to explain

- **Why this is different from something like NotebookLM:** *"You're not
  asking a chatbot to dig through a raw PDF every time. You're reading a
  wiki that gets richer every time you add something. Six months from
  now, you'll have a living picture of each researcher, each concept,
  each paper — and new sources keep weaving into it instead of sitting
  in a pile."*
- **Folders appear on their own:** *"Notice you didn't have to tell
  your helper where to file this. It chose based on how similar the
  content is to projects it already knows about. If you don't like the
  name it picked, just rename the folder in Obsidian — your helper
  will learn from that."*

---

## Phase 3 — First query + file-back (minutes 30–45)

### Goal
User asks a real question, sees a cited answer, files the answer as a
permanent page.

### Script

1. Encourage the user: *"Ask something specific — 'What did this report
   say about X?' or 'Which researchers keep coming up?' Something you'd
   genuinely want to know. The more honest the question, the more useful
   the answer."*
2. User types a question.
3. Agent responds with citations: *"According to `Cognitive
   Health/Ketosis.md`, the report concluded X. See also `Entities/David
   Sinclair.md` for context."*
4. If the answer is useful: **user says "file that as a new page."**
5. Agent creates a new concept page in the appropriate folder, with the
   user's question as the title and the answer as the body.

### What to explain

- **Questions are worth saving too:** *"Every good answer with citations
  can become a page. Your wiki doesn't only grow when you feed it
  articles — it grows when you ask smart questions and save the answers.
  If a question was worth asking, the answer's worth keeping."*
- **Experiment freely — undo always works:** *"If your helper gets
  something wrong, just say 'undo that' and it'll take the change back.
  Every edit gets a quiet snapshot behind the scenes, so nothing is
  ever really gone."*
- **Exception: real deletion is final:** *"The one time things aren't
  recoverable is when you explicitly say 'scrub X from my wiki.' Then
  your helper walks you through a careful two-step confirmation before
  removing a topic for good. I'll show you that in the next phase."*

### The 20-question eval set

This is a good moment to capture eval questions. Ask the user:

**"Imagine it's six months from now and you've been using this steadily.
What are 20 questions you'd want to be able to ask your wiki? They
don't have to be things you could ask today — the wiki hasn't grown
yet. They just have to be things you'd genuinely care about knowing
later. We'll use them to keep an eye on whether your wiki is getting
better or worse over time. Think of it as a little health check for
your future self."**

Write the questions into `Paperwik\eval.json` together. The format is
spelled out in the file's comment block. Don't worry about the
`expected_chunks` field yet — that gets filled in after enough sources
have been ingested to have real expected answers.

---

## Phase 4 — Safety and interruption (minutes 45–60)

### Goal
User knows how to stop the agent, what the three un-bypassable prompts
look like, and what to do when something goes wrong.

### Script

1. Show the user: *"If you ever want your helper to stop, press
   **Ctrl+C**. It'll pause mid-thought — that's totally fine, nothing
   gets left broken because every file change is already saved before
   the next one begins. You can experiment, say 'stop', change your
   mind. It's designed to forgive that."*
2. Demonstrate: ask the agent to do something long ("lint the wiki" will
   do). Press Ctrl+C partway through. Agent stops. User sees "interrupted"
   message.
3. Explain: *"Three things will interrupt you regardless of what the
   agent is doing. These come from Anthropic, not from our code, and we
   can't silence them:"*
   - **OAuth re-auth** — every ~24 hours or whenever your Claude token
     expires, you'll see "please sign in again" in your browser. Click
     Approve. It takes 10 seconds.
   - **Terms of Service updates** — Anthropic occasionally pushes a
     ToS prompt. Read it, Accept.
   - **Rate limit** — if you exhaust your Claude Pro 5-hour window, the
     agent stops mid-task. Wait ~5 hours. The agent's own "quota
     telemetry" hook should warn you before you hit this.

4. **Show the diagnostic log:** Open `Documents\Paperwik-Diagnostics.log`
   in Notepad. This is where the agent records anything weird. If
   something goes sideways, email the last ~100 lines to the installer.

5. **Show "scrub X" in dry-run mode** (don't actually redact anything).
   Point out the two-step confirmation flow. Emphasize: **this is the
   only truly destructive thing the agent does, and it makes sure you
   mean it.**

6. Hand the user `OPERATIONAL-ENVELOPE.md` (printed out or emailed). It's
   the reference sheet.

### End of Phase 4

- User can install (they watched).
- User can ingest (they did one).
- User can query (they did one).
- User can interrupt and read the diagnostic log (they saw how).
- User has the envelope doc and a way to reach the installer.

Schedule a **14-day check-in** on the user's calendar AND the installer's
calendar before leaving. Don't skip this — the whole measurement
discipline depends on it.

---

## Post-session checklist (installer only)

- [ ] `eval.json` has 20 questions the user authored
- [ ] User's calendar has the 14-day check-in
- [ ] Installer's calendar has the 14-day check-in
- [ ] Success criteria committed to the project tracker BEFORE leaving:
      ≥10 sources ingested, ≥3 cross-referenced entity pages, ≤3 help
      requests in the 14 days
- [ ] User has the installer's contact info + the envelope doc
- [ ] Diagnostic log path verified + user knows how to find it
