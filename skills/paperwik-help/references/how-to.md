# How to do common things in Paperwik

## Ingest an article, PDF, or Word doc

1. Save the file into `C:\Users\<you>\Paperwik\Vault\Inbox\`. File Explorer drag-and-drop is fine. Any filename works.
2. In Claude Desktop's Code tab, type: **ingest this** (or "ingest the new source", or "read my Inbox").
3. Wait 10-60 seconds per document. On a first-ever ingest expect 3-5 minutes extra while Paperwik downloads its embedding and reranking models (about 600 MB, one-time).
4. Paperwik reports what it did: which project folder it filed under (creating one if needed), how many entity pages it created or updated, and how many chunks went into the search index.
5. When it's done, the source file moves from `Vault/Inbox/` into `Vault/Projects/<Project>/_sources/`. Summary pages live in `Vault/Projects/<Project>/<Page>.md`. Entity pages live in `Vault/Projects/<Project>/Entities/<Entity>.md`.

## Ingest something from a web page

Paste or type: **ingest this article: https://example.com/interesting-thing**. Paperwik fetches the page, saves a cleaned markdown copy into `Vault/Inbox/`, and then runs the normal ingest flow.

## Search your wiki

Just ask a plain-English question in the Code tab. Examples:

- "What do I know about cognitive health?"
- "Which researchers show up in more than two of my reports?"
- "Summarize the last three sources I added."
- "What did that Karpathy post say about LSTMs?"

Paperwik runs hybrid retrieval (keyword match + semantic similarity + entity graph + reranking) and answers with citations back to specific pages. Click any citation in Obsidian to see the source.

## Save an answer as a permanent page

If an answer is good enough to keep, say **file that as a new page** or **save that answer**. Paperwik creates a new page in the relevant project folder with your question as the title and the answer as the body. Questions are worth saving -- a wiki grows not just from sources you add but from answers you decide are worth keeping.

## Undo the last change

Say **undo that** or **roll that back**. Paperwik reverts the most recent file change using the silent git history every edit gets committed to. Experiment freely -- you can always undo.

## Find a specific entity

Say **show me the entity page for Andrej Karpathy** (substitute any person, paper, concept, or organization). If no page exists, Paperwik says so -- it doesn't invent one.

## Permanently delete a topic (redact)

Say **scrub X from my wiki** or **redact X permanently**. Paperwik walks you through a two-step confirmation, then removes the topic from both the live files AND git history. If you back up to OneDrive or Google Drive, those keep copies for ~30 days; Paperwik gives you a link to the cloud trash so you can clear it there too.

## Check the wiki's health

Say **lint my wiki** or **check my wiki for problems**. Paperwik scans for orphan pages (nothing links to them), entities mentioned in 3+ places but without their own page, contradictions between sources, and projects that have gone inactive. It reports findings -- it doesn't auto-fix anything.

## Rebuild the search index

Say **rebuild the index** or **my search feels broken -- rebuild it**. Paperwik walks every markdown file, re-chunks, re-embeds, re-extracts entities, and rewrites `knowledge.db` from scratch. Your actual notes are untouched. Takes 1-5 minutes depending on vault size.

## Check retrieval quality

Say **check retrieval quality** or **run the eval**. Paperwik runs your 20-question eval set (set up during installation; stored in `eval.json`) and reports NDCG@10, MRR, and Recall@5. Scores dropping by more than 5% since the previous run get flagged in the diagnostic log.

## Update Paperwik

When the maintainer publishes a new version:

1. In Claude Desktop's Code tab, click the **+** button next to the chat box.
2. Click **Plugins**.
3. Click **paperwik** under Personal.
4. Click **Update** on the plugin detail page. Desktop reloads the new version.
5. Click **Enable** on the same page even if it already shows as enabled -- Claude Desktop resets the enable state on every version bump (this is a Desktop UX quirk, not a Paperwik bug).
6. Fully quit and reopen Claude Desktop if skills don't immediately appear.

## Check what version you have

Say **what version of Paperwik is this?**. Claude reads `plugin.json` from the plugin cache and reports the version.

## Say "something feels off"

Paperwik runs its own self-diagnostic: checks OAuth status, disk state, database health, recent hook crashes. Tells you what it found. If nothing obvious, it points you at the diagnostic log (`Documents\Paperwik-Diagnostics.log`) which you can send to your installer.
