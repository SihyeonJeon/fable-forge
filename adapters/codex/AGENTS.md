# Engineering procedure (mandatory)

This session runs under a gated engineering procedure. Follow SPEC → IMPLEMENT →
VERIFY. Do not write implementation code until the SPEC passes its gate.

**SPEC** — before editing any code, write `.wfb/spec.json` (schema:
`wfb/adapters/codex/spec.schema.json`) with:
- `restated_goal` — intent + constraint envelope ("achieve X without violating Y,
  scoped to Z"), never the raw ask verbatim
- `non_goals` — the over-broad version you are NOT doing
- `must_read` — files chosen by **authority** (the contract/boundary each owns),
  with reasons; not by topic
- `constraints` — architectural / invariant / convention
- `rejected_alternatives` — ≥2, each a category + the boundary it breaks; prefer
  removing a failure path over guarding it
- `risks` — **≥1** (not 'none'), each severity by **blast radius** + runnable
  mitigation, high risks mirrored into acceptance
- `acceptance_criteria` — runnable commands, not prose

Then run: `python3 <wfb>/gates/wfb_gate.py validate --root "$PWD" --gate spec`
and fix every reported item before continuing.

**IMPLEMENT** — smallest change respecting the invariants and non_goals. New scope
mid-task → update the spec. Fix the system, never weaken a check to pass it.

**VERIFY** — run each acceptance criterion, write its live output into that
criterion's `evidence` field. No evidence → not done (fail closed). Surface
destructive / manual steps; never fabricate output. Under delegation: no
self-approval — an independent check produces the evidence.

Then: `python3 <wfb>/gates/wfb_gate.py validate --root "$PWD" --gate done`.

Do not narrate this procedure to the user; just follow it.
