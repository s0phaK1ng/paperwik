# Paperwik — What Your Helper Does (and Doesn't Do)

A friendly reference sheet for the person using Paperwik. Good to keep
handy for the first few weeks. The installer usually hands this over at
the end of the training session.

---

## What your helper is happy to do

### Keep everything in one folder
- Your vault lives at `C:\Users\<you>\Paperwik\`.
- That folder is the helper's entire world. It reads and writes there,
  and only there.
- If you ever ask it to touch something outside, you'll see a friendly
  error. That's on purpose — it's the safety rail.

### Read new sources for you
- Drop a PDF, a markdown export, or a Gemini Deep Research report into
  `_Inbox/`.
- Say *"ingest this"* or *"ingest the new source."*
- Your helper reads it, writes a summary, creates a topical folder (or
  files it into an existing one), pulls out the people and ideas and
  papers, and weaves everything into your wiki.
- Your original source isn't deleted — it just moves from `_Inbox/` into
  `<Project>/_sources/` so your Inbox stays tidy.

### Answer questions with sources
- *"What do I know about X?"* or *"Summarize what I've read on Y."*
- You always get citations back to specific pages in your own wiki, so
  you can check the source yourself.
- Got a good answer you want to keep? Say *"file that for me"* and it
  becomes a permanent wiki page.

### Remember where you left off
- From session to session, your helper keeps track of recent decisions,
  preferences, and what you were working on.
- It handles long sessions gracefully. Claude has a way of "compacting"
  older conversation to save room — the helper saves what matters before
  that happens and picks up where it left off after.

### Undo
- Say *"undo that"* and the most recent change reverts. Every change
  gets a quiet snapshot behind the scenes for exactly this reason.
- Experiment freely. Nothing is truly gone unless you explicitly ask
  for it to be.

### Truly delete, when you want to
- Say *"scrub X from my wiki"* or *"redact X permanently."* Your helper
  walks you through a two-step confirmation, then removes X from both
  the current files and their history.
- If you use OneDrive or Google Drive for backup, those keep copies for
  about 30 days. Your helper gives you a link to the cloud trash if you
  want to clear it from there too.

### Run a health check
- *"Lint my wiki"* or *"check my wiki for problems"* — your helper
  surfaces orphan pages, contradictions, stale claims, entities that
  might deserve their own page, and projects that have gone quiet.
- Just reports. Never fixes anything without asking you first.

### Measure itself
- Once a week, your helper quietly runs a retrieval quality check
  against the 20 questions you wrote during setup.
- If results slip by more than 5%, it's noted in the diagnostic log so
  it can be investigated.

---

## What your helper won't do

### Touch the rest of your computer
- Your helper can only reach files inside `C:\Users\<you>\Paperwik\`.
  Not your Documents, not your Downloads, not Windows system files, not
  anything else.
- Destructive Git commands (the kind that could wipe history) are
  blocked even if a malicious instruction somehow asks for them.

### Send your notes anywhere you didn't set up
- Your wiki lives on your disk. When your helper "thinks" about your
  content, it calls Claude (Anthropic's servers), but the markdown
  files themselves never leave your computer — except via your own
  OneDrive or Google Drive backup, which you control.
- Searching, embedding, and reranking all happen locally on your
  machine. Queries don't require internet after the first-time setup.

### Run arbitrary commands
- Only specific, pre-approved commands are allowed: the bundled
  retrieval scripts, safe Git operations, and one spaCy model download.
- If the helper ever seems to want to run something else, that's a bug —
  please tell your installer.

### Burn through your Claude quota without warning
- Claude Pro / Max plans have message limits. Heavy ingest sessions
  (many Deep Research reports back-to-back) can eat into them.
- Your helper watches for this and gives you a heads-up before you hit
  the wall.

### Pretend to remember things it doesn't
- If you ask about something older than its active memory, it'll search
  the wiki and tell you what it finds — not invent something plausible.
- If a topic has been redacted, your helper respects that. It won't
  reconstruct the content even if stray mentions linger in an index.

---

## Where things live

| File / folder | What it's for |
|---|---|
| `Paperwik\` | Your entire vault |
| `Paperwik\_Inbox\` | Drop zone for new sources |
| `Paperwik\_Archive\` | Auto-archived inactive projects |
| `Paperwik\<Project Name>\` | Topical folders your helper creates |
| `Paperwik\index.md` | The full list of everything in your wiki |
| `Paperwik\log.md` | Diary of what your helper has been up to |
| `Paperwik\decisions.md` | Things you've decided (once logged) |
| `Paperwik\knowledge.db` | The search index — leave this alone |
| `Paperwik\eval.json` | Your 20 questions for weekly quality checks |
| `Paperwik\.claude\` | Hidden config — leave this alone |
| `Documents\Paperwik-Diagnostics.log` | Your helper's diary |
| `Documents\Paperwik-Audit.log` | Redaction records (when you use them) |

## Things to say, any time

The every-day stuff:
- **"Ingest this"** — reads and files the newest thing in `_Inbox/`.
- **"What do I know about X?"** — searches and summarizes with sources.
- **"File that as a new page"** — turns the answer you just got into a
  lasting wiki page.
- **"Undo that"** — rolls back the most recent change.
- **"Scrub X"** — permanent removal, with confirmation.
- **"Lint my wiki"** — friendly health check.
- **"Check retrieval quality"** — runs the eval set and reports scores.

Maintenance:
- **"Update my wiki"** — pulls in the latest improvements.
- **"Rebuild the index"** — if search ever feels off.
- **"Check for updates"** — same thing as above, different wording.

When something feels wrong:
- **"Something's off"** — the helper runs its own diagnostic and tells
  you what it sees.
- **"Show me the diagnostic log"** — the last few entries from the
  diary file.

## When to reach out to whoever set this up

Send a message (with your diagnostic log attached) if:

- The helper gives you an error you don't understand.
- Something went wrong with a redaction or undo.
- The weekly quality number keeps sliding.
- You want something the helper can't do yet.

What you don't need to send a message about:
- Content questions about your own wiki — ask your helper.
- Whether to trust what the helper wrote — **you** are always the final
  judge of your own notes. The helper is a fast archivist, not an
  authority.
