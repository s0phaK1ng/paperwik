# Paperwik

An AI helper that quietly keeps your notes organized for you.

**Based on the LLM-Wiki pattern described by [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) in April 2026.** Paperwik is one implementation of that pattern, packaged for non-technical Windows users.

> **You are probably not the intended end user.** This repo is a plugin meant to be installed on someone's computer by a friend, family member, or anyone comfortable with a terminal. End users never come here directly. This README is for people evaluating the design or considering a contribution.

## What it is

Paperwik turns a capable AI agent into a personal research and journaling archivist. You hand it sources; it reads, summarizes, cross-links, and keeps a growing markdown wiki in your Obsidian vault.

**Two ways to ingest:**

- **Primary (what most users do):** drag a PDF, article, or markdown export from File Explorer directly into **Claude Desktop's chat bar** and say *"ingest this."*
- **Secondary (good for batching or Obsidian-native workflow):** drop files into the vault's `Inbox/` folder — visible in Obsidian's file tree — and say *"ingest my Inbox."*

Either way, the agent reads, summarizes, routes to a topical folder (auto-created if needed), pulls out the people and ideas worth tracking, and weaves everything into your wiki.

- You read and browse in **Obsidian** — graph view, backlinks, Dataview queries.
- Need a deeper dive? Say *"research X thoroughly"* and paperwik runs a ~10-minute 4-phase research pipeline using Claude's built-in web tools, dropping the cited writeup into your vault's `Inbox/` for the normal ingest flow to absorb.
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

1. Run the one-line bootstrap from PowerShell: `irm https://s0phak1ng.github.io/paperwik/install.ps1 | iex` — installs Git, Claude Desktop (which includes the Claude Code CLI), Obsidian, VC++ redist, and `uv`, then pre-clones the paperwik plugin and registers it with Claude Code so no manual `/plugin marketplace add` is required.
2. Open Claude Desktop. In the **Code tab**, click **+** → Plugins → paperwik → **Update** → **Enable**. Claude Desktop resets the enable state on version bumps, so re-click Enable even if it already looks enabled.
3. On first session in the scaffolded `%USERPROFILE%\Paperwik\` vault, the SessionStart hook finalizes the layout and downloads the retrieval models once (~3–5 min, ~600 MB). After that, it's instant.

No custom installer to build. No Python environment management for the end user. One bundled binary (`git-filter-repo.exe`) for the redaction feature.

## Roadmap — agent-agnostic future

Paperwik's valuable piece is the **methodology** — how an AI agent maintains a compounding wiki. That methodology doesn't depend on any one vendor. The scripts, vault structure, and knowledge-graph schema are all agent-neutral; only the plumbing (hooks, slash commands, permissions) is Claude-Code-specific.

Adapters planned:

- **Today (v0.7.x — see Status):** Claude Code, running inside Claude Desktop on Windows. Hardened across the v0.6.x ZSC saga and v0.7.0+v0.7.1 deep-research engine absorption, with tooling-enforced contracts and a synthetic regression baseline (see Architecture highlights).
- **Next:** Gemini CLI adapter.
- **Then:** OpenAI Codex adapter (AGENTS.md-based).
- **Long term:** Local-LLM adapter (Ollama or similar), for people who want the pattern fully offline.

The core retrieval + memory + graph code in `scripts/` is already agent-agnostic and will port directly. The adapter layer for each agent is the new work.

If you want to write an adapter, open an issue — happy to collaborate.

## Architecture highlights

- **Tooling-enforced contracts (the meta-principle, v0.6.4–v0.7.1)** — paperwik's central hardening lesson, codified across releases as decisions D11/D12/D13: any operation framed as *"agent reads tool output and writes a file"* gets skipped on real runs. The only reliable enforcement is to either (a) move the operation INTO a tool with input validation, or (b) gate downstream tools on the operation's outputs. paperwik now does both in multiple places — `write_summary.py` and `populate_label.py` (v0.6.4) refuse malformed input; `index_source.py` pre-flight gates REFUSE to index if `source_type:` or `.paperwik/label.txt` are missing; `merge_chunks.py` (v0.7.1) raises `ValueError` on chunks under 200 chars; the `output_validator.py` block-writes any document that doesn't match the structural contract. The wiki you ship cannot be malformed because the tools say no.
- **Synthetic test harness (v0.7.1-prep)** — `plugin/tests/research_harness/` exercises the deep-research contract chain (`merge_chunks` → `parse_section_response × 3` → `stitch_final` → `output_validator`) against fixed fixtures with 13 expected snapshots. Catches code-level bugs in the four contract scripts WITHOUT burning Pro budget on real WebSearch / WebFetch / Task calls. Caught 2 paperwik-side bugs at zero cost on first run before the real D1 ever happened. Runs as a regression gate on every commit that touches the research stack.
- **Single vault** — one Obsidian vault, topical project folders inside, agent auto-routes via a hybrid ZSC-first / cosine-fallback router (v0.6.0). v0.6.2 added a cold-start rule: with only 1 prior project, requires cosine ≥ 0.85 to file in (because cosine signal is unreliable until there's a comparison set).
- **Hybrid retrieval** — SQLite + `sqlite-vec` + FTS5 + `fastembed` + `FlashRank` + spaCy, all toggleable via `retrieval_config.json`.
- **Zero-shot classification (v0.6.0)** — local DeBERTa-v3-base-zeroshot-v2.0-c (commercial-license-safe) ONNX classifier handles two jobs: (1) the project router consults it FIRST against per-project descriptive labels, with cosine centroids as fallback when the entailment gate doesn't fire; (2) source-type classification (academic / article / newsletter / social / journal / reference) runs at the start of every ingest so the subagent's extraction prompt is tailored to the document's shape. Pure local — no Anthropic API dependency. First ingest pays a one-time ~30-60s cost: ~738 MB FP32 ONNX downloads from Hugging Face once, gets quantized to ~150 MB INT8 via `onnxruntime.quantization.quantize_dynamic`, the FP32 copy is deleted to reclaim space, and every subsequent classify call loads the cached INT8 in milliseconds.
- **Entity graph** — PERSON / CONCEPT / PAPER / ORGANIZATION extracted at ingest, stored in SQLite.
- **Compaction-resilient memory** — PreCompact + SessionStart(compact) hook pair writes salient state to disk before Claude's auto-compression and re-hydrates after.
- **YOLO-safe permissions** — `defaultMode: bypassPermissions` + a broad `Bash(*)` allow list + a PowerShell `PreToolUse` governor that blocks path traversal, compound shell, and unsafe git, plus a destructive-op deny list (rm -rf, git push --force, etc.). Zero approval prompts during routine use, without a wide-open security posture.
- **Deep research, in-session (v0.4.0 → v0.7.1)** — a 4-phase `paperwik-research` skill (PLANNER → SEARCHER → parallel SECTION WRITERS → EDITOR) that uses only Claude Code native primitives (WebSearch, WebFetch, Task subagents). Drops a 3-5K word synthesis document into Vault/Inbox/ for the existing ingest flow to absorb. Pro-tier aware: Sonnet for synthesis, Haiku for retrieval, default 3 sections (v0.7.1 hard-caps at 5 to stay within a Pro 5-hour window), up-front cost/time confirmation gate. v0.7.0 absorbed CoWork's deep-research v1.1+v1.2 contract clarity: subagents return drafts as inline four-marker blocks (`---BEGIN_SECTION---` / `---BEGIN_SUMMARY---` / `---METADATA---`) parsed by `parse_section_response.py`; searcher emits a strict 7-key canonical chunk schema normalized by `merge_chunks.py`; final document assembly via `stitch_final.py`; Tier 1 (rapidfuzz) → Tier 3 (LLM-judge) sanitizer cascade orchestrated by `tier3_judge.py`. CoWork's Tier 2 NLI step is intentionally skipped (NUC-required); the 2-tier subset is functionally equivalent to CoWork with `DEEP_RESEARCH_ZSC_ENABLED=false`. v0.7.1 hardened against 6 D1 retrospective surfaces: settings.json safety-rail refactor (no more permission prompts mid-run), exact-title constraints on `## Context` + `## Gaps & Caveats`, 200-char chunk minimum (kills agent terseness), 5-section cap, Sources-table filter to cited-only. End-to-end exercised by the synthetic test harness above.
- **Obsidian brand experience** — shipped `.obsidian/` template: 6 community plugins pre-installed (Dataview, Marp, Hover Editor, Recent Files, Better Search Views, Image Toolkit) + Canvas, a filtered and color-coded graph view (Inbox=gold, Entities=teal, Projects=slate, `_sources`=muted grey), a `<200-line` paperwik.css brand snippet, a minimalist hotkey scheme (Alt+H home, Alt+I Inbox, Ctrl+G graph; Vim-mode + split-pane unbound), a workspace injection that bypasses OneDrive sync conflicts, and a **DataviewJS security lockdown** closing an LLM-laundered XSS/RCE vector documented by Elastic Security Labs (PhantomPulse RAT, 2026).
- **Silent Git autosave** — every file mutation committed invisibly, enabling a conversational `revert-state` skill for "undo that."
- **Weekly retrieval eval** — 20-question NDCG@10/MRR/Recall@5 harness against a user-authored question set, alerts on 0.05 WoW drop.
- **True redaction** — `git filter-repo`-backed skill with four-gate safety (dry-run → explicit confirm phrase → second gate on >20 files → wiki-name typed confirmation). Writes tombstones to prevent reconstruction.

## Credits + how Paperwik differs from Karpathy's original

Karpathy's gist describes the **pattern** at an idea level. It explicitly invites readers to "copy-paste this to your own LLM agent" and let the agent build out specifics. Paperwik is one such build-out — opinionated toward a particular audience and workload.

### What we kept from the original

- **The three layers:** immutable raw sources, an agent-owned wiki, a schema file teaching the agent how to behave.
- **The three operations, now four:** ingest, query, lint — plus deep research, added in paperwik v0.4.0 and substantially hardened across v0.7.0 (CoWork v1.1+v1.2 contract absorption) and v0.7.1 (D1 retrospective fixes).
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
| No explicit threat model | `defaultMode: "bypassPermissions"` + broad `Bash(*)` allow + destructive-op deny + a `PreToolUse` governor that enforces path boundary, safe-git subset, and compound-command blocking | Zero approval prompts during routine use, without a wide-open security posture. A redacted topic can't be reconstructed even if stray references survive |
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
- `#317` Embedded help via `paperwik-help` skill + 3 Diataxis references + single-source pandoc pipeline (v0.3.0)
- `#321–326` Deep-research skill as a 4-phase Claude-Code-native pipeline: hybrid model routing (Sonnet synthesis / Haiku retrieval), explicit `model:` pin in every Task call, default 3 section writers, up-front cost/time gate, bundled open-Q resolutions (v0.4.0)
- `#327–333` Obsidian template rebuild (v0.5.0): plugin roster (include 7 / exclude 8) on agent-safety grounds, DataviewJS security lockdown citing PhantomPulse RAT (Elastic Security Labs 2026), CSS snippet over community theme for upgrade stability, workspace.json injection via install-time Copy-Item to bypass OneDrive conflicts, programmatic plugin install via GitHub Releases API, Local Graph depth-2 as default right-sidebar pane, user-custom.css as immutable upgrade-surviving tweak surface
- `#334–342` Zero-shot classification (v0.6.0): hybrid ZSC-first router with cosine fallback preserved (no regression risk for v0.5.x callers); local DeBERTa-v3-base-zeroshot-v2.0-c (commercial-license-safe) via direct onnxruntime + Rust tokenizers (no transformers library, saves ~2 GB of dep weight); lazy install-time quantization via `quantize_dynamic` because no INT8 variant exists on Hugging Face for this model (FP32 738 MB → INT8 ~150 MB on first classify, FP32 then deleted); per-project descriptive labels at `Vault/Projects/<Project>/.paperwik/label.txt` (agent-owned, hidden from Obsidian's file tree); source-type taxonomy (6 types) classified at NEW ingest Step 1.5 so subagent extraction is type-aware; weekly accuracy benchmark piggybacks on the existing retrieval-eval cron (no new infra); zsc_enabled toggle in retrieval_config.json as a kill-switch
- v0.6.1–v0.6.8 (April 2026): the ZSC saga shake-down. Field-stable verdicts after eight surgical patches — `onnx` PEP-723 dep, `MAX_CHUNK_CHARS` chunker hard cap, indexer self-heal of the projects table, `write_summary.py` + `populate_label.py` tools + indexer pre-flight gates that REFUSE to index if the agent skipped Step 4 / Step 5 of the ingest flow, `sympy` PEP-723 dep, dynamic ONNX input filter, NLI template + label tuning, and finally `multi_label=True` argmax for source classification. The lesson logged across D11/D12/D13: any operation framed as "agent reads tool output and writes a file" gets skipped — the only reliable enforcement is to either move the operation INTO a tool with input validation, or gate downstream tools on the operation's outputs.
- v0.7.0 (April 2026): absorbed CoWork's deep-research engine v1.1+v1.2 — section-writer subagents now return drafts as inline four-marker blocks (parsed by `parse_section_response.py`), the searcher emits a strict 7-key canonical chunk schema (normalized by `merge_chunks.py`), final document assembly via `stitch_final.py`, Tier 3 LLM-judge orchestration via `tier3_judge.py`. CoWork's Tier 2 NLI step is intentionally skipped (NUC-required); the 2-tier paperwik subset is functionally equivalent to running CoWork's engine with `DEEP_RESEARCH_ZSC_ENABLED=false`. Documented in `plugin/skills/paperwik-research/DIVERGENCES_FROM_COWORK.md` (12 paperwik-vs-CoWork divergences listed as of v0.7.1).
- v0.7.1 (April 2026): D1 retrospective. paperwik's first real deep-research run (LiFePO4 vs Li-ion EV battery chemistry tradeoffs, ~6,294 words, 26 cited sources) ran end-to-end successfully but exposed 6 contract-layer surfaces. v0.7.1 ships all six fixes as one release: F1 (settings.json safety-rail refactor — surgical Windows-system-dir denies replace broad `Write(C:/**)` deny), F2 (planner exact-title constraint on `Context` and `Gaps & Caveats`), F3+F4 (search contract 200-char chunk minimum + `merge_chunks.py` ValueError on shorter chunks — kills agent terseness at the contract AND merge layers), F5 (planner 5-section hard cap, was 6, after v0.6.x's "default 3" was overrun by an 8-section LiFePO4 outline), F6 (`stitch_final.py` filters Sources table + `sources_count` to chunks actually cited in the body). Synthetic harness extended with uncited fixture chunks so F6's filter is visibly exercised by the regression baseline. paperwik also published a bidirectional handoff doc (`handoff_paperwik_to_cowork_v0.7.1.md`) so the upstream CoWork engine can absorb F2/F3/F4/F6 + the harness pattern.

## Status

**v0.7.1 (April 2026).** Current released version. First target user is a non-technical Windows user doing heavy Gemini Deep Research. Free and open source; no ads, no subscriptions beyond your own Claude Pro/Max plan.

**The big idea, distilled across releases:** paperwik is not just a wiki agent — it's a wiki agent **whose contracts are tooling-enforced rather than prose-enforced**. Every shipped release for the last month has hardened a different layer of "agent reads tool output and writes a file" into "tool refuses to operate unless the contract holds." Indexer pre-flight gates that refuse missing `source_type:` (v0.6.4). `populate_label.py` and `write_summary.py` that validate inputs (v0.6.4). `merge_chunks.py` rejecting under-spec chunks (v0.7.1). `output_validator.py` block-writing malformed final documents. The wiki dad ends up with cannot be malformed because the tools refuse to make it so. This is paperwik's load-bearing differentiator from "give the LLM a folder and pray."

**v0.7.x (April 2026)** — deep-research engine absorption + hardening. v0.7.0 absorbed CoWork's `deep-research` engine v1.1+v1.2 (inline-return four-marker block contract for section writers, strict 7-key canonical chunk schema, 2-tier sanitizer cascade). v0.7.1 followed up with 6 D1 retrospective fixes that closed real surfaces from the first live research run on "LiFePO4 vs Li-ion EV battery chemistry tradeoffs" — settings.json safety-rail refactor, exact-title constraints, chunk-size enforcement, section count cap, Sources-table filter. End-to-end exercised by a new synthetic test harness at `plugin/tests/research_harness/` that runs the contract chain against fixed fixtures and gates regressions before they ship.

**v0.6.x (April 2026)** — local zero-shot classification, hardened across 8 surgical patches (v0.6.0 → v0.6.8). DeBERTa-v3-zeroshot-v2.0-c ONNX model, lazy-quantized to ~150 MB INT8 on first ingest, routes new sources by topical match against per-project descriptive labels and classifies source TYPE (academic / article / newsletter / social / journal / reference). Enforced by indexer pre-flight gates that REFUSE to index if the agent skipped any contract-mandatory step. The v0.6.1–v0.6.8 patch sequence was paperwik's apprenticeship in the architectural-enforcement lesson now codified as design principle (decisions D11/D12/D13).

**v0.5.0 (April 2026)** — Obsidian brand experience: pre-installed plugin roster, color-coded graph, hotkey scheme, DataviewJS security lockdown, workspace injection that bypasses OneDrive sync conflicts, Web Clipper integration.

**v0.4.0 (March 2026)** — first deep-research skill ported from CoWork's v1.0.

**No Anthropic API dependency added in any release** — pure local ONNX for classification, native Claude Code primitives for everything else (WebSearch, WebFetch, Task subagents). Users on Claude Pro/Max never see API metering.

A v0.7.x dial-in cycle is currently mid-flight: v0.7.1 shipped 2026-04-27 (commit `5e79e0f`); Phase E sandbox confirmation run on "best home espresso machines under $1000" is pending — on pass, v0.7.x marks field-stable in `AGENT_ONBOARDING.md`.

See the `.NOTES` block in `install.ps1` for the full changelog from v0.5.0 onward, and `plugin/skills/paperwik-research/DIVERGENCES_FROM_COWORK.md` for the 12-row paperwik-vs-CoWork divergence audit.

## License

MIT. See LICENSE file.
