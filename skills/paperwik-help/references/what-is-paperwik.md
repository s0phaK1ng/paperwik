# What is Paperwik?

Paperwik turns your Claude Pro or Claude Max subscription into a personal research wiki. You drop articles, PDFs, Word documents, or text files into a single folder on your PC and tell Claude "ingest this." Claude reads the source, writes a clear summary page, and creates cross-referenced pages for the people, concepts, papers, and organizations it mentions. Over time your vault becomes a searchable second brain where every note links to every related note.

You read your wiki in **Obsidian** (a beautiful free note-taking app that the installer set up for you). You talk to Claude in **Claude Desktop** -- specifically the **Code tab**, where Paperwik lives as a plugin.

## What Paperwik can do (as of v0.3.0)

- **Ingest** -- drop any readable file into `Vault/Inbox/` and say "ingest this." Claude reads it, decides which project folder it belongs in, and writes summary + entity pages inside `Vault/Projects/<Project>/`.
- **Search** -- ask a plain-English question. Paperwik runs hybrid retrieval (keyword + semantic + entity graph + cross-encoder reranking) across your entire wiki and answers with citations.
- **Auto-link** -- every new page automatically cross-references existing entity pages. A second mention of "Andrej Karpathy" updates his existing page instead of creating a duplicate.
- **Auto-save** -- every file Claude writes is snapshot to a local git history behind the scenes. You can undo any change at any time by saying "undo that."
- **Auto-archive your chats** -- every conversation you have with Paperwik is mirrored to disk so you can ask months later, "what did we decide about X?" and Claude can read its own previous sessions.
- **Auto-log decisions** -- when you say things like "let's go with X" or "final answer: Y," Paperwik quietly notes the decision in `decisions.md`. You never have to tell it to remember.
- **Lint** -- ask for a health check and Paperwik surfaces orphan pages, entities that deserve their own page, contradictions between sources, and projects that have gone quiet.
- **Redact** -- ask Paperwik to "scrub X from my wiki" and it does a two-step-confirmed permanent removal from both files and git history.

## What Paperwik doesn't do

- It doesn't ingest content behind a login (paywalled articles, private Notion, private Google Docs). Give it files or public URLs.
- It doesn't edit your existing notes -- only adds new pages or appends to entity pages.
- It doesn't sync across devices. Your vault lives on this PC. Use OneDrive or Google Drive if you want backup.
- It doesn't run on macOS or Linux in v0.3.0 -- Windows 10/11 only.
- It doesn't send your markdown files anywhere. Claude reads them in memory during each session; the files themselves stay on your disk.

## Where things live

| Path | What's in it |
|---|---|
| `C:\Users\<you>\Paperwik\` | Your Paperwik system root (Claude Code's working directory) |
| `C:\Users\<you>\Paperwik\CLAUDE.md` | Instructions Claude reads every session -- don't edit |
| `C:\Users\<you>\Paperwik\knowledge.db` | The search index -- don't edit |
| `C:\Users\<you>\Paperwik\index.md` | Running catalog of every page in your wiki |
| `C:\Users\<you>\Paperwik\log.md` | Diary of every ingest / lint / redact |
| `C:\Users\<you>\Paperwik\decisions.md` | Auto-captured decisions you've stated in chat |
| `C:\Users\<you>\Paperwik\eval.json` | Retrieval-quality questions for weekly checks |
| `C:\Users\<you>\Paperwik\.claude\chat-history\<session>.jsonl` | Full chat transcripts, mirrored per session |
| `C:\Users\<you>\Paperwik\Vault\` | What Obsidian opens -- user-facing layer only |
| `C:\Users\<you>\Paperwik\Vault\Welcome.md` | Greeting / orientation page |
| `C:\Users\<you>\Paperwik\Vault\Inbox\` | Drop zone for new sources |
| `C:\Users\<you>\Paperwik\Vault\Projects\<Project>\` | Topical folders Paperwik creates |
| `C:\Users\<you>\Paperwik\Vault\Projects\<Project>\Entities\<Entity>.md` | Person / concept / paper / organization pages |
| `C:\Users\<you>\Paperwik\Vault\Projects\<Project>\_sources\` | Original source files after ingest |
| `C:\Users\<you>\Documents\Paperwik-Diagnostics.log` | Support log -- send this if something breaks |

**The simple version**: Obsidian opens `Vault/` and shows you Welcome, Inbox, and Projects. Everything else (database, logs, agent state) lives one level up where you don't have to look at it.
