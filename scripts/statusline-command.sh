#!/bin/bash
input=$(cat)
model=$(echo "$input" | jq -r '.model.display_name // "?"')
dir=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')
used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')

branch=$(git -C "$dir" --no-optional-locks symbolic-ref --short HEAD 2>/dev/null || git -C "$dir" --no-optional-locks rev-parse --short HEAD 2>/dev/null)
out="$model | $dir"
# Docker sandbox (sbx) sets SANDBOX_NAME; flag it in yellow at the front.
[ -n "${SANDBOX_NAME:-}" ] && out="$(printf '\033[33mIN SBX\033[0m') | $out"

if [ -n "$branch" ]; then
  dirty=""
  [ -n "$(git -C "$dir" --no-optional-locks status --porcelain 2>/dev/null)" ] && dirty="*"
  out="$out | $(printf '\033[32m%s%s\033[0m' "$branch" "$dirty")"
fi

if [ -n "$used" ]; then
  pct=$(printf '%.0f' "$used")
  if [ "$pct" -gt 80 ]; then
    ctx=$(printf '\033[31mctx %s%%\033[0m' "$pct")
  else
    ctx="ctx ${pct}%"
  fi
else
  ctx="ctx --"
fi
out="$out | $ctx"
printf '%s' "$out"
