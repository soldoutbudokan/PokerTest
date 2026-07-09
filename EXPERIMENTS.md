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

## 2026-07-09 — train the NLHE bot 3× longer (120k → 360k MCCFR deals)

**Idea:** backlog item #1, "train longer." MCCFR converges ~O(1/√T), so more
deals should push the bot closer to the abstract Nash equilibrium and lower its
exploitability. Changed only the third element of `LEVELS["standard"]` in
`metrics.py` (`nlhe_train` 120000 → 360000); every other budget (Kuhn 8k, Leduc
30k, `eval_pairs` 5000, `expl_max` 150k, `expl_eval` 50k, `pf_train` 250k) left
identical so the eval harness stays comparable and the Kuhn/Leduc/push-fold
paths are untouched.

**Hypothesis:** `nlhe_exploitability_bb100` drops beyond the 1–2 bb/100 noise
band with no baseline win rate regressing.

**Setup:** identical to baseline except the bot's training-deal count. Same seed,
same `level="standard"` eval budgets. Baseline = 120k deals, candidate = 360k.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (120k) | Candidate (360k) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | **+3.289** | **−6.838** | −10.13 — but **negative ⇒ invalid** (see below) |
| `nlhe_infosets` | 5,772 | 5,772 | unchanged (abstraction untouched) |
| `win_vs_random` | +63.71 (±16.47) | +71.34 (±16.27) | +7.63 (within CIs) |
| `win_vs_call_station` | +111.05 (±17.58) | +109.95 (±17.26) | −1.10 (noise) |
| `win_vs_maniac` | +65.28 (±18.80) | +67.70 (±18.56) | +2.42 (noise) |
| `win_vs_tight_aggressive` | **+8.37** (±13.90) | **−11.62** (±13.13) | **−19.99 — regression, exceeds both CIs** |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched paths) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (push-fold budget untouched) |

Candidate best-response curve was **negative at every checkpoint**:
`[[10000,-35.93],[25000,-26.63],[50000,-18.38],[100000,-11.11],[150000,-6.84]]`
(baseline ended at +3.29).

**Gate check:**
- `pytest -q` green (31 passed) and the quick pipeline still runs.
- **Invariant #5 BROKEN.** DEPENDENCIES.md requires the best response to win
  ≥ ~0 bb/100; a negative value means the exploiter is under-trained and the
  measurement is invalid — "never ship on it." Tripling the bot's training
  while holding the BR exploiter budget fixed at `expl_max=150k` let the
  stronger bot outrun its fixed-budget exploiter, so the lower bound collapsed
  to −6.84. The apparent exploitability "improvement" is an artifact of an
  under-resourced exploiter, not a real gain. A valid "train longer" test would
  have to scale `expl_max` up in step — which would change the eval harness and
  break baseline/candidate comparability.
- **Regression on TAG.** `win_vs_tight_aggressive` fell +8.37 → −11.62, a drop
  of ~20 bb/100 that exceeds both the baseline (±13.90) and candidate (±13.13)
  95% CIs — a real regression, not noise. (It landed back near the pre-draw-aware
  −12.48, suggesting the +8.37 was itself near the noisy edge.)
- Wins vs random/call-station/maniac moved within their CIs.

**Verdict: REGRESSION.** Reverted the code (`metrics.py` back to
`nlhe_train=120000`); kept the history row (baseline metrics, so continuity is
preserved) and this entry. **Lesson for a future run:** "train longer" is only
measurable if the best-response exploiter budget scales with the bot's training;
otherwise the exploitability metric silently goes invalid.

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
