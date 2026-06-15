#!/usr/bin/env bash
# wfb-codex — phase-gated, SINGLE-SESSION wrapper around `codex exec`.
#
# Enforcement: the wrapper controls phases, so the model cannot reach IMPLEMENT
# until its spec passes the gate. Cost: this is a 3-pass structure (SPEC / IMPLEMENT /
# VERIFY as separate exec/resume turns); even single-thread it measures ~11-14x a naked
# run (TOKEN_BUDGET.md). Use it as a bootstrap / high-stakes gate, not the steady default;
# the cheaper path is the in-session hook or wfb-codex-accept.
#
#   wfb-codex "<goal>"
#   WFB_MODEL=gpt-5.5 WFB_SPEC_TRIES=4 WFB_SANDBOX=workspace-write wfb-codex "<goal>"
#   WFB_BYPASS=1 wfb-codex "<goal>"     # passthrough (ungated)
set -euo pipefail

# Resolve through symlinks (installed onto PATH as a symlink; $0 is the link, not the file).
SELF="$0"
while [ -h "$SELF" ]; do d="$(cd "$(dirname "$SELF")" && pwd)"; SELF="$(readlink "$SELF")"; case "$SELF" in /*) ;; *) SELF="$d/$SELF";; esac; done
HERE="$(cd "$(dirname "$SELF")" && pwd)"
GATE="$(cd "$HERE/../../gates" && pwd)/wfb_gate.py"
ROOT="$PWD"
GOAL="${*:-}"
MODEL="${WFB_MODEL:-gpt-5.5}"
SANDBOX="${WFB_SANDBOX:-workspace-write}"
MAXTRIES="${WFB_SPEC_TRIES:-4}"
RUNLOG="$ROOT/.wfb/codex_run.jsonl"

[ -n "$GOAL" ] || { echo "usage: wfb-codex \"<goal>\"" >&2; exit 2; }

# `codex exec` takes -s/--sandbox; `codex exec resume` does NOT (it inherits the
# session's sandbox). So first-call and resume-call option sets differ.
COMMON=(--json --skip-git-repo-check -c model="$MODEL")
[ -n "${WFB_EFFORT:-}" ] && COMMON+=(-c model_reasoning_effort="$WFB_EFFORT")
FIRST_OPTS=("${COMMON[@]}" -s "$SANDBOX")
RESUME_OPTS=("${COMMON[@]}")

if [ "${WFB_BYPASS:-}" = "1" ]; then
  echo "wfb-codex: BYPASS (ungated)" >&2
  exec codex exec --skip-git-repo-check -s "$SANDBOX" -c model="$MODEL" "$GOAL"
fi

python3 "$GATE" scaffold --root "$ROOT" --goal "$GOAL" >/dev/null
: > "$RUNLOG"
TID=""

_extract_tid() {  # read newest thread_id from RUNLOG
  python3 - "$RUNLOG" <<'PY'
import json, sys
tid = ""
for ln in open(sys.argv[1], encoding="utf-8", errors="replace"):
    ln = ln.strip()
    if not ln or ln[0] != "{":
        continue
    try:
        o = json.loads(ln)
    except Exception:
        continue
    if o.get("type") == "thread.started" and o.get("thread_id"):
        tid = o["thread_id"]
print(tid)
PY
}

codex_first() {  # $1 = prompt
  codex exec "${FIRST_OPTS[@]}" "$1" < /dev/null >> "$RUNLOG" 2>/dev/null || true
  TID="$(_extract_tid)"
}
codex_resume() {  # $1 = prompt ; continues the same thread (context retained)
  if [ -n "$TID" ]; then
    codex exec resume "${RESUME_OPTS[@]}" "$TID" "$1" < /dev/null >> "$RUNLOG" 2>/dev/null || true
  else
    codex exec resume "${RESUME_OPTS[@]}" --last "$1" < /dev/null >> "$RUNLOG" 2>/dev/null || true
  fi
}

read -r -d '' SPEC_SKELETON <<'JSON' || true
{
  "grade": "STANDARD",
  "restated_goal": "<intent + constraint envelope: 'achieve X without Y, scoped to Z' — NOT the raw ask verbatim>",
  "non_goals": ["<the over-broad version you are NOT doing>"],
  "must_read": [{"path": "<a REAL file path you read, or set external:true>", "authority_reason": "<the contract/boundary it owns>"}],
  "constraints": {"invariant": ["<what must NOT change>"]},
  "rejected_alternatives": [
    {"category": "<scope|architecture|tempting_shortcut|compatibility|or any apt label>", "alternative": "<the option>", "broken_boundary": "<the principle/cost it violates>"},
    {"category": "...", "alternative": "...", "broken_boundary": "..."}
  ],
  "risks": [{"risk": "<risk>", "severity": "<low|medium|high|blocking>", "mitigation": "<a runnable check>", "acceptance_ref": "<criterion id, required if high/blocking>"}],
  "acceptance_criteria": [{"criterion": "<what done means>", "verify": {"type": "command", "value": "<a runnable command>"}}]
}
JSON

# ---------------------------------------------------------------- SPEC phase ---
spec_ok=0
for try in $(seq 1 "$MAXTRIES"); do
  if [ "$try" = "1" ]; then
    codex_first "Engineering task: ${GOAL}

Produce ONLY the SPEC and WRITE it to .wfb/spec.json (overwrite). Do NOT edit or
create any other file; do NOT write implementation code yet. Use EXACTLY this JSON
shape — keep these key names and nesting, fill the <...> placeholders:
${SPEC_SKELETON}"
  else
    errs="$(python3 "$GATE" validate --root "$ROOT" --gate spec 2>&1 || true)"
    codex_resume "Your .wfb/spec.json FAILED the gate. Rewrite ONLY that file, fixing EXACTLY:
${errs}"
  fi
  if python3 "$GATE" validate --root "$ROOT" --gate spec; then
    spec_ok=1; echo "wfb-codex: SPEC gate PASS (try $try, thread ${TID:-last})"; break
  fi
done
[ "$spec_ok" = "1" ] || { echo "wfb-codex: SPEC gate still failing after ${MAXTRIES} tries — abort (fail closed)." >&2; exit 1; }

# ----------------------------------------------------------- IMPLEMENT phase ---
codex_resume "Now IMPLEMENT the task per .wfb/spec.json. Respect its non_goals and
invariants; make the smallest change that satisfies acceptance_criteria. If a read
reveals new scope, update .wfb/spec.json first. Do not weaken any check to pass."

# -------------------------------------------------------------- VERIFY phase ---
codex_resume "VERIFY: run each acceptance_criteria command in .wfb/spec.json and write
its live output into that criterion's \"evidence\" field, then save. Do not fabricate
output; if a step needs human/credentials/destructive action, write that in evidence."

if python3 "$GATE" validate --root "$ROOT" --gate done; then
  python3 "$GATE" close --root "$ROOT"
  echo "wfb-codex: DONE — done gate passed, evidence recorded."
else
  echo "wfb-codex: VERIFY incomplete — done gate unmet (above). Task left open (fail closed)." >&2
  exit 1
fi
