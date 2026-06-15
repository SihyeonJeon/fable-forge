#!/usr/bin/env bash
# fable-forge — Codex installer.
# PRIMARY (steady-state, in-session): native Codex hooks merged into
# ~/.codex/hooks.json — PreToolUse blocks apply_patch until the spec gate passes,
# inside ONE codex session (no multi-pass reload). Token cost is measured in
# TOKEN_BUDGET.md (the gate adds turns; not a free single additive term).
# FALLBACK: the forge-codex wrapper (multi-pass; ~10x, use only where a runtime
# without hook trust is needed).
# Also places the procedure mandate in ~/.codex/AGENTS.md (inherited every session).
# Idempotent.   sh install.sh [--uninstall]
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK_DIR="$(cd "$HERE/../hooks" && pwd)"            # shared, runtime-agnostic hooks
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
HOOKS_JSON="$CODEX_HOME/hooks.json"
GLOBAL_AGENTS="$CODEX_HOME/AGENTS.md"
BIN_DIR="${FORGE_BIN_DIR:-$HOME/.local/bin}"
MARK_BEGIN="<!-- fable-forge:begin -->"
MARK_END="<!-- fable-forge:end -->"
MODE="install"
[ "${1:-}" = "--uninstall" ] && MODE="uninstall"

chmod +x "$HERE/forge-codex.sh" 2>/dev/null || true
mkdir -p "$CODEX_HOME"
[ -f "$HOOKS_JSON" ] || echo '{}' > "$HOOKS_JSON"

# --- 1) native hooks (the in-session path) ---
HOOK_DIR="$HOOK_DIR" HOOKS_JSON="$HOOKS_JSON" MODE="$MODE" python3 - <<'PY'
import json, os
hook_dir = os.environ["HOOK_DIR"]; path = os.environ["HOOKS_JSON"]; mode = os.environ["MODE"]
with open(path, encoding="utf-8") as f:
    try: cfg = json.load(f)
    except Exception: cfg = {}
hooks = cfg.setdefault("hooks", {})
def strip(ev):
    kept = []
    for g in hooks.get(ev, []):
        g = dict(g); g["hooks"] = [h for h in g.get("hooks", []) if hook_dir not in h.get("command","")]
        if g["hooks"]: kept.append(g)
    if kept: hooks[ev] = kept
    elif ev in hooks: del hooks[ev]
for ev in ("UserPromptSubmit","PreToolUse","PostToolUse","Stop"): strip(ev)
if mode == "install":
    def c(n): return {"type":"command","command":f'python3 "{hook_dir}/{n}"',"timeout":20}
    hooks.setdefault("UserPromptSubmit",[]).append({"hooks":[c("user_prompt_submit.py")]})
    hooks.setdefault("PreToolUse",[]).append({"matcher":"apply_patch|Edit|Write","hooks":[c("pre_tool_use.py")]})
    hooks.setdefault("PostToolUse",[]).append({"matcher":"apply_patch|Edit|Write","hooks":[c("post_tool_use.py")]})
    hooks.setdefault("Stop",[]).append({"hooks":[c("stop.py")]})
with open(path,"w",encoding="utf-8") as f: json.dump(cfg,f,indent=2,ensure_ascii=False); f.write("\n")
print(f"  hooks {mode} -> {path}: " + ", ".join(k for k in ('UserPromptSubmit','PreToolUse','PostToolUse','Stop') if k in hooks))
PY

# --- 2) global AGENTS.md procedure mandate ---
strip_block() {
  [ -f "$1" ] || return 0
  python3 - "$1" "$MARK_BEGIN" "$MARK_END" <<'PY'
import sys, re
p,b,e = sys.argv[1:4]; t=open(p,encoding="utf-8").read()
open(p,"w",encoding="utf-8").write(re.sub(re.escape(b)+r".*?"+re.escape(e)+r"\n?","",t,flags=re.S))
PY
}
strip_block "$GLOBAL_AGENTS"
if [ "$MODE" = "install" ]; then
  { echo "$MARK_BEGIN"; cat "$HERE/AGENTS.md"; echo "$MARK_END"; } >> "$GLOBAL_AGENTS"
fi

# --- 3) headless commands on PATH ---
# forge-codex-accept = PRIMARY headless path (worktree-accept; what README documents);
# forge-codex = older multi-pass wrapper fallback for non-git contexts.
if [ "$MODE" = "install" ]; then
  mkdir -p "$BIN_DIR"
  ln -sf "$HERE/forge-codex-accept.sh" "$BIN_DIR/forge-codex-accept"
  ln -sf "$HERE/forge-codex.sh" "$BIN_DIR/forge-codex"
else
  rm -f "$BIN_DIR/forge-codex-accept" "$BIN_DIR/forge-codex"
fi

if [ "$MODE" = "install" ]; then
  echo "wfb (Codex): installed."
  echo "  PRIMARY headless: $BIN_DIR/forge-codex-accept \"<goal>\" --repo <dir>  (worktree-accept)."
  echo "  in-session: native hooks in $HOOKS_JSON (when they fire — TRUST via 'codex' then '/hooks',"
  echo "    or for automation pass 'codex exec --dangerously-bypass-hook-trust ...')."
  echo "  mandate: $GLOBAL_AGENTS   multi-pass wrapper fallback: $BIN_DIR/forge-codex"
else
  echo "wfb (Codex): removed (hooks, AGENTS block, PATH shims)."
fi
