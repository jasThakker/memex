#!/usr/bin/env bash
# PostToolUse hook, runs after Edit/Write.
# - .md files: regenerate the HTML view in docs/html/ (derived output, gitignored).
# - .py files: report ruff problems. Never modifies source files.
# Exit 2 sends the output back to Claude; exit 0 means nothing to report.
set -uo pipefail

file=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))')

[[ -f "$file" ]] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

if [[ "$file" == *.md ]]; then
  if ! out=$(python3 scripts/render_docs.py "$file" 2>&1); then
    printf 'render_docs.py failed for %s:\n%s\n' "$file" "$out" >&2
    exit 2
  fi
  exit 0
fi

[[ "$file" == *.py ]] || exit 0

# Until Phase 1 adds ruff to the project, do nothing.
uv run --no-sync ruff --version >/dev/null 2>&1 || exit 0

status=0
output=""
if ! out=$(uv run --no-sync ruff check "$file" 2>&1); then
  output+="$out"$'\n'
  status=2
fi
if ! out=$(uv run --no-sync ruff format --check --diff "$file" 2>&1); then
  output+="$out"$'\n'
  status=2
fi

if [[ $status -ne 0 ]]; then
  printf 'ruff reported problems in %s (fix them with a visible edit):\n%s' "$file" "$output" >&2
fi
exit $status
