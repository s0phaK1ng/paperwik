# Paperwik

An AI helper that quietly keeps your notes organized for you.

**Based on the LLM-Wiki pattern described by [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) in April 2026.** Paperwik is one implementation of that pattern, packaged for non-technical Windows users.

> **You are probably not the intended end user.** This repo is a plugin meant to be installed on someone's computer by a friend, family member, or anyone comfortable with a terminal. End users never come here directly. This README is for people evaluating the design or considering a contribution.

## What it is

Paperwik turns a capable AI agent into a personal research and journaling archivist. You drop sources in; it reads, summarizes, cross-links, and keeps a growing markdown wiki in your Obsidian vault.

- Drop PDFs, articles, or Gemini Deep Research exports into an `_Inbox/` folder.
- Say "ingest this."
- The agent reads, summarizes, routes to a topical folder (auto-created if needed), pulls out the people and ideas worth tracking, and weaves everything into your wiki.
- You read and browse in Obsidian — graph view, backlinks, Dataview queries.
- Everything is plain markdown on your disk. No cloud, no database, no vendor lock-in.

## The bet (Karpathy's framing)

Traditional RAG retrieves from raw sources on every query — nothing accumulates between questions. The wiki pattern inverts this: an LLM agent incrementally builds a persistent, interlinked markdown graph so insights compound over time. As Karpathy puts it: *"Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase."* LLMs don't get bored of maintenance the way humans do, which is why this works.

Read [the original gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) first if you haven't. It's the clearest single explanation of why this pattern is different from RAG, and it's a short read.

## What's inside

- `skills/` — description-triggered capabilities (ingest, query, lint, redact, etc.)
- `hooks/` — lifecycle scripts (memory save/restore, auto-file, audit logging, safety rails)
- `scripts/` — Python retrieval stack (embeddings, search, reranker, entity graph) with PEP-723 inline deps, run via `uv`
- `templates/vault/` — the starter folder structure the agent lays down on first run
- `.claude-plugin/plugin.json` — the manifest

## Who this is for

- **End users:** non-technical friends, family, and anyone who wants an AI archivist for their research or notes without learning how it works. **Recommended entry point:** Claude Desktop (which includes Claude Code), because it's the friendliest setup for people who don't live in a terminal.
- **Installers:** someone comfortable running a couple of install commands on behalf of an end user, then doing a one-hour training session together.
- **Developers:** folks adding support for other agents (see roadmap below).

## How it's delivered today

1. Run the one-line bootstrap: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex` — installs Claude Desktop (with Claude Code), Obsidian, and `uv`.
2. Open Claude Code (inside Claude Desktop), run `/plugin marketplace add s0phak1ng/paperwik` + `/plugin install paperwik`.
3. On first session, the scaffolding hook creates the vault at `%USERPROFILE%\Knowledge\` and downloads the retrieval models once (~3–5 min). After that, it's instant.

No custom installer to build. No Python environment management for the end user. One bundled binary (`git-filter-repo.exe`) for the redaction feature.

## Roadmap — agent-agnostic future

Paperwik's valuable piece is the **methodology** — how an AI agent maintains a compounding wiki. That methodology doesn't depend on any one vendor. The scripts, vault structure, and knowledge-graph schema are all agent-neutral; only the plumbing (hooks, slash commands, permissions) is Claude-Code-specific.

Adapters planned:

- **v1 (today):** Claude Code, running inside Claude Desktop on Windows.
- **v1.1+:** Gemini CLI adapter.
- **v1.2+:** OpenAI Codex adapter (AGENTS.md-based).
- **v2:** Local-LLM adapter (Ollama or similar), for people who want the pattern fully offline.

The core retrieval + memory + graph code in `scripts/` is already agent-agnostic and will port directly. The adapter layer for each agent is the new work.

If you want to write an adapter, open an issue — happy to collaborate.

## Architecture highlights

- **Single vault** — one Obsidian vault, topical project folders inside, agent auto-routes via embedding similarity.
- **Hybrid retrieval** — SQLite + `sqlite-vec` + FTS5 + `fastembed` + `FlashRank` + spaCy, all toggleable via `retrieval_config.json`.
- **Entity graph** — PERSON / CONCEPT / PAPER / ORGANIZATION extracted at ingest, stored in SQLite.
- **Compaction-resilient memory** — PreCompact + SessionStart(compact) hook pair writes salient state to disk before Claude's auto-compression and re-hydrates after.
- **YOLO-safe permissions** — `defaultMode: dontAsk` + narrow allow list + a PowerShell `PreToolUse` governor that blocks path traversal, compound shell, and unsafe git. Zero approval prompts during routine use.
- **Silent Git autosave** — every file mutation committed invisibly, enabling a conversational `revert-state` skill for "undo that."
- **Weekly retrieval eval** — 20-question NDCG@10/MRR/Recall@5 harness against a user-authored question set, alerts on 0.05 WoW drop.
- **True redaction** — `git filter-repo`-backed skill with four-gate safety (dry-run → explicit confirm phrase → second gate on >20 files → wiki-name typed confirmation). Writes tombstones to prevent reconstruction.

## Credits + how Paperwik differs from Karpathy's original

Karpathy's gist describes the **pattern** at an idea level. It explicitly invites readers to "copy-paste this to your own LLM agent" and let the agent build out specifics. Paperwik is one such build-out — opinionated toward a particular audience and workload.

### What we kept from the original

- **The three layers:** immutable raw sources, an agent-owned wiki, a schema file teaching the agent how to behave.
- **The three operations:** ingest, query, lint.
- **The `index.md` + `log.md` convention** for navigation and history.
- **Obsidian as the reading surface.** Graph view, backlinks, Dataview — all preserved.
- **Standard markdown, no proprietary formats.** Your notes survive the tool.
- **Queries-become-pages:** good answers get filed back into the wiki so exploration compounds alongside ingestion.
- **The core metaphor.** The wiki is the codebase; the LLM is the writer. We take this seriously — the user doesn't edit wiki pages directly, because the agent will rewrite them next time it touches those topics. Let the agent own its codebase.

### Where we diverged, and why

| Karpathy's original | Paperwik | Why |
|---|---|---|
| A prose idea-file you paste into your LLM of choice; agent-agnostic | A packaged plugin for a specific agent (Claude Code via Claude Desktop) for v1, with other agents on the roadmap | Non-technical users shouldn't have to understand agent configuration to benefit from the pattern. We traded breadth for a paved path |
| Optional [`qmd`](https://github.com/tobi/qmd) CLI for search once the vault outgrows `index.md` | Hybrid retrieval stack bundled from day one: SQLite + `sqlite-vec` + FTS5 + `fastembed` + `FlashRank` + spaCy + entity graph | Our target user generates ~1 Gemini Deep Research report per day. They'd hit the index-only ceiling in weeks. We front-loaded the retrieval infrastructure |
| Human-in-the-loop: "I read the summaries, check the updates, guide the LLM on what to emphasize" | Automatic project routing, silent Git autosave, auto-filed chat, compaction-resilient memory | A non-technical user can't be asked to curate at every turn. We made the defaults sensible and the corrections easy ("undo that", drag folders to retrain the router) |
| Filesystem layout open-ended; applications suggested (personal, research, book companion, business wiki) | One vault per install, topical project folders auto-created by the agent | A non-technical user wants "my notes" to be one place. Multiple vaults is a power-user concept |
| No taxonomy prescribed | We tried PARA, then dropped it; agent creates topical project folders on demand | PARA's Projects/Areas/Resources/Archive distinction requires the user to model their own life. Topical folders don't |
| No structured entity extraction | PERSON / CONCEPT / PAPER / ORGANIZATION graph built at ingest and stored in SQLite | Deep Research reports are entity-dense; cross-report queries ("which researchers appear across multiple reports?") fail on vector search alone |
| No compaction-resilience pattern | `PreCompact` + `SessionStart(compact)` hook pair writes durable state before auto-compaction and restores after | Measured data from a related project showed rule compliance drops from ~75% to ~25% post-compaction without this pattern. For long sessions, it's the difference between a helpful archivist and an amnesiac one |
| No measurement discipline | 20-question retrieval eval harness running weekly against a user-authored question set, alerts on 5% WoW NDCG@10 drop | Retrieval quality silently degrades as wikis grow. Without measurement, you notice only when it's frustrating. By then it's hard to diagnose |
| No explicit threat model | `defaultMode: "dontAsk"` + narrow allow list + a `PreToolUse` governor that enforces path boundary, safe-git subset, and compound-command blocking | Zero approval prompts during routine use, without a wide-open security posture. A redacted topic can't be reconstructed even if stray references survive |
| No redaction mechanism (plain delete retains Git history) | `redact-history` skill backed by `git-filter-repo`, four-gate safety flow, tombstones to prevent agentic reconstruction | Real privacy requires truly erasing things, not just deleting the current file. Four gates because it's irreversible |

### A note on the relationship

The original is the clearer explanation of **why**. Paperwik is one working **how** for a specific audience. Neither replaces the other — if you're a technical user who wants to roll your own in the spirit of Karpathy's gist, do that. If you want to hand an AI archivist to your parent or a non-technical friend, install Paperwik.

### On attribution

Karpathy's gist has no explicit license, but it explicitly invites implementations. We've built this from the ideas — we haven't copied the gist's prose. Our language is our own; the intellectual debt is his.

## Internal design log (for contributors)

Major architectural decisions are tracked in the parent project's knowledge base. Key ones:

- `#297` Single vault with agent-managed project folders (not multi-wiki)
- `#298` Delivery = light plugin + first-run library-native model download (not custom installer)
- `#299` Hybrid retrieval stack in v1, all components toggleable
- `#300` Entity graph at ingest, not as future work
- `#301` 20-question eval harness from day one
- `#302` Two-band project routing with override learning

## Status

Pre-alpha. v0.1.0 is the first public release. First target user is a non-technical Windows user doing heavy Gemini Deep Research. Free and open source; no ads, no subscriptions beyond your own Claude Pro/Max plan.

## License

MIT. See LICENSE file.
