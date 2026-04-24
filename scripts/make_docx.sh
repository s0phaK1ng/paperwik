#!/usr/bin/env bash
#
# make_docx.sh -- regenerate docs/Paperwik-User-Guide.docx from the
# canonical markdown references that ship with the paperwik-help skill.
#
# These three markdown files are the SINGLE SOURCE OF TRUTH for:
#   - the Claude-readable help the agent pulls in at runtime, AND
#   - the .docx user guide we print/email to non-technical users.
#
# Usage:
#   cd <plugin-root>   # repo root, where .claude-plugin/ lives
#   scripts/make_docx.sh
#
# Produces: docs/Paperwik-User-Guide.docx (non-empty on success).
#
# Exit codes:
#   0   docx generated successfully
#   1   pandoc not on PATH, or generation produced empty output, or
#       one of the reference files is missing
#
# Design notes:
#   - Uses pandoc because MkDocs/Docusaurus don't emit .docx natively and
#     Docusaurus's MDX format corrupts LLM consumption of the same source.
#   - --reference-doc is optional; if scripts/paperwik-brand.docx doesn't
#     exist we fall back to pandoc's default styling.
#   - Image-sizing note: inside the reference files, size images via
#     `![alt](img.png){width=400px}` attribute syntax -- pandoc's default
#     is 1.67" square which looks cramped (pandoc issue #976).

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF_DIR="$PLUGIN_ROOT/skills/paperwik-help/references"
OUT_DIR="$PLUGIN_ROOT/docs"
BRAND="$PLUGIN_ROOT/scripts/paperwik-brand.docx"
VERSION_FILE="$PLUGIN_ROOT/.claude-plugin/plugin.json"

# Verify pandoc is available
if ! command -v pandoc >/dev/null 2>&1; then
  echo "ERROR: pandoc not found on PATH." >&2
  echo "Install pandoc: https://pandoc.org/installing.html" >&2
  exit 1
fi

# Verify the three reference files exist
for f in what-is-paperwik.md how-to.md troubleshooting.md; do
  if [ ! -f "$REF_DIR/$f" ]; then
    echo "ERROR: missing reference $REF_DIR/$f" >&2
    exit 1
  fi
done

# Extract version from plugin.json (pure sed; avoids a python/jq dependency)
VERSION="$(sed -n 's/^\s*"version":\s*"\([^"]*\)".*/\1/p' "$VERSION_FILE" | head -n 1)"
VERSION="${VERSION:-unknown}"

mkdir -p "$OUT_DIR"

PANDOC_ARGS=(
  "$REF_DIR/what-is-paperwik.md"
  "$REF_DIR/how-to.md"
  "$REF_DIR/troubleshooting.md"
  -o "$OUT_DIR/Paperwik-User-Guide.docx"
  --toc
  -N
  --standalone
  --metadata "title=Paperwik User Guide"
  --metadata "subtitle=v${VERSION}"
)

if [ -f "$BRAND" ]; then
  PANDOC_ARGS+=(--reference-doc="$BRAND")
fi

pandoc "${PANDOC_ARGS[@]}"

# Guard against silent empty output
if [ ! -s "$OUT_DIR/Paperwik-User-Guide.docx" ]; then
  echo "ERROR: pandoc produced empty output" >&2
  exit 1
fi

SIZE="$(stat -c%s "$OUT_DIR/Paperwik-User-Guide.docx" 2>/dev/null || wc -c < "$OUT_DIR/Paperwik-User-Guide.docx")"
echo "OK: wrote docs/Paperwik-User-Guide.docx (${SIZE} bytes, v${VERSION})"
