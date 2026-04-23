---
name: 👑 proactive-reauth
description: >
  Detect imminent or recent OAuth token expiry and proactively surface a
  friendly re-auth dialog before the user hits a 401 error. Triggers on
  phrases like "the agent stopped working", "I got logged out", "I got a
  401 error", "why won't you respond", "authentication failed", "token
  expired", "I need to sign in again". Also runs proactively at session
  start (via wrapper script invocation, not as a hook) when credentials
  are within 12 hours of expiry or older than 30 days on disk. CoWork
  research shows OAuth refresh is intermittently broken in 2026, so this
  is a v1 requirement, not v1.1.
allowed-tools: Read, Bash
---

# proactive-reauth

Catch OAuth token expiry before the user does.

## Triggers

- "the agent stopped working"
- "I got logged out" / "authentication failed"
- "token expired" / "OAuth error" / "401"
- "why won't you respond"
- "I need to sign in again"
- Proactive: triggered by the session launcher when credential file is
  stale (age >30d OR expiresAt within 12h)

## Flow

### 1. Check credential freshness

Read `%USERPROFILE%\.claude\.credentials.json`. It contains:

```json
{
  "claudeAiOauth": {
    "accessToken": "sk-ant-oat01-...",
    "refreshToken": "...",
    "expiresAt": 1775212290694,
    "scopes": [...],
    "subscriptionType": "pro"
  }
}
```

Run a quick Python check via `uv run`:

```python
# /// script
# requires-python = ">=3.12"
# ///
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

path = Path(os.environ['USERPROFILE']) / '.claude' / '.credentials.json'
if not path.exists():
    print('MISSING'); sys.exit(0)
try:
    j = json.loads(path.read_text(encoding='utf-8'))
    oauth = j.get('claudeAiOauth', {})
    if not oauth.get('accessToken'):
        print('MALFORMED'); sys.exit(0)
    expires_ms = oauth.get('expiresAt')
    if expires_ms:
        expires = datetime.fromtimestamp(expires_ms / 1000, tz=timezone.utc)
        hours_left = (expires - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left <= 0:
            print('EXPIRED')
        elif hours_left < 12:
            print(f'WARN {hours_left:.1f}')
        else:
            print(f'VALID {hours_left:.1f}')
    else:
        age_days = (datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).days
        if age_days > 30:
            print('EXPIRED')
        elif age_days > 14:
            print('WARN')
        else:
            print('VALID')
except Exception as e:
    print(f'MALFORMED {e}')
```

Classify into: `VALID` / `WARN` / `EXPIRED` / `MISSING` / `MALFORMED`.

### 2. Report to the user

Branch based on state:

- **VALID** → If the user triggered this skill, reassure them:
  *"Your Claude sign-in is fresh (expires in X hours). The agent
  stopping isn't a sign-in issue. Let me check the diagnostic log for
  what actually happened."*

- **WARN** → *"Your Claude sign-in is aging (X hours left before
  re-auth). You're still good for now, but you may be asked to sign in
  again in the next session. Want to re-auth now to skip the
  interruption?"*

- **EXPIRED** → *"Your Claude sign-in has expired. Run `/login` at the
  prompt to re-authenticate. A browser window will open; click Approve.
  Takes ~10 seconds."*

- **MISSING** → *"I can't find any Claude credentials. This means you
  haven't signed in yet, or the credential file was deleted. Run
  `/login` to sign in."*

- **MALFORMED** → *"Your credential file is corrupted. Either delete
  `%USERPROFILE%\.claude\.credentials.json` and run `/login`, or send
  the file to your support contact — they can repair it."*

### 3. Append to diagnostic log

```
[TIMESTAMP] [proactive-reauth] state=<STATE> hours_left=<N> action=<recommendation>
```

## Rules

- **Never delete the credentials file yourself.** That's the user's
  action.
- **Never run `/login` automatically.** The OAuth flow involves a
  browser approval — the user has to see it.
- **If the state is VALID but the user reports the agent is stuck**,
  don't insist. Check the diagnostic log for HOOK_CRASH or rate-limit
  indicators instead.
- **Be honest about what you DON'T know.** If the `.credentials.json`
  schema has changed in a new Claude Code version, the parsing may
  return spurious WARN/EXPIRED signals. Match the reported state to the
  user's actual experience before concluding.
