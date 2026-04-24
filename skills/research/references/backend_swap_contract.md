# Backend Swap Contract

Action item **A8** (ported to paperwik as action item #409). Formalizes the
boundary that makes this engine disposable when native Claude or Gemini deep
research APIs stabilize.

---

## The Contract

**Downstream systems (skills, hooks, ingestion pipelines, other plugins) may
depend ONLY on:**

1. The **file drop event**: a markdown file appears at paperwik's configured
   drop target: `~/Paperwik/Vault/Inbox/`.
2. The **file format**: YAML frontmatter with the 5 required keys + H2/H3
   body + Sources table (see paperwik decision equivalent of #305 and
   `SKILL.md` §Output Format Contract).

**Downstream systems may NOT depend on:**

- Any file under `~/Paperwik/.claude/skills/state/deep-research/` (internal)
- Any script under `plugin/skills/research/scripts/` (internal)
- Any hook under `plugin/hooks/subagent_{start,stop}.py` (internal)
- The number of sections, the chunking strategy, the fuzzy threshold, or
  any other implementation detail
- The presence of a `run_id`, `verification_report.json`, or any other
  intermediate artifact
- The timing of when the file appears (could be 30 seconds with a native
  API, 15 minutes with the current engine)

---

## Why This Matters

As of 2026-04-24:

- **Gemini Deep Research API** launched (`deep-research-max-preview-04-2026`
  endpoint, `background=True`, $1–$7 per task — verified via CoWork V5 probe).
- **Anthropic Claude Research mode** exists in consumer Claude.ai for up to
  45 min autonomous runs, but is NOT yet exposed programmatically (as of
  CoWork V2 probe). This will almost certainly ship within 12–24 months.

When a native API stabilizes AND it's acceptable for paperwik's use case,
the swap looks like:

1. Replace the entire 4-phase engine with a single HTTP call wrapper.
2. The wrapper still writes a markdown file to `~/Paperwik/Vault/Inbox/`,
   with the same format.
3. Downstream ingestion (paperwik `ingest` skill) requires **zero changes**.
4. The old engine's code moves to `_deprecated/` and gets deleted after 30
   days of stable native-API operation.

If downstream systems had been coupled to engine internals, that swap would
require updating multiple skills, hooks, and possibly the knowledge base
schema. The contract prevents that coupling.

---

## Decision Reference

This contract is the operational expression of paperwik's decision equivalent
of **CoWork #307**: "File-based handoff is the stable integration contract —
backend is swappable."

Any change to this contract requires:
1. Explicit update to the decision (superseding decision logged in paperwik's
   decision log)
2. Migration plan for all downstream consumers (currently: `ingest` skill)
3. User approval via `/plan` → `/validate-build-plan` → `/build`

---

## Enforcement

Two enforcement mechanisms:

1. **SKILL.md Invariants §2**: "One engine entrypoint. Other skills/scripts
   must not call internal phases directly."
2. **Code review discipline**: any PR that adds a reference to
   `plugin/skills/research/scripts/` or
   `~/Paperwik/.claude/skills/state/deep-research/` from outside this skill's
   own directory must be rejected and refactored to depend on the file drop
   instead.

The engine itself does NOT currently expose any runtime enforcement (e.g.,
sealed directories) — this is a discipline contract, not a technical one.
Upgrading to technical enforcement is out of scope for v0.4.0.

---

## paperwik / CoWork divergence

CoWork and paperwik ship independent implementations of this engine (per
handoff §10). Both engines emit to the same YAML + H2/H3 + Sources format,
but:
- CoWork drops to `Paperclip/Research/_Inbox/` (infrastructure path).
- paperwik drops to `~/Paperwik/Vault/Inbox/` (end-user Obsidian vault path).

Downstream consumers are also different:
- CoWork: `/research-ingestion` skill in the main CoWork .claude/skills/.
- paperwik: `ingest` skill (or explicit "ingest this" user command) absorbs
  Vault/Inbox drops into the right project folder.

The backend_swap_contract applies identically to both. If native APIs ship,
paperwik swaps its engine independently of CoWork — they're not a shared
codebase.

---

## Version History

- **v1 (2026-04-22, CoWork action item A8)** — Initial contract. Establishes
  the downstream dependency boundary and explains the swap motivation.
- **v1.paperwik (2026-04-24, paperwik action item #409)** — Ported from
  CoWork with drop-target paths updated: `~/Paperwik/Vault/Inbox/` instead
  of CoWork's `Paperclip/Research/_Inbox/`. Downstream consumer reference
  updated from `/research-ingestion` to paperwik's `ingest` skill.
  Paperwik / CoWork divergence section added.
