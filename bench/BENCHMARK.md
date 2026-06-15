# Quality benchmark — gate ON vs OFF

Question: does forcing the spec+verify discipline (the wfb gate) lift a model's
**output correctness** — i.e., does a weaker model + the layer reach a stronger
model's quality? (The token-cost side is in `../TOKEN_BUDGET.md`.)

## Method

- 3 tasks with a **hidden grader** (`quality/grade.py`) — edge cases the model
  never sees: `slugify` (collapse/strip/empty/case), `parse_duration` (valid combos
  + invalid-must-raise), `is_prime` ("optimize" while preserving n<2/negative edges).
- Grader validated to discriminate: a good `slugify` scores 10/10, a naive one 3/10;
  a good `is_prime` 10/10, the classic `i*i<=n` (no `n<2` guard) 7/10.
- Two arms, SAME task: **naked** (`codex exec`) vs **wfbd** (`wfb-codex-accept`,
  worktree + gate). Score = hidden assertions passed / total. The wfbd arm's
  produced module is graded (gate engaged: tasks B/C logged `ACCEPTED`).

## Results

| task | symbol | naked | wfbd (gate) |
| --- | --- | --- | --- |
| A | slugify | 10/10 | 10/10 |
| B | parse_duration | 10/10 | 10/10 |
| C | is_prime (preserve edges) | 10/10 | 10/10 |

Run on **gpt-5.5** AND on the weaker **gpt-5.4-mini** — identical: **10/10 on every
task, both arms, both models.**

## Honest conclusion

**No measurable quality lift on these tasks.** Both a strong model (gpt-5.5) and a
weak one (gpt-5.4-mini) already produce fully-correct, edge-case-complete code
*naked*, so the gate has nothing to add.

This is consistent with everything else measured: **the wfb layer enforces
*process*, not *capability*.** It does not inject intelligence. Its demonstrated
value is enforcement (no unspeced/forbidden work reaches the repo), evidence, and
auditability — not making a weaker model smarter on tasks it can already do.

Where a lift *could* appear, and why it didn't here:
- The only place forcing a spec+tests helps correctness is when a model is
  **capable but lazy** — it would write a subtle bug naked (skipping tests) but
  catches it once the gate forces "run your acceptance criteria." These tasks were
  simple enough that even the naked weak model wrote no bug to catch.
- A discriminating benchmark needs **bug-prone tasks at the edge of competence**
  (subtle off-by-one / state / concurrency / spec-ambiguity) where naked output is
  plausibly-wrong. Constructing those with objective hidden graders is the open
  follow-up. The honest prior: any lift is modest and task-specific, not a general
  "weak model → strong model" multiplier.

## Reproduce

```sh
WFB_MODEL=gpt-5.4-mini WFB_EFFORT=medium bash bench/run_quality.sh
```
