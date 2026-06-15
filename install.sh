#!/usr/bin/env bash
# fable-forge installer — wires the gate into your agent CLI(s) so every session
# (and every orchestrated worker) runs on top of it. Idempotent. Needs python3.
#
#   sh install.sh                 # machine-wide: every Claude Code project (auto-detect Codex)
#   sh install.sh --here          # this repo only (Claude Code project-level settings)
#   sh install.sh claude-code     # Claude Code only
#   sh install.sh codex           # Codex only
#   sh install.sh all             # both
#   sh install.sh --uninstall [target]
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
have(){ command -v "$1" >/dev/null 2>&1; }
chmod +x "$HERE"/adapters/*/install.sh "$HERE"/adapters/codex/*.sh "$HERE"/gates/*.py 2>/dev/null || true

UNINSTALL=""; SCOPE="machine"
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) UNINSTALL="--uninstall"; shift ;;
    --here|--project) SCOPE="project"; shift ;;
    *) break ;;
  esac
done
TARGET="${1:-auto}"

# --here: gate ONLY this repo via Claude Code project-level settings (lower commitment)
if [ "$SCOPE" = "project" ]; then export CLAUDE_SETTINGS="$PWD/.claude/settings.json"; fi

cc(){ bash "$HERE/adapters/claude-code/install.sh" $UNINSTALL; }
cx(){ bash "$HERE/adapters/codex/install.sh" $UNINSTALL; }

if ! have python3; then echo "wfb: python3 is required (the gate engine is stdlib python3)."; exit 1; fi

case "$TARGET" in
  claude-code) cc ;;
  codex)       cx ;;
  all)         cc; cx ;;
  auto)
    did=0
    if [ -d "$HOME/.claude" ] || have claude; then cc; did=1; fi
    if have codex; then cx; did=1; fi
    if [ "$did" = 0 ]; then
      echo "wfb: no Claude Code (~/.claude) or codex CLI detected."
      echo "  install explicitly:  sh install.sh claude-code   |   sh install.sh codex"
      exit 1
    fi ;;
  *) echo "usage: sh install.sh [claude-code|codex|all] | --uninstall [target]"; exit 2 ;;
esac

if [ -z "$UNINSTALL" ]; then
  echo
  echo "wfb installed (scope: $SCOPE). Work-shaped prompts auto-start a gated task;"
  echo "edits are blocked until .forge/spec.json passes the gate."
  if [ "$SCOPE" = "project" ]; then echo "  active only in: $PWD"; else echo "  active in every Claude Code project on this machine"; fi
  echo "  toggle in-session:  forge off  /  forge on  /  forge status"
  echo "  Codex headless:      forge-codex-accept \"<goal>\" --repo <dir>   (adapters/codex/ENFORCEMENT.md)"
fi
