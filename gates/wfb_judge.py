#!/usr/bin/env python3
"""wfb_judge — the SEMANTIC quality gate (the judge layer).

The deterministic gate (wfb_gate.py) checks FORM. This scores the spec's CONTENT
against rubric/SCORECARD.md (0-2 per dimension) with an LLM judge, catching what the
gate cannot: trivial-but-runnable acceptance ('true'), generic rejected_alternatives,
a restated_goal that only paraphrases. Off the hot path — for dev / corpus promotion.
A cross-family judge (different model than the worker) is recommended to avoid bias.

Usage: wfb_judge.py --spec <spec.json> [--model gpt-5.5] [--threshold 1]
       prints per-dimension scores + verdict; exit 0 = pass, 1 = fail, 2 = error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

# validation_loop + failure_handling need RUNTIME artifacts (observations, evidence)
# that don't exist at SPEC time — so they are judged only at the DONE phase. (A
# cross-family judge comparison surfaced that scoring them pre-implementation
# unfairly fails good specs.)
SPEC_DIMS = ["goal_reframing", "context_selection", "constraint_provenance",
             "alternative_rejection", "risk", "acceptance"]
DONE_DIMS = SPEC_DIMS + ["validation_loop", "failure_handling"]

RUBRIC_LINES = {
    "goal_reframing": "0 echoes the literal ask; 1 restates intent; 2 intent + constraint envelope + real non_goals",
    "context_selection": "0 topical/none; 1 role-justified; 2 role-justified + a precedent to mirror + hazards",
    "constraint_provenance": "0 asserted/none; 1 some; 2 every constraint tiered + evidence-linked",
    "alternative_rejection": "0 none/by taste/generic; 1 a named reason; 2 category + the SPECIFIC broken boundary, path removed not guarded",
    "risk": "0 vague/'be careful'; 1 severity + mitigation; 2 blast-radius severity + a RUNNABLE mitigation mirrored to acceptance",
    "acceptance": "0 prose or trivial (e.g. 'true','echo'); 1 some runnable; 2 a real behavioral test + an artifact check, falsifiable",
    "validation_loop": "0 none; 1 one-way refs; 2 observations that revise the plan, decisions cite evidence",
    "failure_handling": "0 silent/fabricated; 1 rejects/defers; 2 fails closed + defers authority + honest carry-forward",
}


def build_prompt(spec: dict, dims) -> str:
    rub = "Score 0-2 each (0=absent/echoes/vacuous, 1=present and adequate, 2=exemplary):\n" + \
        "\n".join(f"- {d}: {RUBRIC_LINES[d]}" for d in dims)
    return (
        "You are a STRICT, skeptical senior engineering reviewer. Score this spec's "
        "CONTENT quality (not whether fields are merely present). Be harsh on lazy fills: "
        "a restated_goal that only paraphrases the ask, generic 'do it differently' rejected "
        "alternatives, 'be careful' mitigations, or trivially-passing acceptance like 'true' "
        "must score 0-1.\n\n" + rub +
        "\n\nOutput ONLY a JSON object, no prose:\n"
        '{"scores":{' + ",".join(f'"{d}":N' for d in dims) +
        '},"pass":true_or_false,"flags":["short reasons for any 0/1"]}\n'
        "pass=true ONLY if every score >= 1 AND none is a lazy fill.\n\n"
        "SPEC:\n" + json.dumps(spec, ensure_ascii=False, indent=1)
    )


def call_judge(prompt: str, model: str) -> str:
    p = subprocess.run(
        ["codex", "exec", "--json", "-s", "read-only", "--skip-git-repo-check",
         "-m", model, "-c", "model_reasoning_effort=medium", prompt],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=420,
    )
    text = ""
    for ln in (p.stdout or "").splitlines():
        ln = ln.strip()
        if not ln or ln[0] != "{":
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        it = o.get("item") or {}
        if it.get("type") == "agent_message" and it.get("text"):
            text = it["text"]
    return text


def parse_verdict(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(prog="wfb_judge")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--model", default="gpt-5.5")
    ap.add_argument("--threshold", type=int, default=1)
    ap.add_argument("--phase", choices=["spec", "done"], default="spec",
                    help="spec = 6 spec dims; done = all 8 (adds validation_loop, failure_handling)")
    a = ap.parse_args()
    dims = SPEC_DIMS if a.phase == "spec" else DONE_DIMS

    try:
        spec = json.loads(open(a.spec, encoding="utf-8").read())
    except Exception as exc:
        print(f"judge: cannot read spec: {exc}", file=sys.stderr)
        return 2

    verdict = parse_verdict(call_judge(build_prompt(spec, dims), a.model))
    scores = verdict.get("scores") or {}
    if not scores:
        print("judge: no parseable verdict from model (failing closed)", file=sys.stderr)
        return 1

    print(f"judge ({a.model}, phase={a.phase}) — semantic scores (0-2):")
    for d in dims:
        print(f"  {d:22s} {scores.get(d, '?')}")
    for f in verdict.get("flags", []):
        print(f"  flag: {f}")
    ok = all(isinstance(scores.get(d), int) and scores[d] >= a.threshold for d in dims)
    total = sum(scores.get(d, 0) for d in dims if isinstance(scores.get(d), int))
    print(f"  -> total {total}/{2*len(dims)}, verdict {'PASS' if ok else 'FAIL'} (every dim >= {a.threshold})")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"judge internal error (failing closed): {exc}", file=sys.stderr)
        raise SystemExit(1)
