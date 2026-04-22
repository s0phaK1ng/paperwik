# Paperwik — When Things Feel Off

Every now and then, something will interrupt your flow. None of these
are your fault, and Paperwik isn't broken — they come from Anthropic's
side of things, and each one has a quick friendly fix.

This is a reference. Skim it now, keep it handy. You probably won't need
most of it.

---

## 1. "Please sign in again" (the most common one — roughly once a day)

### What you'll see

Mid-conversation, your helper stalls and the terminal shows:

```
API Error: 401 ... OAuth token has expired ...
```

Or a browser window pops open asking you to sign in to Claude.

### Why this happens

Claude's sign-ins last about 24 hours. When the token expires, Claude
needs a fresh one. Sometimes that happens silently; sometimes you need
to click Approve in the browser.

### What to do

1. If the browser opened — click **Approve** on claude.ai. Pop back to
   your helper. It'll resume where you left off.
2. If you only saw the error and no browser — type `/login` at the
   Claude Code prompt. That asks for a fresh sign-in.
3. If neither works — close everything, reopen Claude Desktop (or your
   terminal), and start fresh. The sign-in flow will trigger
   automatically.

Takes about 10 seconds either way.

### Only reach out to your installer if…

- You signed in successfully and the error keeps coming back.
- The browser shows your Claude Pro subscription is expired (that's a
  billing issue, not a Paperwik issue).

---

## 2. "Please accept our updated Terms" (rare — every few months)

### What you'll see

A Claude.ai page opens with an updated Terms of Service. Your helper
pauses until you've acknowledged it.

### Why this happens

Anthropic updates their ToS occasionally. The CLI waits for you to see
the change before continuing.

### What to do

1. Open claude.ai.
2. Read the update (or skim — your call).
3. Click **Accept**.
4. Return to your helper and type your next message. It picks right back up.

### Reach out to your installer only if…

- The update is substantial and you're not sure whether to accept.
  Check with them first.

---

## 3. "You've hit your message limit" (happens during heavy ingests)

### What you'll see

```
API Error: 429 Rate limit reached on claude-sonnet-4-6 ...
```

Or mid-operation:

```
Stopping — you've hit your 5-hour message limit. Try again at <time>.
```

### Why this happens

Claude Pro has a rolling 5-hour message window. A bunch of ingests in a
row (each one calls Claude several times to extract entities and write
summaries) can exhaust it. Your helper tries to warn you at 80%, but it
sometimes sneaks past.

### What to do

1. Note the reset time in the message — something like *"try again at
   3:45 PM."*
2. Take a break until then. No retries will work sooner.
3. When you come back, pick up where you left off. The helper won't
   leave anything half-finished — if an ingest got cut off, it retries
   cleanly.

### How to avoid hitting this next time

- **Spread ingests out.** Rather than 10 reports in a row, do a few,
  take a break, come back.
- **When you see the 80% warning**, switch to lighter tasks for a while
  — querying, reading your wiki, filing back answers, linting.
- **If this keeps happening**, Claude Max has a larger quota. Or just
  ingest about one Deep Research report per day.

### Reach out to your installer if…

- The 5-hour window resets but you're still getting 429 errors —
  something's off with the token or the plan.
- Your quota is draining faster than your ingests would explain.

---

## The diagnostic log — your universal helpline

Every time something non-routine happens, your helper writes a line to:

```
C:\Users\<you>\Documents\Paperwik-Diagnostics.log
```

If anything feels off:

1. Open that file in Notepad.
2. Copy the last ~100 lines (or everything since the last time things
   felt fine).
3. Send it to whoever installed Paperwik for you, with a sentence or two
   about what you saw.

That's almost always enough to figure out what happened. Don't worry
about understanding the log yourself — it's meant for your installer.
Don't delete it, either; the history is useful context.

---

## "Something's wrong and I don't know what"

Before reaching out, try these in order. The first two fix roughly half
of all weirdness:

1. **Close and reopen.** Shut down Claude Desktop (or your terminal),
   open it again, try the thing that wasn't working.
2. **Restart Obsidian.** If the UI looked wrong, this usually fixes it.
3. **Run `claude /doctor`.** Claude has a built-in check-up command that
   looks for common problems.
4. **Peek at the diagnostic log** for a line that starts with
   `HOOK_CRASH` in the last few minutes. If one exists, that's the
   likely suspect — send your installer that line plus the 20 lines
   around it.
5. **Say "rebuild the index"** if search feels wrong. This reconstructs
   the search database from your markdown files (which are untouched).
6. **Say "check for updates"** as a last resort. Sometimes an Anthropic
   change has broken a piece and there's already a patch waiting.

If none of that helps, send the diagnostic log and a screenshot to your
installer. There's no mystery that won't resolve with context and
patience.
