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

## 2026-07-05 — finer post-flop strength buckets (8 → 12)

**Idea:** backlog item #3 — refine the post-flop card abstraction from 8 to 12
equal-probability made-hand-strength buckets (`StrengthAbstraction(
postflop_buckets=12)` in `metrics.py` and `evaluate.py`). A finer strength
grid should let the bot separate hands it currently lumps together (e.g. a
strong second pair vs a weak top pair), on top of the draw feature already
shipped on 2026-07-01.

**Hypothesis:** more granular strength resolution moves the abstraction closer
to the true game, so either in-abstraction exploitability drops or head-to-head
strength (notably vs tight-aggressive) rises — the same mechanism that made the
draw-aware split a win.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop
buckets, draw-aware flop/turn split), same `level="standard"` MCCFR
training/eval budget, same seeds. Only `postflop_buckets` changed (8 → 12).
Smoke test green: `python -m pytest -q` → 31 passed; `visualize --level quick`
ran the full pipeline without error.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (8) | Candidate (12) | Δ | vs baseline 95% CI |
|---|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | 3.227 | **-0.062** | flat — far inside the 1–2 bb/100 noise band |
| `nlhe_infosets` | 5,772 | 7,644 | +32% | (expected — finer abstraction) |
| `win_vs_random` | +63.71 | +71.03 | +7.32 | within ±16.47 (z=+0.61) |
| `win_vs_call_station` | +111.05 | +101.01 | -10.04 | within ±17.58 (z=-0.79) |
| `win_vs_maniac` | +65.28 | +57.97 | -7.31 | within ±18.80 (z=-0.54) |
| `win_vs_tight_aggressive` | **+8.37** | **-5.08** | **-13.45** | within ±13.90 (z=-1.33) — but flips from beating to losing TAG |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged | untouched code path |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged | pre-flop only, unaffected |

Best-response exploitability stayed positive throughout training (BR invariant
holds): candidate curve `[-29.64, -18.44, -9.04, -1.27, 3.23]` vs baseline
`[-28.87, -17.97, -8.81, -0.99, 3.29]` — same shape, same sign at convergence.

**Gate check:**
- `pytest -q` (via `python -m pytest -q`) green: 31 passed.
- Invariants: Kuhn/Leduc untouched and unchanged; bot still crushes
  random/call-station/maniac by a wide significant margin (all CIs clear of 0);
  BR exploitability ends positive (3.227 ≥ 0). All hold.
- Primary metric: **neither path improved.** `nlhe_exploitability_bb100` moved
  only -0.062 bb/100 (inside the noise band, not a signal), and
  `win_vs_tight_aggressive` moved the *wrong* way (+8.37 → -5.08), so it did
  not rise beyond its CI.
- No formal regression: no `win_vs_*` category dropped by more than its 95% CI
  half-width (the largest drop, TAG's -13.45, sits just inside ±13.90,
  z=-1.33). But TAG flipping from a (non-significant) win to a (non-significant)
  loss, with exploitability flat, is the opposite of the hypothesised win.

**Verdict: NO CHANGE.** The primary metric did not improve beyond noise and the
one category we hoped to gain on (TAG) got worse, so the finer bucketing is not
a real, regression-free improvement. Reverted the code change (`postflop_buckets`
back to 8) and restored the committed figures; kept only the history row and this
notebook entry so the trail stays continuous. Interpretation: at the fixed
`standard` training budget, adding ~32% more info sets spreads the same MCCFR
samples thinner, and the extra strength granularity doesn't pay for itself — a
finer abstraction needs more training to fill in, which is a separate experiment.

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
