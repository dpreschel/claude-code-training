#!/usr/bin/env bash
# Rebuild the course toolchain inside a fresh Docker sandbox (sbx).
#
# Only the repo and ~/.claude/skills are mounted from the host, so a new
# sandbox starts without these tools. Run from anywhere:
#
#   bash scripts/sandbox-setup.sh
#
# Safe to re-run. Needs these hosts allowed in the sandbox network policy
# (sbx policy allow network <hosts>, run on the host; global rules persist):
#   pypi.org files.pythonhosted.org release-assets.githubusercontent.com
#   services.gradle.org repo.maven.apache.org plugins.gradle.org
#   plugins-artifacts.gradle.org

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_VERSION="${PYTHON_VERSION:-3.15}"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "Node.js 24 and JDK 21 (apt)"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs-24 openjdk-21-jdk-headless

step "Java trust store (includes the sandbox proxy CA)"
# The JDK keystore starts empty here, so every Java/Gradle TLS download fails
# with "trustAnchors parameter must be non-empty" until it is regenerated.
sudo update-ca-certificates -f >/dev/null

step "npm, pnpm and bun"
# The nodejs-24 package ships without npm, so bootstrap it from the registry.
# The image's npm prefix (/usr/local/share/npm-global) is user-owned, so no
# sudo: running npm as root leaves root-owned files that break later installs.
# bun runs the repo's .claude/hooks/index.ts; without it every hook event
# fails with "bun: not found".
if ! command -v npm >/dev/null; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  tarball="$(curl -fsSL https://registry.npmjs.org/npm/latest | jq -r .dist.tarball)"
  curl -fsSL "$tarball" | tar xz -C "$tmp"
  node "$tmp/package/bin/npm-cli.js" install -g npm
  hash -r
fi
command -v pnpm >/dev/null || npm install -g pnpm
command -v bun >/dev/null || npm install -g --allow-scripts=bun bun
hash -r

step "Python $PYTHON_VERSION as default python/python3 (uv, in ~/.local/bin)"
# Debian's system Python is left in place for OS tooling.
uv python install "$PYTHON_VERSION" --default --preview-features python-install-default

step "Claude Code status line"
mkdir -p "$HOME/.claude"
install -m 0755 "$REPO_ROOT/scripts/statusline-command.sh" "$HOME/.claude/statusline-command.sh"
settings="$HOME/.claude/settings.json"
[ -f "$settings" ] || echo '{}' > "$settings"
jq --arg cmd "bash $HOME/.claude/statusline-command.sh" \
  '.statusLine = {type: "command", command: $cmd}' "$settings" > "$settings.tmp"
mv "$settings.tmp" "$settings"

step "Slide dependencies"
(cd "$REPO_ROOT" && pnpm install --silent)

step "Versions"
printf '%-8s %s\n' \
  node    "$(node --version)" \
  npm     "$(npm --version)" \
  pnpm    "$(pnpm --version)" \
  bun     "$(bun --version)" \
  java    "$(java -version 2>&1 | grep -m1 version)" \
  python  "$(python3 --version)" \
  uv      "$(uv --version)"
