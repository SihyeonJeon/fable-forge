<!-- wfb: paste into a project's CLAUDE.md (or ~/.claude/CLAUDE.md for all
projects) so the procedure rides in context alongside the hard gate. Optional —
the hooks enforce regardless; this just makes the model fluent in what the gate
expects, reducing block round-trips. -->

## Engineering procedure (enforced by wfb)

Work-shaped prompts auto-start a gated task. You **cannot edit implementation
files until `.wfb/spec.json` passes the SPEC gate.** Follow SPEC → IMPLEMENT →
VERIFY:

- **SPEC** — write `.wfb/spec.json`: `restated_goal` (intent + constraint
  envelope, never the raw ask verbatim), `non_goals`, `must_read` (files chosen by
  authority + reason), `constraints` (architectural/invariant/convention),
  `rejected_alternatives` (≥2: category + the boundary each breaks; remove a path,
  don't guard it), `risks` (≥1, not 'none'; severity by blast radius + runnable
  mitigation; mirror high risks into acceptance), `acceptance_criteria` (runnable commands, not prose).
- **IMPLEMENT** — smallest change respecting invariants. New scope mid-task →
  update the spec. Fix the system, never weaken a check to pass it.
- **VERIFY** — run every acceptance criterion, record live `evidence`. No evidence
  → not done (fail closed). Surface destructive/manual steps; never fake them. No
  self-approval under delegation.

Full text: `wfb/prompts/FABLE_PROCEDURE.md`. Do not narrate the procedure
to the user; just follow it.
