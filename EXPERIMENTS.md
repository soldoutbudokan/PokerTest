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

## 2026-07-15 — more post-flop strength buckets (8 → 12)

**Idea:** finer post-flop card abstraction. The `StrengthAbstraction` splits
made-hand strength into `postflop_buckets` per street (currently 8, times the
draw feature added 2026-07-01). Backlog item #3: raise it to 12 so nearby
hand strengths stop sharing a bucket, in the hope of lower abstraction error
(→ lower exploitability) and/or sharper play. Single-variable change:
`StrengthAbstraction(postflop_buckets=8)` → `12` in `metrics.py:nlhe_metrics`.
This only enlarges the card abstraction (info-set keys), **not** the betting
tree, so per-deal traversal cost — and the MCCFR/BR training budget — is
unchanged; the comparison is apples-to-apples at the same `standard` level.

**Hypothesis:** finer strength resolution reduces the abstraction gap and
should lower `nlhe_exploitability_bb100` (or at least not hurt), possibly
helping vs tight-aggressive.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop
buckets, draw-aware, MCCFR `level="standard"`, seed 0) except
`postflop_buckets=12`. Baseline and candidate both computed at `standard`.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (8) | Candidate (12) | Δ | 95% CI (cand) |
|---|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | 3.227 | **−0.06** (flat — well inside the 1–2 bb/100 noise band) | — |
| `nlhe_infosets` | 5,772 | 7,644 | +32% (expected — finer abstraction) | — |
| `win_vs_random` | +63.71 | +71.03 | +7.32 | ±16.50 (sig) |
| `win_vs_call_station` | +111.05 | +101.01 | −10.04 (within CI) | ±17.69 (sig) |
| `win_vs_maniac` | +65.28 | +57.97 | −7.31 (within CI) | ±18.77 (sig) |
| `win_vs_tight_aggressive` | **+8.37** (±13.90) | **−5.08** (±14.07) | **−13.45** — right at the CI boundary; flips from (non-sig) beating TAG to (non-sig) losing | ±14.07 (not sig) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched path) | — |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (preflop-only, no post-flop buckets) | — |

Best-response exploitability stayed positive throughout (BR invariant holds):
candidate curve `[[10000,-29.64],[25000,-18.44],[50000,-9.04],[100000,-1.27],
[150000,3.23]]` — same shape and sign as baseline's, ending +3.23 ≥ 0.

**Gate check:**
- `pytest -q` (via `python -m pytest -q`, see 2026-07-01 note) green: 31 passed.
- Invariants: Kuhn/Leduc unchanged; bot still crushes
  random/call-station/maniac by a wide **significant** margin; BR ends
  positive (3.227 ≥ 0); push/fold unchanged. All hold.
- Primary metric: **fails.** `nlhe_exploitability_bb100` moved −0.06 bb/100
  (noise, not the hoped-for drop), and `win_vs_tight_aggressive` moved the
  *wrong* way by 13.45 bb/100 (right at its ~14 bb/100 CI). Neither primary
  metric improved beyond noise.
- Regression: no single `win_vs_*` category dropped by *more* than its 95% CI
  (TAG −13.45 vs ±13.90–14.07 sits on the boundary; call-station −10.04 and
  maniac −7.31 are inside their wider CIs), so not a hard regression — but the
  finer buckets clearly bought nothing: at fixed 120k training the extra 1,872
  info sets are more thinly trained, and the added resolution is washed out by
  MCCFR + evaluation noise.

**Verdict: NO CHANGE.** Reverted the code (`postflop_buckets` stays 8);
appended today's history row with the **unchanged** baseline metrics so the
trail stays continuous. The shipped bot is unchanged. If revisited, this
change likely needs a larger training budget to pay off (more buckets ⇒ more
info sets ⇒ under-trained at the current deal count).

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
