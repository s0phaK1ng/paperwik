# Divergences from CoWork's deep-research engine

paperwik's `paperwik-research` skill is forked from CoWork's
`deep-research` skill (workspace path:
`C:\Users\mmgla\Claude CoWork\.claude\skills\deep-research\`). This file
records every paperwik-specific divergence so future maintainers (and the
upstream CoWork agent) know what's intentional and what isn't.

CoWork upstream version covered: **v1.2** (2026-04-27).
paperwik adoption version: **v0.5.0** (2026-04-27, plugin v0.7.0).

---

## 1. Sanitizer cascade — paperwik runs the 2-tier subset

| Tier | CoWork (full 3-tier asymmetric) | paperwik (2-tier) |
|------|----------------------------------|--------------------|
| **Tier 1** | `scripts/sanitizer.py` deterministic rapidfuzz match | ✅ adopted verbatim |
| **Tier 2** | Local DeBERTa-v3 NLI on NUC via the `verify_nli` MCP tool. `scripts/tier2_verify.py` orchestrates. Asymmetric: auto-accepts entailment ≥0.70, escalates contradiction verdicts to Tier 3 always. | ❌ **SKIPPED.** No NUC, no MCP server, no NLI model on the user's laptop. AMBIGUOUS/FAIL from Tier 1 escalates DIRECTLY to Tier 3. |
| **Tier 3** | LLM-as-judge via Task subagent (typically Haiku 4.5). `scripts/tier3_judge.py` orchestrates `prepare`/`merge`. | ✅ adopted verbatim |

**Functional equivalence:** paperwik's 2-tier is what you get from CoWork's
3-tier when `DEEP_RESEARCH_ZSC_ENABLED=false`. CoWork's kill-switch path
IS paperwik's default path. No behavioral semantics are lost — only the
Tier 2 optimization (~65% of AMBIGUOUS pairs auto-resolved locally).

**Cost impact:** for paperwik's friend-and-family scale (1–2 runs per
week), the extra ~30 Task subagent calls per run that Tier 2 would have
absorbed are within Claude Pro subscription budget. If a user ever
escalates to ~10 runs per day, Tier 2 could be ported by lifting
`scripts/tier2_verify.py` and a quantized local NLI model — that's
v0.8.x territory, not in scope.

**Files affected by this divergence:**
- `scripts/sanitizer.py` — paperwik runs Tier 1 only; same algorithm as CoWork
- `scripts/tier3_judge.py` — adopted verbatim; paperwik feeds Tier 1 → Tier 3 directly
- `references/sanitizer_pattern.md` — paperwik-specific rewrite documenting the 2-tier flow
- `scripts/stitch_final.py` — adopted verbatim; reads `verification_report_v3.json` if present, falls back to Tier 1's `verification_report.json`

---

## 2. Hybrid model routing — paperwik pins per-Task, CoWork inherits

CoWork's deep-research lets the parent session's model bleed into Task
subagents. paperwik **explicitly pins `model:` on every Task call**:

| Phase | paperwik | CoWork |
|-------|----------|--------|
| Phase 1 PLANNER | `model: "sonnet"` | (inherits from parent) |
| Phase 2 SEARCHER | `model: "haiku"` | (inherits) |
| Phase 3 SECTION WRITERS | `model: "sonnet"` | (inherits) |
| Phase 4 EDITOR | `model: "sonnet"` | (inherits) |
| Phase 4 Tier 3 JUDGE | `model: "haiku"` | (inherits) |
| Phase 4 weakening rewrites | `model: "haiku"` | (inherits) |

**Why:** Pro users can pick Opus in the Desktop model dropdown. If the
parent session inherits to Task subagents and the user has Opus selected,
EVERY phase runs on Opus and burns ~3× the budget. paperwik's explicit
pinning prevents this. (CoWork users tend to be technical and pick
Sonnet manually; paperwik users are non-technical and the default
must-not-burn-budget behavior is mandatory.)

---

## 3. Default section count — paperwik 3, CoWork 8–12

paperwik defaults to 3 section writers. CoWork defaults to 8–12.

**Why:** Pro has ~45 prompts per 5-hour rolling window. A 3-writer run
fits comfortably inside one window; an 8–12-writer run flirts with the
prompt cap and may stall the user mid-run if they had other recent
chats. The user can ask for more sections explicitly ("research X
thoroughly with 8 sections") and the planner respects that.

**Files affected:** `references/planner_prompt.md` (paperwik's planner
default + the SKILL.md design-principles bullet #4).

---

## 4. Drop target — paperwik writes to Vault/Inbox/, CoWork writes to project-specific

paperwik final document drops to `~/Paperwik/Vault/Inbox/deep_research_<slug>_<date>.md`.
CoWork drops to a project-specific path (e.g., `Paperclip/Research/_Inbox/`)
selected by the SKILL.md's runtime detection block.

**Why:** paperwik has a single vault. The downstream `paperwik-ingest`
skill picks up everything in `Vault/Inbox/` automatically. CoWork is a
multi-project workspace and needs per-project routing.

**Files affected:** `scripts/stitch_final.py` is invoked with paperwik-specific
`--drop-target ~/Paperwik/Vault/Inbox/`. SKILL.md hardcodes the target
in Phase 4 step 6.

---

## 5. Wake-lock + slug generator — paperwik adds, CoWork doesn't have

paperwik's Phase 0 invokes `scripts/wake_lock.py enforce` before the
engine runs and `release` in `finally`. Without this, the user's laptop
sleeps mid-run.

paperwik's Phase 4 originally used `scripts/slug_from_topic.py` to build
a dad-readable filename (`Cognitive Health Strategies - 2026-04-24.md`).
v0.5.0 of the skill migrated slug generation INTO `scripts/stitch_final.py`
to match the CoWork v1.1 layout, but `slug_from_topic.py` is preserved
for backwards compatibility.

**Why:** Non-technical Windows laptop. CoWork users are technical and
running on machines with proper power profiles.

**Files affected:** `scripts/wake_lock.py` (paperwik-only),
`scripts/slug_from_topic.py` (paperwik-only).

---

## 6. Up-front cost/time confirmation gate — paperwik mandates, CoWork doesn't

paperwik's Phase 0b shows the user an estimate before running:

```
A research run on "<topic>" will:
  - take ~8-12 minutes of wall-clock time
  - consume roughly 2-4 hours of your weekly Sonnet budget
  - use roughly 30-50 prompts of your 5-hour window

If you're already close to your weekly cap, you may want to wait. Proceed? (yes/no)
```

CoWork users are presumed to know their budget; paperwik users explicitly
do not.

**Files affected:** SKILL.md Phase 0b (paperwik-specific section).

---

## 7. One-time advisory + sentinel — paperwik adds, CoWork doesn't

paperwik shows a one-time tip explaining that the research engine routes
to Sonnet/Haiku regardless of the user's Desktop model picker. Sentinel
file at `~/Paperwik/.claude/skills/state/research-advisory-shown` ensures
it shows once and only once.

**Why:** Pro users will check the model picker, see Opus, and worry that
research will burn 3× budget. The advisory disarms the worry up front.

**Files affected:** SKILL.md Phase 0a (paperwik-specific section).

---

## 8. Hook registration — paperwik via install.ps1 + vault settings.local.json, CoWork via per-project settings.local.json

paperwik's installer (`install.ps1` substep c4) merges the SubagentStart
and SubagentStop hook stanzas into `~/Paperwik/Vault/.claude/settings.local.json`
on every install run. CoWork users edit each project's `settings.local.json`
manually.

**Why:** paperwik is a single-vault product; one-time merge is the right
ergonomic. CoWork is multi-project and per-project opt-in is intentional.

**Files affected:** `install.ps1` substep c4 (paperwik-only); CoWork
SKILL.md "Hook Registration" section is more elaborate.

---

## 9. Plugin distribution path — paperwik ships via plugin marketplace, CoWork ships at workspace root

paperwik's research skill lives at
`plugin/skills/paperwik-research/` inside the GitHub repo
`s0phak1ng/paperwik`. End users install via the Claude Code plugin
marketplace (`/plugin marketplace add s0phak1ng/paperwik`); the
installer one-liner clones the plugin to
`~/.claude/plugins/marketplaces/paperwik/` and merges hook stanzas.

CoWork's deep-research skill lives at the workspace root
(`C:\Users\mmgla\Claude CoWork\.claude\skills\deep-research\`) so all
projects in the workspace can opt in. Not distributed externally.

**Why:** paperwik is a product; CoWork is a workspace.

**Files affected:** all paths inside the skill are relative to the
plugin install location, not absolute. The CoWork SKILL.md's "Hook
Registration" section uses absolute paths because the skill is at the
workspace root.

---

## 10. Output validator's intermediate H2 minimum — paperwik 2, CoWork 3

CoWork's `output_validator.py` v1.1 requires `## Context` first, `## Sources`
present, and **at least 3 other H2 sections in between** (`MIN_OTHER_H2_SECTIONS = 3`).
That value was tuned for CoWork's 8–12-section default outline.

paperwik's planner default is **3 sections total** (Divergence #3) — so a typical
final document has Context + 2 topical sections + Sources = only 2 intermediate H2s.
A `>=3` rule would fail every paperwik run on default settings.

paperwik lowers `MIN_OTHER_H2_SECTIONS` to **2**. Surfaced by the synthetic test
harness at `plugin/tests/research_harness/` on first execution; the harness's
3-section synthetic plan failed validation under CoWork's stricter value.

**Files affected:** `scripts/output_validator.py` (one line change with a
comment block citing this divergence).

---

## 11. Planner outline contract — paperwik 3-default with no Findings requirement

CoWork's `planner_prompt.md` mandated three sections by name (Context, Findings,
Gaps & Caveats) and recommended 8–10 outline sections by default. CoWork's v1.1
relaxed the validator to allow topic-specific section names instead of literal
`## Findings`, but the planner_prompt.md was never updated to match.

paperwik's planner_prompt.md is updated to:

- Default to **3 outline sections** (matching SKILL.md design principle #4)
- Allow **topic-specific section names** (matching v1.1 relaxed validator)
- Drop the literal `## Findings` mandate (the topical sections ARE the findings)
- Note that `## Sources` and `## Verification` are generated by the Editor
  during stitching; they should NOT appear in the planner's outline

This is a paperwik internal-consistency fix — the planner's contract now
matches the SKILL.md flow and the v1.1 relaxed validator. Surfaced by the
synthetic test harness.

**Files affected:** `references/planner_prompt.md` (Section count requirements
+ Mandatory sections subsections rewritten).

---

## 12. settings.json safety rail — paperwik uses surgical Windows-system-dir denies, not broad `Write(C:/**)`

CoWork's deep-research engine doesn't ship a vault-level `settings.json`
(it uses workspace-level Claude Code configuration). paperwik's
`templates/paperwik/.claude/settings.json` originally had a broad
`Write(C:/**)` and `Edit(C:/**)` deny in its safety rail — intent: "block
the agent from writing anywhere on the Windows system drive."

v0.7.0's first real research run (D1, 2026-04-27) surfaced that the broad
deny was triggering permission prompts (in bypassPermissions mode) on every
write inside `~/Paperwik/.claude/skills/state/deep-research/runs/...` —
which are absolute paths starting with `C:/Users/<user>/Paperwik/...` and
therefore matched `Write(C:/**)`. The deep-research skill writes its run
state under that path, so Matt hit ~6-10 permission prompts during a
single research run.

v0.7.1 replaces the broad deny with surgical denies for Windows system
directories specifically:

- `Write/Edit(C:/Windows/**)`
- `Write/Edit(C:/Program Files/**)`
- `Write/Edit(C:/Program Files (x86)/**)`
- `Write/Edit(C:/ProgramData/**)`

Plus belt-and-suspenders explicit allows for `.claude/skills/state/**`
paths. (Note: under Claude Code's current permission semantics, the
explicit allows are documentation/future-proofing — F1a's deny refactor
does the actual behavior fix.)

**Known limitation** introduced by this divergence: non-system-dir
absolute writes outside `~/Paperwik` (e.g., `C:/Users/<other-user>/`,
`C:/Users/<user>/Desktop/`) are no longer blocked by the safety rail.
paperwik's normal operation never targets such paths, but a
prompt-injection attack could. Theoretical risk; revisit in v0.8.x if
needed.

**Files affected:** `templates/paperwik/.claude/settings.json` (deny
list refactor + allow list extension).

---

## What paperwik adopted VERBATIM from CoWork v1.1+v1.2

These files are byte-identical between the CoWork source and paperwik's
copy as of v0.5.0 / 2026-04-27:

- `references/section_writer_prompt.md` (v2)
- `references/search_contract.md` (v2)
- `references/tier3_judge_prompt.md` (D2R-1, NEW)
- `references/planner_prompt.md` (unchanged from v1)
- `references/backend_swap_contract.md` (unchanged from v1)
- `scripts/chunk_text.py` (unchanged from v1)
- `scripts/sanitizer.py` (unchanged from v1; Tier 1 only is correct for paperwik)
- `scripts/output_validator.py` (v1.1 relaxed)
- `scripts/merge_chunks.py` (D2R-2, NEW)
- `scripts/parse_section_response.py` (D2R-5, NEW)
- `scripts/stitch_final.py` (v1.1, NEW)
- `scripts/tier3_judge.py` (v1.1, NEW)
- `hooks/subagent_start.py` (unchanged from v1)
- `hooks/subagent_stop.py` (unchanged from v1)

When the upstream CoWork engine ships v1.3 / v2 / etc., a maintainer
should diff these files against `C:\Users\mmgla\Claude CoWork\.claude\skills\deep-research\`
and decide which deltas to absorb.

---

## What paperwik SKIPPED from CoWork v1.1+v1.2

- `scripts/tier2_verify.py` — NUC + MCP + NLI model required, skipped
  per Divergence #1.

If a future paperwik version adds a local NLI capability (probably as
part of v0.8.x once we have a working framework for distributing
quantized ONNX models — see lessons learned in v0.6.x), this file
becomes adoptable.

---

## Open upstream items the maintainer should track

- **Tier 2 portability.** If CoWork develops a Tier 2 implementation that
  doesn't require a NUC (e.g., DeBERTa-v3 NLI as an in-process ONNX
  model), absorb it. Paperwik already runs an ONNX classifier in
  `scripts/classify.py` for project routing (v0.6.x), so the
  infrastructure is partly there.
- **Section-writer file-write fix upstream in Claude Code.** If the
  Claude Code team fixes the subagent-write sandbox issue that drove the
  inline-return contract (v1.2 D2R-4), inline-return becomes optional
  rather than mandatory. We should keep using it anyway — the parser is
  deterministic and the contract is tighter than file-writes.
- **Schema-strict search subagents.** `references/search_contract.md` v2
  pins the 7-key schema; `scripts/merge_chunks.py` normalizes 4 known
  drift variants. If CoWork (or paperwik) hits a 5th variant in the
  field, expand the merger.

---

## Build & ship metadata

| Item | Value |
|------|-------|
| paperwik plugin version when adopted | v0.7.0 |
| paperwik-research skill version when adopted | 0.5.0 |
| CoWork upstream version absorbed | v1.2 |
| Migration commit | `d94b5fe` (v0.7.0) |
| Migration date | 2026-04-27 |
| Files adopted verbatim | 14 (5 references + 7 scripts + 2 hooks) |
| Files adapted | 2 (`SKILL.md`, `references/sanitizer_pattern.md`) |
| Files skipped | 1 (`scripts/tier2_verify.py`) |
| Net new code | ~1100 lines (the 4 new scripts + tier3_judge_prompt.md + this file) |
