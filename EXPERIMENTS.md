# Experiments log

The daily improvement routine (`routines/daily_improvement.md`) appends one
entry per run. Newest first. Each entry: what was tried, the hypothesis, the
before→after objective metrics, and the verdict (IMPROVEMENT / NO CHANGE /
REGRESSION).

Metrics legend (all from `pokerbot.metrics.flatten`):
- `kuhn_exploitability`, `leduc_exploitability` — solver sanity (must stay low).
- `nlhe_exploitability_bb100` — best-response lower bound (lower = better).
- `win_vs_*` — bot win rate vs each baseline, bb/100 (higher = better).
- `pushfold_jam_pct` — 10 BB SB jam range (Nash ≈ 60–70%).

---

## 2026-07-08 — train the NLHE bot longer (120k → 300k MCCFR deals)

**Idea:** backlog #1. MCCFR converges ~O(1/√T), so training the bot on more
sampled deals should push it closer to the abstract Nash equilibrium and lower
its exploitability. Bumped `LEVELS["standard"]` `nlhe_train` 120,000 → 300,000
(2.5×), and `LEVELS["full"]` 250k → 600k to preserve level ordering. Deliberately
kept a **single variable**: the best-response budget (`expl_max=150000`),
eval pairs, and push/fold training were all left unchanged so any move in the
metric is attributable to bot training alone.

**Hypothesis:** a more-converged bot is less exploitable, so
`nlhe_exploitability_bb100` should fall (below the baseline 3.289) while the
wide win-rate margins vs random/call-station/maniac hold.

**Setup:** identical to baseline except bot training deals (heads-up 20 BB,
pot + all-in, 169 pre-flop + 8 draw-aware post-flop buckets), `level="standard"`,
same seed. Baseline computed on the committed 120k code, candidate on the 300k
code; both at `standard`. Candidate training/eval took ~774s.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (120k) | Candidate (300k) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | **+3.289** | **−5.367** | −8.66 — but **negative = invariant #5 broken** (see below) |
| `nlhe_infosets` | 5,772 | 5,772 | unchanged (same abstraction) |
| `win_vs_random` | +63.71 (CI 16.47) | +83.41 (CI 16.62) | +19.70 |
| `win_vs_call_station` | +111.05 (CI 17.58) | +102.43 (CI 17.28) | −8.62 (within CI, still crushes) |
| `win_vs_maniac` | +65.28 (CI 18.80) | +64.22 (CI 18.72) | −1.06 (noise) |
| `win_vs_tight_aggressive` | **+8.37** (CI 13.90) | **−5.41** (CI 13.14) | **−13.77** ≈ its 95% CI — flips from beating to losing TAG |
| `kuhn` / `leduc` exploitability | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (solver untouched) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged |

Best-response curve (BR iters → bb/100), baseline vs candidate — the **whole
curve shifted down**:
`10k: -28.9→-35.0 · 25k: -18.0→-25.5 · 50k: -8.8→-17.0 · 100k: -1.0→-9.7 ·
150k: +3.29→-5.37`.

**Gate check — FAILS:**
- `pytest -q` green (31 passed) and Kuhn/Leduc invariants unchanged. ✅
- **Invariant #5 BROKEN:** the best response ends at **−5.367 bb/100 < 0**.
  DEPENDENCIES.md: "A best response to the bot must be ≥ ~0 bb/100 (a negative
  number means the exploiter is under-trained or the measurement is wrong —
  never ship on it)." The apparent exploitability "improvement" is a
  **measurement artifact**: holding the BR budget at 150k while the bot trained
  2.5× longer left the exploiter under-trained relative to the now-stronger bot,
  so it can no longer even break even. This is not a genuine reduction in true
  exploitability — the number is simply no longer a valid lower bound.
- **Regression:** `win_vs_tight_aggressive` dropped 13.77 bb/100 (≈ its 95% CI),
  flipping from +8.37 to −5.41 — the wrong direction for the secondary gate
  metric.

**Verdict: NO CHANGE (REGRESSION).** Reverted the `LEVELS` change; kept the
history row + this note. A real exploitability gain from longer training would
require scaling the best-response budget (`expl_max`) in lock-step so the metric
stays a valid ≥0 lower bound — but that is a second, confounded variable, out of
scope for a one-idea run. Worth revisiting as a paired "train bot **and**
exploiter longer" experiment.

**Environment note:** as in prior runs, bare `pytest -q` fails collection
(`ModuleNotFoundError: pokerbot`) because the console script omits cwd from
`sys.path`; `python -m pytest -q` passes cleanly (31). Not a code regression.

---

## 2026-07-01 — draw-aware post-flop abstraction

**Idea:** the post-flop abstraction (`StrengthAbstraction`) only bucketed
made-hand strength, so a middle pair with a flush draw looked identical to a
dead middle pair. Added a redraw-potential feature (`_draw_feature` in
`nlhe_abstraction.py`): on the flop/turn only, classify 0 = no redraw, 1 =
weak (backdoor flush / gutshot), 2 = strong (made flush draw or open-ended
straight draw), and fold that into the bucket key as `(street, strength_bucket,
draw_feature)`. River is untouched (no more cards to draw to, so the feature
carries no signal there — added it anyway it would just fragment buckets for
nothing). `draw_aware=True` is now the default on `StrengthAbstraction`;
`metrics.py`/`evaluate.py` didn't need changes since they call it with just
`postflop_buckets=8`.

**Hypothesis:** this was flagged in the 2026-06-30 backlog as the most likely
real strength win, since made-hand-strength-only abstraction is documented as
draw-blind.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop
buckets, 8 post-flop strength buckets **now split by draw feature on
flop/turn**), same `level="standard"` MCCFR training/eval budget, same seed.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline | Candidate | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 2.805 | 3.289 | +0.484 (within the routine's stated 1–2 bb/100 noise band) |
| `nlhe_infosets` | 3,980 | 5,772 | +45% (expected — bigger abstraction) |
| `win_vs_random` | +50.57 | +63.71 | +13.14 |
| `win_vs_call_station` | +101.94 | +111.05 | +9.11 |
| `win_vs_maniac` | +60.00 | +65.28 | +5.28 |
| `win_vs_tight_aggressive` | **-12.48** (CI ±13.92, not significant) | **+8.37** (CI ±13.90, not significant) | **+20.85** — bigger than either side's 95% CI half-width; the bot flips from (non-significantly) losing to (non-significantly) beating TAG |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched code path — confirms determinism/isolation) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (push/fold is preflop-only, unaffected by a post-flop abstraction change) |

Best-response exploitability stayed positive throughout training
(BR invariant holds: `[[10000,-28.87],[25000,-17.97],[50000,-8.81],
[100000,-0.99],[150000,3.29]]` vs baseline's near-identical curve — same
shape, same sign at convergence).

**Gate check:**
- `pytest -q` (via `python -m pytest -q`, see note below) green: 31 passed.
- Invariants: Kuhn/Leduc untouched and unchanged; bot still crushes
  random/call-station/maniac by a wide significant margin (all improved);
  BR exploitability ends positive (3.289 ≥ 0).
- Primary metric: `win_vs_tight_aggressive` improved by 20.85 bb/100, more
  than either baseline's or candidate's 95% CI half-width (~13.9) — a real
  swing, not noise (two-sample z ≈ 2.1). `nlhe_exploitability_bb100` moved
  the wrong direction but by 0.48 bb/100, inside the routine's explicit
  noise band.
- No regression: every `win_vs_*` category improved or held; no category
  dropped.

**Environment note:** in this sandbox, the bare `pytest -q` command from the
routine fails all collection with `ModuleNotFoundError: No module named
'pokerbot'` because the plain `pytest` console script doesn't put the cwd on
`sys.path`; `python -m pytest -q` (which does) passes cleanly. Not a code
regression — just how this runner invokes the interpreter.

**Verdict: IMPROVEMENT.** Kept the change (`draw_aware=True` default in
`StrengthAbstraction`), regenerated `EVALUATION.md` and `figures/` at
`level=standard`, and committed to `main`.

---

## 2026-06-30 — baseline established (initial bot)

**Idea:** none yet — record the starting point so future runs have something to
beat.

**Setup:** heads-up 20 BB, pot-sized bets + all-in, 169 pre-flop + 8 post-flop
strength buckets, chance-sampling MCCFR.

**Baseline metrics:** see the first row of `metrics_history.csv` and
`EVALUATION.md`. Headline: bot beats random/call-station/maniac by +60 to +90
bb/100 (significant), ties tight-aggressive (within CI), best-response
exploitability lower bound a few bb/100, push/fold range ≈ 62% (matches Nash).

**Known weaknesses to attack (the backlog):**
- Post-flop abstraction is **draw-blind** (made-hand strength only) — likely the
  biggest strength leak; a draw-aware bucket is the highest-value experiment.
- Single bet size (pot) — adding 0.5-pot may help.
- Pre-flop play is limp-heavy; deeper stacks would give more room vs TAG.

**Verdict:** BASELINE.
