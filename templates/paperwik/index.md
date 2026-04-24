---
created: 2026-04-22
tags: [index, meta]
---

# Index

Auto-maintained catalog of every page in this wiki. One line per page.
The assistant updates this after every ingest and after any lint pass.

Dataview query below renders dynamically from the YAML frontmatter on each page.

## Active projects

```dataview
TABLE file.folder AS "Project", length(file.outlinks) AS "Links out", length(file.inlinks) AS "Links in", dateformat(file.mtime, "yyyy-MM-dd") AS "Last updated"
FROM "Vault/Projects"
WHERE !contains(file.folder, "_sources") AND !contains(file.folder, "Inbox") AND file.name != "index" AND file.name != "log" AND file.name != "Welcome" AND file.name != "CLAUDE"
SORT file.mtime DESC
```

## Entities (people, papers, concepts, organizations)

```dataview
LIST
FROM #person OR #paper OR #concept OR #organization
SORT file.name ASC
```

## Inbox (pending sources to ingest)

```dataview
LIST
FROM "Vault/Inbox"
SORT file.mtime DESC
```

---

*If this page shows no results, Dataview is either not enabled, still indexing, or the wiki is empty.*
