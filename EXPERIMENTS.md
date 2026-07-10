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

## 2026-07-10 — DCFR average-strategy discount (γ=2) for the NLHE trainer

**Idea:** the NLHE bot trainer (`FastNLHECFR`) is CFR+ with *linear*
average-strategy weighting — each iteration `t`'s strategy contribution is added
with weight `t` (γ=1). The exact solver (`CFRSolver`/`TreeCFR`) already defaults
to Discounted CFR with γ=2, which down-weights the noisier early iterations more
aggressively and empirically sits closer to Nash at the same iteration count.
Backlog item "DCFR tuning". Ported just the γ term into the fast MCCFR trainer:
weight iteration `t` by `t ** γ`. Under end-normalisation this is *exactly*
equivalent to DCFR's per-iteration `(t/(t+1)) ** γ` discount of the accumulated
strategy sum (the common `T ** γ` factor cancels), but costs one `pow` per
iteration instead of a full node sweep. Added `gamma` to `FastNLHECFR`
(**default 1.0 = previous behaviour**, so tests, the exploiter and the push/fold
trainer are untouched) and set the bot trainer in `nlhe_metrics` to γ=2.0. Same
tree and same abstraction → **infoset count unchanged (5,772)**, so no
undertraining-from-a-bigger-model risk.

**Hypothesis:** quadratic averaging tightens the exported average strategy toward
the abstract Nash equilibrium, lowering `nlhe_exploitability_bb100` at no tree
cost.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop + 8
draw-aware post-flop buckets), same `level="standard"`, same seeds. Baseline =
current committed code (γ=1); candidate = γ=2 bot trainer only. Baseline
reproduced the committed 2026-07-01 row bit-for-bit (determinism confirmed).

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (γ=1) | Candidate (γ=2) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | 1.543 | **−1.746** (whole exploit curve shifted down uniformly, but Δ sits **inside** the routine's stated 1–2 bb/100 noise band) |
| `nlhe_infosets` | 5,772 | 5,772 | 0 (unchanged — same tree/abstraction) |
| `win_vs_random` | +63.71 (±16.47) | +67.40 (±16.20) | +3.69 |
| `win_vs_call_station` | +111.05 (±17.58) | +107.57 (±17.68) | −3.48 (within CI) |
| `win_vs_maniac` | +65.28 (±18.80) | +60.08 (±18.61) | −5.20 (within CI) |
| `win_vs_tight_aggressive` | **+8.37** (±13.90) | **−2.44** (±13.79) | **−10.81** (within CI, but flips from beating to losing TAG; 78% of its CI) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched code path) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (push/fold trainer left at γ=1) |

Candidate exploit curve `[[10000,-30.08],[25000,-19.46],[50000,-10.52],
[100000,-2.77],[150000,1.54]]` vs baseline `[...,-0.99,3.29]`: every point lower
(bot exploited less at every exploiter budget), and the endpoint stays **positive**
so the BR invariant holds. A cheap `quick`-budget A/B independently showed the
same direction (γ1 +0.42 → γ2 −2.39).

**Gate check:**
- `pytest -q` (`python -m pytest -q`) green: 31 passed.
- Invariants all hold: Kuhn/Leduc unchanged; bot still crushes
  random/call-station/maniac by wide significant margins; BR exploitability ends
  positive (+1.543 ≥ 0).
- **Primary metric:** exploitability improved by 1.746 bb/100 — real-looking
  (uniform curve shift + independent smoke test) but **within the routine's
  explicit 1–2 bb/100 noise band**, so not confidently beyond noise. The other
  primary path (`win_vs_tight_aggressive`) moved the *wrong* way.
- **Regression:** no `win_vs_*` category drops beyond its 95% CI, so no
  *statistically significant* regression — but three of four categories softened
  and TAG flipped from +8.37 to −2.44 (78% of its CI) on the flagship head-to-head.

**Verdict: NO CHANGE.** The exploitability gain is promising but sits inside the
routine's declared noise band, and it comes alongside a broad win-rate softening
(TAG flipping negative). Per the routine's "if unsure whether something is noise,
treat it as noise (don't ship)," the code change was **reverted**; only this log
entry and the (baseline) history row are committed. Worth revisiting with the
exploiter *also* on DCFR (for a tighter, more trustworthy bound) and/or more
training iterations to confirm whether the exploitability edge survives — the
`gamma` hook makes that a one-line follow-up.

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
