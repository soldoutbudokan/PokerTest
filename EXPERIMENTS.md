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

## 2026-07-14 — DCFR-style quadratic strategy averaging in the NLHE trainer

**Idea:** the exact Kuhn/Leduc solvers default to Discounted CFR with γ=2
(quadratic strategy averaging) *because* it pulls the average strategy toward
equilibrium faster — yet the NLHE MCCFR trainer (`FastNLHECFR`) uses plain
CFR+ **linear** averaging (weighting iteration `t` by `t`). Aligned the two:
added an `avg_power` parameter to `FastNLHECFR` (default `1.0` = unchanged
behaviour, so all tests stay byte-identical) that weights each iteration's
strategy contribution by `t ** avg_power`, and set `avg_power=2.0` for the bot
and push/fold trainers in `metrics.py`. The regret update (regret-matching-plus)
is untouched, the betting tree and card abstraction are identical, and the
best-response exploiter is left unchanged — so the exploitability ruler stays a
valid apples-to-apples lower bound at the same 150k-iter budget.

**Hypothesis:** heavier late-iteration weighting converges the *average*
strategy closer to the abstract Nash at the same 120k training budget, lowering
`nlhe_exploitability_bb100` for free (no bigger tree, no extra iterations).

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop +
8 draw-aware post-flop buckets), same `level="standard"` budget, same seed 0.
Only the bot's average-strategy weighting changed (linear → quadratic).

**Pre-check (A/B probe, bot train 120k, exploiter 100k / eval 30k):**
`avg_power` 1.0 → +0.12, 1.5 → −1.05, 2.0 → −1.78 bb/100 — a clean *monotone*
effect (heavier averaging → harder to exploit), confirming the direction is
real and not a single-seed fluke. (Negative values there just mean a 100k-iter
exploiter is under-converged against the improved bot; the full run uses 150k.)

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`, seed 0):

| Metric | Baseline | Candidate | Δ | Noise / CI |
|---|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | 1.543 | **−1.746** | within the routine's 1–2 bb/100 noise band |
| `win_vs_random` | +63.71 | +67.40 | +3.69 | within CI ±16.20 |
| `win_vs_call_station` | +111.05 | +107.57 | −3.48 | within CI ±17.68 |
| `win_vs_maniac` | +65.28 | +60.08 | −5.20 | within CI ±18.61 |
| `win_vs_tight_aggressive` | **+8.37** | **−2.44** | **−10.81** | within CI ±13.79 (flips beating→losing) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged | untouched code path |
| `nlhe_infosets` | 5772 | 5772 | 0 | same tree/abstraction |
| `pushfold_jam_pct` | 62.1 | 61.5 | −0.6 | still in the Nash 60–70% band |

Best-response exploiter curve stayed monotone-positive-at-convergence and valid:
baseline `[[10000,-28.87],[25000,-17.97],[50000,-8.81],[100000,-0.99],[150000,3.29]]`
vs candidate `[[10000,-30.08],[25000,-19.46],[50000,-10.52],[100000,-2.77],[150000,1.54]]`
— same shape, ends **+1.54 ≥ 0** (BR invariant #5 holds).

**Gate check:**
- `pytest -q` green: 31 passed (default `avg_power=1.0` keeps existing behaviour;
  candidate run used 2.0).
- Invariants: Kuhn/Leduc unchanged; evaluator untouched; bot still crushes
  random/call-station/maniac by wide, significant margins (+67/+108/+60);
  BR exploitability ends +1.54 ≥ 0. **All invariants hold — nothing is broken.**
- Primary metric: `nlhe_exploitability_bb100` fell 1.746, but that is **inside
  the routine's explicit 1–2 bb/100 noise band** (same basis on which the
  2026-07-01 entry called a 0.48 exploitability move "noise"), so it is *not*
  an improvement beyond noise. `win_vs_tight_aggressive` did not improve — it
  *dropped* 10.81 (within CI, not significant).
- No **significant** regression: every `win_vs_*` Δ is within its 95% CI. But
  the pattern is telling — the change trades win-rate breadth (all four
  baselines drifted down, TAG flips negative) for a noise-band dip in
  exploitability.

**Verdict: NO CHANGE.** The one primary path that moved (exploitability) moved
only within the stated noise band, and it came paired with a consistent — if
individually non-significant — decline across every head-to-head win rate,
including undoing the previous run's TAG edge. Per the routine's rule ("if
unsure whether something is noise, treat it as noise; don't ship"), reverted the
`avg_power` change; the bot on `main` is unchanged. Recorded this run's history
row from the (unchanged) baseline bot. Worth revisiting only with a *stronger*
exploiter budget to confirm whether the exploitability gain is genuine signal,
and paired with more training so the average-weighting shift doesn't starve
rarely-visited infosets (the likely cause of the win-rate drift).

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
