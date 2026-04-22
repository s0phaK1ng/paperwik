# Building git-filter-repo.exe for Paperwik

This document is for the **plugin maintainer** only — end users never see it.
It explains how to produce `bin/git-filter-repo.exe`, the one binary that ships
in the Paperwik plugin. It's needed for the `redact-history` skill.

## Why a frozen .exe

`git filter-repo` is a Python script, not a Git built-in. There's no official
prebuilt Windows binary upstream. Rather than asking dad to install Python
separately just for one skill, we freeze the script into a standalone `.exe`
using PyInstaller.

## Prerequisites (one-time, on the dev machine)

- **Python 3.12** installed. Download from https://python.org/downloads. Tick
  "Add python.exe to PATH" during install.
- **Git** installed.

## Build steps

Open a PowerShell or cmd window.

### 1. Clone the source at a pinned commit

Pinning to a specific commit means future Paperwik releases that rebuild
this binary produce the same behavior.

```powershell
cd C:\temp
git clone https://github.com/newren/git-filter-repo.git
cd git-filter-repo
git checkout v2.47.0
```

If v2.47.0 isn't available when you build, use the latest release tag (check
`git tag | tail -5`). Record the tag you used in the release notes.

### 2. Install a pinned PyInstaller

```powershell
python -m pip install --upgrade pip
python -m pip install pyinstaller==6.12.0
```

PyInstaller version 6.12.0 (or whichever is current stable when you build).
Pinning avoids the build drifting between releases.

### 3. Freeze

```powershell
pyinstaller --onefile --name git-filter-repo git-filter-repo
```

This produces `dist\git-filter-repo.exe` (~10–15 MB).

### 4. Smoke-test it

```powershell
dist\git-filter-repo.exe --help
```

You should see the filter-repo help output. If you get a Windows Defender
warning about an unrecognized publisher, that's expected for unsigned
binaries — dismiss it. (Code signing is a v2 concern; for friends-and-family
v1 it's not critical.)

### 5. Copy into the plugin

```powershell
copy dist\git-filter-repo.exe <path-to-plugin-repo>\bin\git-filter-repo.exe
```

### 6. Commit + push

```powershell
cd <path-to-plugin-repo>
git add bin/git-filter-repo.exe
git commit -m "Add git-filter-repo.exe v2.47.0 (PyInstaller 6.12.0)"
git push
```

GitHub will handle this as a binary file. It's well under the 100MB limit,
so no Git LFS needed. A ~15MB binary is reasonable in the plugin repo.

## Rebuilding on upstream changes

Rebuild when:
- Upstream `git-filter-repo` releases a security fix
- PyInstaller releases a security fix
- Python 3.12 is deprecated (not for ~2 years)

Not when:
- A new PyInstaller or filter-repo version comes out with non-critical
  changes. Stability > currency for this binary.

## Verification after rebuild

Before shipping a rebuilt binary to users:

1. Build the plugin, install it locally.
2. Create a scratch Obsidian vault with 3 fake Deep Research markdown files.
3. Run `redact-history` against one of them in dry-run mode — confirm the
   preview is accurate.
4. Run for real with `yes, purge` — confirm the file is gone + a tombstone is
   written + the audit log has a new line.
5. Inspect `git log` — confirm the commits touching the purged file are gone.

Document the test in `CHANGELOG.md` for that release.

## Troubleshooting

### PyInstaller complains about missing modules
Add `--collect-all git_filter_repo` to the command.

### The frozen .exe is huge (>50 MB)
Add `--strip` (requires `strip.exe` from MinGW) and `--upx-dir` (download UPX
separately) to compress.

### Windows Defender flags the .exe at runtime on users' machines
This is the soft-mandatory argument for code signing. If more than one user
reports it, prioritize getting a code-signing cert. For v1, document it in
the Operational Envelope as a known quirk.
