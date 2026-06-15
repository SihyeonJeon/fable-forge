# The judge layer (semantic gate)

The deterministic gate (`gates/wfb_gate.py`) checks **form** — fields present,
well-typed, non-empty, paths real, no forbidden edits. It cannot tell a thoughtful
spec from a form-valid but lazy one: a `restated_goal` that only paraphrases, a
generic "do it differently" rejected_alternative, a `"be careful"` mitigation, or a
trivially-passing `acceptance.verify.value: "true"` all pass the gate.

`gates/wfb_judge.py` is the **semantic** gate: an LLM scores the spec's *content*
against `rubric/SCORECARD.md` (0–2 per dimension). It is **off the hot path** — a real
model call, for HEAVY tasks / corpus promotion, not every edit.

```sh
wfb_judge.py --spec .wfb/spec.json --phase spec --model gpt-5.5   # 6 spec dims
wfb_judge.py --spec .wfb/spec.json --phase done --model gpt-5.5   # + validation_loop, failure_handling
# exit 0 = pass (every active dim >= 1), 1 = fail
```

## Phase-aware (a flaw the cross-family check caught)

`validation_loop` and `failure_handling` need **runtime artifacts** (observations,
live evidence) that don't exist at SPEC time. Judging a spec on them unfairly fails
good specs. So the judge scores **6 dims at `--phase spec`**, all **8 at `--phase
done`** (where the evidence exists).

This flaw was surfaced by judging with **two model families** and seeing them
diverge — a single judge would have masked it.

## Demonstration (measured)

Two specs, both **passing the deterministic gate** (identical form), differing only
in content quality:

| | det. gate | judge gpt-5.5 (spec) | judge Claude (spec) |
| --- | --- | --- | --- |
| GOOD (real constraint envelope, specific rejected alts, pytest acceptance) | PASS | **8/12 PASS** | **10/12 PASS** |
| GAMED (paraphrase goal, generic alts, "be careful", `verify:"true"`) | PASS | **0/12 FAIL** | **1/12 FAIL** |

**Cross-family consensus:** both judges pass GOOD and fail GAMED. Every GAMED
penalty lands exactly where the deterministic gate was blind — the trivial command,
the generic alternatives, the vacuous mitigation.

## Honest limits of the judge

- It is an LLM: **non-deterministic and fallible.** Mitigate with a **cross-family**
  judge (model ≠ the worker's), a threshold (every dim ≥ 1), and 2–3 votes for
  high-stakes.
- **Same-family bias:** judging gpt-5.5's work with a gpt-5.5 judge flatters it. Use
  a different family (here, Claude) as the second judge.
- It scores the spec's *reasoning*, still not the *code's correctness* — that is the
  acceptance commands' job (run them), and the hidden-grader benchmark
  (`bench/BENCHMARK.md`).

## Where it fits

```
work prompt
  -> wfb_gate (FORM, deterministic, free, every task)         [block edits until spec valid]
  -> wfb_judge (SEMANTICS, LLM, HEAVY/corpus only)            [reject shallow-but-valid specs]
  -> acceptance commands (CORRECTNESS, run the tests)           [does the code actually work]
```
Three layers, increasing cost and depth: shape → reasoning quality → real behavior.
