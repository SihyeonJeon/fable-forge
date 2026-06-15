#!/usr/bin/env bash
# fable-forge full sequential test suite (local, no network, no Codex API).
# Exercises: unit tests, gate lifecycle, runtime-agnostic hook block (Claude Code +
# Codex apply_patch), .forge exemption, edit logging, forbidden_paths verification,
# installer merge/uninstall roundtrip. Prints PASS/FAIL per step; exits 1 on any fail.
set +e
FORGE="$(cd "$(dirname "$0")/.." && pwd)"
GATE="$FORGE/gates/forge_gate.py"
HOOKS="$FORGE/adapters/hooks"
PASS=0; FAIL=0
ok(){ echo "  PASS  $1"; PASS=$((PASS+1)); }
no(){ echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
chk(){ [ "$1" = "$2" ] && ok "$3" || no "$3 (got '$1' want '$2')"; }

echo "== 1. unit tests =="
( cd "$FORGE" && python3 -m unittest -q tests.test_forge_gate ) >/tmp/ut.txt 2>&1 \
  && ok "unittest" || { no "unittest"; tail -5 /tmp/ut.txt; }

echo "== 2. gate lifecycle (deterministic) =="
D="$(mktemp -d)"; echo "x=1" > "$D/real.py"
python3 "$GATE" scaffold --root "$D" --goal "add a sort helper to real.py" >/dev/null
python3 "$GATE" validate --root "$D" --gate spec >/dev/null 2>&1; chk "$?" "1" "empty spec BLOCKED"
cat > "$D/.forge/spec.json" <<JSON
{"grade":"STANDARD","raw_goal":"add a sort helper","restated_goal":"Add a stable sort helper to real.py without changing existing function signatures, scoped to real.py.",
"non_goals":["no new dependency"],"constraints":{"invariant":["existing signatures unchanged"]},
"must_read":[{"path":"real.py","authority_reason":"owns the module API the helper joins"}],
"rejected_alternatives":[{"category":"scope","alternative":"add a sorting library","broken_boundary":"new dep, over-broad"},{"category":"tempting_shortcut","alternative":"mutate input in place","broken_boundary":"breaks caller expectations"}],
"risks":[{"risk":"unstable order","severity":"medium","mitigation":"unit test on duplicate keys"}],
"forbidden_paths":["config/*"],
"acceptance_criteria":[{"criterion":"sorts stably","verify":{"type":"command","value":"python3 -m pytest -q"}}]}
JSON
python3 "$GATE" validate --root "$D" --gate spec >/dev/null 2>&1; chk "$?" "0" "filled spec PASS"
python3 "$GATE" validate --root "$D" --gate done >/dev/null 2>&1; chk "$?" "1" "done BLOCKED (no evidence)"
python3 - "$D" <<'PY'
import json,sys; f=sys.argv[1]+"/.forge/spec.json"; d=json.load(open(f))
d["acceptance_criteria"][0]["evidence"]="ran pytest: 3 passed"; json.dump(d,open(f,"w"))
PY
python3 "$GATE" validate --root "$D" --gate done >/dev/null 2>&1; chk "$?" "0" "done PASS (evidence)"
echo "config/policy.py" > "$D/.forge/edits.txt"
python3 "$GATE" validate --root "$D" --gate done >/dev/null 2>&1; chk "$?" "1" "forbidden_paths edit BLOCKS done"
python3 "$GATE" close --root "$D" --force >/dev/null 2>&1; chk "$?" "1" "--force refused without FORGE_BYPASS"

echo "== 3. runtime-agnostic hook block (clean payloads) =="
python3 - "$D" "$HOOKS" >/tmp/hooks.txt 2>&1 <<'PY'
import json, os, subprocess, sys, tempfile
D, HOOKS = sys.argv[1], sys.argv[2]
env = dict(os.environ, CLAUDE_PROJECT_DIR=D, FORGE_HOME=tempfile.mkdtemp()); env.pop("FORGE_BYPASS", None)
os.makedirs(D+"/.forge", exist_ok=True)
json.dump({"grade":"STANDARD","raw_goal":"x"}, open(D+"/.forge/spec.json","w"))
open(D+"/.forge/ACTIVE","w").write("x")
def hook(h,p):
    r=subprocess.run([sys.executable,f"{HOOKS}/{h}"],input=json.dumps(p),capture_output=True,text=True,env=env)
    return r.returncode
def out(name,cond): print(f"{'PASS' if cond else 'FAIL'}|{name}")
out("CC Edit blocked", hook("pre_tool_use.py",{"tool_name":"Edit","tool_input":{"file_path":D+"/real.py"},"cwd":D})==2)
out("Codex apply_patch blocked", hook("pre_tool_use.py",{"tool_name":"apply_patch","tool_input":{"command":"*** Update File: real.py\n+x"},"cwd":D})==2)
out(".forge authoring allowed", hook("pre_tool_use.py",{"tool_name":"apply_patch","tool_input":{"command":f"*** Update File: {D}/.forge/spec.json\n+x"},"cwd":D})==0)
out("non-edit ignored", hook("pre_tool_use.py",{"tool_name":"Read","tool_input":{"file_path":D+"/real.py"},"cwd":D})==0)
open(D+"/.forge/edits.txt","w").close()
hook("post_tool_use.py",{"tool_name":"apply_patch","tool_input":{"command":"*** Update File: src/x.py\n+y"},"cwd":D})
out("PostToolUse logged path", "src/x.py" in open(D+"/.forge/edits.txt").read())
PY
while IFS='|' read -r st name; do chk "$st" "PASS" "$name"; done < /tmp/hooks.txt

echo "== 4. installer merge/uninstall roundtrip (no real config touched) =="
TS="$(mktemp -d)/settings.json"
CLAUDE_SETTINGS="$TS" sh "$FORGE/adapters/claude-code/install.sh" >/dev/null 2>&1
python3 -c "import json;c=json.load(open('$TS'));ev=c.get('hooks',{});print('OK' if all(k in ev for k in ('UserPromptSubmit','PreToolUse','PostToolUse','Stop')) else 'NO')" 2>/dev/null | grep -q OK && ok "install merges 4 events" || no "install merge"
CLAUDE_SETTINGS="$TS" sh "$FORGE/adapters/claude-code/install.sh" --uninstall >/dev/null 2>&1
python3 -c "import json;c=json.load(open('$TS'));print('OK' if not c.get('hooks') else 'NO')" 2>/dev/null | grep -q OK && ok "uninstall removes them" || no "uninstall"

echo "== 5. installer syntax =="
bash -n "$FORGE/adapters/claude-code/install.sh" && ok "CC install.sh" || no "CC install.sh"
bash -n "$FORGE/adapters/codex/install.sh" && ok "Codex install.sh" || no "Codex install.sh"
bash -n "$FORGE/adapters/codex/forge-codex.sh" && ok "forge-codex.sh" || no "forge-codex.sh"

echo "== 6. worktree-accept mechanics (no codex) =="
command -v git >/dev/null 2>&1 && {
  RR="$(mktemp -d)"; ( cd "$RR" && git init -q && git config user.email t@t && git config user.name t \
    && printf 'v1\n' > app.py && mkdir -p config && printf 'policy\n' > config/policy.py \
    && git add -A && git commit -qm base ) >/dev/null 2>&1
  BASE="$(git -C "$RR" rev-parse HEAD)"
  spec_into(){ mkdir -p "$1/.forge"; echo x > "$1/.forge/ACTIVE"; echo STANDARD > "$1/.forge/GRADE"; cat > "$1/.forge/spec.json" <<JSON
{"grade":"STANDARD","raw_goal":"add feature","restated_goal":"Add a feature module without touching config policy, scoped to feature.py.",
"non_goals":["no config changes"],"constraints":{"invariant":["config/policy.py unchanged"]},
"must_read":[{"path":"app.py","authority_reason":"owns the entry the feature joins"}],
"rejected_alternatives":[{"category":"scope","alternative":"rewrite app","broken_boundary":"over-broad"},{"category":"tempting_shortcut","alternative":"inline in config","broken_boundary":"pollutes policy"}],
"risks":[{"risk":"regress","severity":"medium","mitigation":"smoke"}],"forbidden_paths":["config/*"],
"acceptance_criteria":[{"criterion":"import","verify":{"type":"command","value":"python3 -c 'import feature'"},"evidence":"import OK"}]}
JSON
  }
  # ACCEPT: only feature.py touched
  WA="$(mktemp -d)/wt"; git -C "$RR" worktree add --detach "$WA" "$BASE" >/dev/null 2>&1
  spec_into "$WA"; printf 'def feature():\n    return 1\n' > "$WA/feature.py"
  git -C "$WA" add -A >/dev/null 2>&1
  git -C "$WA" diff --cached --name-only "$BASE" | grep -v '^\.forge/' > "$WA/.forge/edits.txt"
  python3 "$GATE" validate --root "$WA" --gate done >/dev/null 2>&1; chk "$?" "0" "accept: allowed edit passes gate"
  git -C "$WA" diff --cached --binary "$BASE" | git -C "$RR" apply --index >/dev/null 2>&1
  [ -f "$RR/feature.py" ] && ok "accept: diff applied to real repo" || no "accept: diff applied"
  git -C "$RR" worktree remove --force "$WA" >/dev/null 2>&1; git -C "$RR" reset -q --hard "$BASE" >/dev/null 2>&1
  # REJECT: forbidden config/policy.py touched
  WB="$(mktemp -d)/wt"; git -C "$RR" worktree add --detach "$WB" "$BASE" >/dev/null 2>&1
  spec_into "$WB"; printf 'def feature():\n    return 1\n' > "$WB/feature.py"; printf 'HACKED\n' > "$WB/config/policy.py"
  git -C "$WB" add -A >/dev/null 2>&1
  git -C "$WB" diff --cached --name-only "$BASE" | grep -v '^\.forge/' > "$WB/.forge/edits.txt"
  python3 "$GATE" validate --root "$WB" --gate done >/dev/null 2>&1; chk "$?" "1" "reject: forbidden edit blocks gate"
  chk "$(cat "$RR/config/policy.py")" "policy" "reject: real repo policy untouched"
  git -C "$RR" worktree remove --force "$WB" >/dev/null 2>&1
} || no "git not available for worktree test"

echo "== 7. adversarial: hook exemption over-match (clean payloads) =="
python3 - "$HOOKS" "$GATE" >/tmp/adv.txt 2>&1 <<'PY'
import json, os, subprocess, sys, tempfile
HOOKS, GATE = sys.argv[1], sys.argv[2]
D = tempfile.mkdtemp(); env = dict(os.environ, CLAUDE_PROJECT_DIR=D, FORGE_HOME=tempfile.mkdtemp()); env.pop("FORGE_BYPASS", None)
subprocess.run([sys.executable, GATE, "scaffold", "--root", D, "--goal", "add x"], capture_output=True)
def pre(p): return subprocess.run([sys.executable, f"{HOOKS}/pre_tool_use.py"], input=json.dumps(p), capture_output=True, text=True, env=env).returncode
def out(n, c): print(f"{'PASS' if c else 'FAIL'}|{n}")
# real-file edit whose patch text merely MENTIONS .forge -> must BLOCK (over-match closed)
out("over-match real-file edit blocked", pre({"tool_name": "apply_patch", "tool_input": {"command": "# note: see .forge/ later\n*** Update File: src/app.py\n+evil"}, "cwd": D}) == 2)
# pure .forge authoring -> allowed
out("pure .forge authoring allowed", pre({"tool_name": "apply_patch", "tool_input": {"command": "*** Update File: .forge/spec.json\n+{}"}, "cwd": D}) == 0)
PY
while IFS='|' read -r st name; do chk "$st" "PASS" "$name"; done < /tmp/adv.txt

echo "== 8. in-session toggle (forge off / on) =="
python3 - "$HOOKS" "$GATE" >/tmp/tog.txt 2>&1 <<'PY'
import json, os, subprocess, sys, tempfile
HOOKS, GATE = sys.argv[1], sys.argv[2]
D = tempfile.mkdtemp(); env = dict(os.environ, CLAUDE_PROJECT_DIR=D, FORGE_HOME=tempfile.mkdtemp()); env.pop("FORGE_BYPASS", None)
subprocess.run([sys.executable, GATE, "scaffold", "--root", D, "--goal", "add x"], capture_output=True)
def ups(p, sid="S1"): return subprocess.run([sys.executable, f"{HOOKS}/user_prompt_submit.py"], input=json.dumps({"prompt": p, "cwd": D, "session_id": sid}), capture_output=True, text=True, env=env).stdout
def edit_rc(sid="S1"): return subprocess.run([sys.executable, f"{HOOKS}/pre_tool_use.py"], input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": D + "/a.py"}, "cwd": D, "session_id": sid}), capture_output=True, text=True, env=env).returncode
def state():
    p = os.path.join(D, ".forge", "STATE"); return open(p).read().strip() if os.path.exists(p) else "(none)"
def out(n, c): print(f"{'PASS' if c else 'FAIL'}|{n}")
out("edit blocked before toggle", edit_rc() == 2)
o = ups("forge off"); out("forge off blocks prompt + project STATE=off", '"decision": "block"' in o and state() == "off")
out("edit allowed while off", edit_rc() == 0)
ups("forge on"); out("forge on -> project STATE=on", state() == "on")
out("edit blocked again after on", edit_rc() == 2)
ups("forge off"); ups("forge on here", "HARD")
out("session 'on here' overrides project off", edit_rc("HARD") == 2)
out("other session inherits project off", edit_rc("OTHER") == 0)
PY
while IFS='|' read -r st name; do chk "$st" "PASS" "$name"; done < /tmp/tog.txt

echo "== 9. edge cases (robustness / no-brick) =="
python3 - "$HOOKS" "$GATE" >/tmp/edge.txt 2>&1 <<'PY'
import json, os, subprocess, sys, tempfile
HOOKS, GATE = sys.argv[1], sys.argv[2]
D = tempfile.mkdtemp(); open(D + "/real.py", "w").write("x=1")
subprocess.run([sys.executable, GATE, "scaffold", "--root", D, "--goal", "add x"], capture_output=True)
env = dict(os.environ, CLAUDE_PROJECT_DIR=D, FORGE_HOME=tempfile.mkdtemp()); env.pop("FORGE_BYPASS", None)
def pre(raw, e=env): return subprocess.run([sys.executable, f"{HOOKS}/pre_tool_use.py"], input=raw, capture_output=True, text=True, env=e).returncode
def out(n, c): print(f"{'PASS' if c else 'FAIL'}|{n}")
ap = lambda *ps: json.dumps({"tool_name": "apply_patch", "tool_input": {"command": "".join(f"*** Update File: {p}\n+x\n" for p in ps)}, "cwd": D})
out("empty stdin fails open", pre("") == 0)
out("garbage stdin fails open", pre("not json") == 0)
out("no tool_input fails open (no brick)", pre(json.dumps({"tool_name": "Edit", "cwd": D})) == 0)
out("non-edit tool ignored", pre(json.dumps({"tool_name": "Read", "tool_input": {"file_path": D + "/x"}, "cwd": D})) == 0)
out("apply_patch mixed (.forge+real) blocks", pre(ap(D + "/.forge/spec.json", D + "/real.py")) == 2)
out("apply_patch only .forge allowed", pre(ap(D + "/.forge/spec.json")) == 0)
out("FORGE_BYPASS allows", pre(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": D + "/real.py"}, "cwd": D}), dict(env, FORGE_BYPASS="1")) == 0)
PY
while IFS='|' read -r st name; do chk "$st" "PASS" "$name"; done < /tmp/edge.txt

echo; echo "==== TOTAL: $PASS pass, $FAIL fail ===="
[ "$FAIL" = "0" ] || exit 1
