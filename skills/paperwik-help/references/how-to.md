# How to do common things in Paperwik

## Ingest an article, PDF, or Word doc

Two equivalent ways — pick whichever feels easier. Result is the same.

**Way 1 (easiest, what most people do): drag-and-drop into Claude Desktop's chat bar.**

1. In Claude Desktop, open the Code tab.
2. Drag the file from File Explorer straight into the chat box. You'll see it attached as a chip (with the filename visible).
3. Type **ingest this** and send.
4. Wait 10-60 seconds per document. On a first-ever ingest expect 3-5 minutes extra while Paperwik downloads its embedding and reranking models (about 600 MB, one-time).
5. Paperwik reports what it did: which project folder it filed under (creating one if needed), how many entity pages it created or updated, and how many chunks went into the search index.

**Way 2 (better for batches, or if you live in Obsidian): drop into the vault's Inbox folder.**

1. Save the file into `C:\Users\<you>\Paperwik\Vault\Inbox\`. File Explorer drag-and-drop is fine. Any filename works. You can drop multiple files at once.
2. In Claude Desktop's Code tab, type **ingest my Inbox** (or "ingest the new sources", or "read everything in Inbox").
3. Paperwik walks the Inbox and ingests each file in turn. Same reporting as Way 1.

**Either way, when ingest finishes:** the source file lives at `Vault/Projects/<Project>/_sources/<filename>`. Summary pages live in `Vault/Projects/<Project>/<Page>.md`. Entity pages live in `Vault/Projects/<Project>/Entities/<Entity>.md`.

## Ingest something from a web page

Paste or type: **ingest this article: https://example.com/interesting-thing**. Paperwik fetches the page, saves a cleaned markdown copy into `Vault/Inbox/`, and then runs the normal ingest flow.

## Do deep research on a topic

Say **research cognitive health thoroughly** (substitute any topic). Paperwik runs a 4-phase research pipeline using Claude's built-in web tools -- no external APIs or keys required. Takes ~8-12 minutes. Drops a 3,000-8,000 word synthesis with 15+ cited sources into `Vault/Inbox/`. You then say "ingest this" the same way you would for any source.

Before the run starts, Paperwik shows you a cost/time estimate like "this will take ~10 min and consume roughly 2-4 Sonnet hours of your weekly budget." Say **yes** or **proceed** to continue, or **no** or **wait** to cancel. Don't skip this gate -- it's there so you know what you're spending before you spend it.

The first time you ever run research, Paperwik also shows a one-time note explaining that research always uses Sonnet + Haiku regardless of which model you've picked in the main chat. That note never repeats.

Good topics for research: anything broad enough to deserve a long cited writeup. Bad topics: "what year was the Eiffel Tower built" (too small -- just ask the question directly) or "my grocery list for tomorrow" (nothing to research).

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
3. In the Directory dialog that opens, make sure the **Code** tab is selected (usually is by default), then click **paperwik** in the list. (On older Claude Desktop builds, paperwik may appear under a **Personal** tab instead — either location works.)
4. Click **Update** on the plugin detail page. Desktop reloads the new version.
5. Click **Enable** on the same page even if it already shows as enabled -- Claude Desktop resets the enable state on every version bump (this is a Desktop UX quirk, not a Paperwik bug).
6. Fully quit and reopen Claude Desktop if skills don't immediately appear.

## Check what version you have

Say **what version of Paperwik is this?**. Claude reads `plugin.json` from the plugin cache and reports the version.

## Say "something feels off"

Paperwik runs its own self-diagnostic: checks OAuth status, disk state, database health, recent hook crashes. Tells you what it found. If nothing obvious, it points you at the diagnostic log (`Documents\Paperwik-Diagnostics.log`) which you can send to your installer.
