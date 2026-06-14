#!/usr/bin/env bash
# fable-forge — Claude Code installer.
# Wires the forge hooks into user-level ~/.claude/settings.json so EVERY project,
# session, and orchestrated subagent inherits the gate. Idempotent. No deps but
# python3 (already required by the hooks).
#
#   sh install.sh            install / refresh
#   sh install.sh --uninstall   remove forge hooks
set -eu

HOOK_DIR="$(cd "$(dirname "$0")/../hooks" && pwd)"   # shared, runtime-agnostic hooks
STATUSLINE="$(cd "$(dirname "$0")" && pwd)/forge-statusline.py"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
MODE="install"
[ "${1:-}" = "--uninstall" ] && MODE="uninstall"

mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

HOOK_DIR="$HOOK_DIR" STATUSLINE="$STATUSLINE" SETTINGS="$SETTINGS" MODE="$MODE" python3 - <<'PY'
import json, os, shlex, sys

hook_dir = os.environ["HOOK_DIR"]
statusline = os.environ["STATUSLINE"]
path = os.environ["SETTINGS"]
mode = os.environ["MODE"]
TAG = "fable-forge"  # our hook commands contain the hook_dir path -> identifiable

with open(path, encoding="utf-8") as f:
    try:
        cfg = json.load(f)
    except Exception:
        cfg = {}

hooks = cfg.setdefault("hooks", {})

def strip_ours(event):
    groups = hooks.get(event, [])
    kept = []
    for g in groups:
        g2 = dict(g)
        g2["hooks"] = [h for h in g.get("hooks", [])
                       if hook_dir not in (h.get("command", ""))]
        if g2["hooks"]:
            kept.append(g2)
    if kept:
        hooks[event] = kept
    elif event in hooks:
        del hooks[event]

for ev in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
    strip_ours(ev)

if mode == "install":
    def cmd(name):
        return {"type": "command", "command": "python3 " + shlex.quote(os.path.join(hook_dir, name))}
    hooks.setdefault("UserPromptSubmit", []).append({"hooks": [cmd("user_prompt_submit.py")]})
    hooks.setdefault("PreToolUse", []).append(
        {"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [cmd("pre_tool_use.py")]})
    hooks.setdefault("PostToolUse", []).append(
        {"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [cmd("post_tool_use.py")]})
    hooks.setdefault("Stop", []).append({"hooks": [cmd("stop.py")]})

# Status-line indicator: show [why-was-fable-banned] when the gate is on. NEVER clobber
# an existing statusLine — only set ours if none, and only remove ours on uninstall.
sl_cmd = "python3 " + shlex.quote(statusline)
sl = cfg.get("statusLine")
sl_cur = sl.get("command") if isinstance(sl, dict) else None
sl_exactly_ours = sl_cur == sl_cmd  # ONLY a statusLine that is purely ours
sl_note = ""
if mode == "install":
    if sl is None:
        cfg["statusLine"] = {"type": "command", "command": sl_cmd}
        sl_note = "added"
    elif sl_exactly_ours:
        sl_note = "present"
    else:
        sl_note = "skipped"  # user has their own (or a composed) statusLine — never touch it
elif sl_exactly_ours:
    # Remove only when it is EXACTLY our command — never a custom/composed one, even if it
    # contains our path (the user may have appended our segment to their own line).
    del cfg["statusLine"]

with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"fable-forge: {mode} complete -> {path}")
print("  events:", ", ".join(k for k in ("UserPromptSubmit","PreToolUse","PostToolUse","Stop") if k in hooks))
if mode == "install":
    if sl_note in ("added", "present"):
        print("  status line: [why-was-fable-banned] shows when the gate is on")
    elif sl_note == "skipped":
        print("  status line: you already have one — to show the indicator, append the output of")
        print(f"               `{sl_cmd}` to your statusLine command")
PY

if [ "$MODE" = "install" ]; then
  echo "fable-forge: active for all Claude Code sessions. Toggle in-session by typing:"
  echo "             forge off            (this dir)        forge on / forge status"
  echo "             forge off here       (this chat only)  forge on here"
  echo "             forge off all        (whole machine)   forge on all"
  echo "             one-off env bypass:  FORGE_BYPASS=1"
else
  echo "fable-forge: removed."
fi
