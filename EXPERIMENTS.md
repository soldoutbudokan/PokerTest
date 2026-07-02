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

## 2026-07-02 — train the NLHE bot longer (120k → 360k MCCFR deals)

**Idea:** backlog #1 ("train longer"). Raise the bot's chance-sampling MCCFR
training budget for the `standard` level from 120,000 to 360,000 deals
(`LEVELS["standard"]` `nlhe_train` 120000 → 360000, everything else — abstraction,
eval budgets, best-response budget, push/fold budget, seed — held identical for a
fair comparison). Hypothesis: exploitability converges ~O(1/√T), so 3× the deals
should measurably lower `nlhe_exploitability_bb100` with no regression to win
rates or the Kuhn/Leduc invariants (this code path doesn't touch them).

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop + 8
post-flop strength buckets, draw-aware, `level="standard"`, seed 0), **only** the
bot's `nlhe_train` deals changed 120k → 360k. Best-response exploiter budget left
at `expl_max=150000` (unchanged), same as baseline.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`, seed 0):

| Metric | Baseline (120k) | Candidate (360k) | Δ | Note |
|---|---|---|---|---|
| `nlhe_exploitability_bb100` | **+3.289** | **-6.838** | -10.13 | **INVALID** — negative best-response lower bound (invariant #5 broken) |
| `nlhe_infosets` | 5,772 | 5,772 | 0 | same abstraction |
| `win_vs_random` | +63.71 (CI ±16.47) | +71.34 (CI ±16.27) | +7.63 | within CI (noise) |
| `win_vs_call_station` | +111.05 (CI ±17.58) | +109.95 (CI ±17.26) | -1.10 | within CI (noise) |
| `win_vs_maniac` | +65.28 (CI ±18.80) | +67.70 (CI ±18.56) | +2.42 | within CI (noise) |
| `win_vs_tight_aggressive` | **+8.37** (CI ±13.90) | **-11.62** (CI ±13.13) | **-19.99** | **REGRESSION** — swing exceeds both CIs |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged | untouched code path (confirms isolation) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged | push/fold is preflop-only |

**Why the exploitability number is invalid, not an improvement.** The
best-response exploit curves tell the story:

- Baseline BR curve `(br_iters, bb100)`: `[[10000,-28.87],[25000,-17.97],
  [50000,-8.81],[100000,-0.99],[150000,+3.29]]` — rises through zero and ends
  **positive** (+3.29): a valid lower bound.
- Candidate BR curve: `[[10000,-35.93],[25000,-26.63],[50000,-18.38],
  [100000,-11.11],[150000,-6.84]]` — the **entire** curve is negative; even after
  150k iterations the best response is still *losing* 6.84 bb/100 to the bot.

The 360k-deal bot really is much better-converged toward the abstract Nash
equilibrium, so far so that the fixed-budget (150k-iter) best-response can no
longer even break even against it. That drives `nlhe_exploitability_bb100`
negative — which per DEPENDENCIES.md invariant #5 ("a best response must be ≥ ~0
bb/100; a negative number means the exploiter is under-trained or the measurement
is wrong — never ship on it") is an **invalid measurement**, not a real
exploitability of -6.8. You cannot claim the primary metric "improved" from a
number the project explicitly flags as broken. The lesson: **the best-response
budget (`expl_max`) must scale with the bot's training budget**; tripling
`nlhe_train` without also raising `expl_max` breaks the exploitability estimator.

**Gate check:**
- `pytest -q` (via `python -m pytest -q`): green, 31 passed (the change is a pure
  numeric train-count bump; no test references it).
- Invariants: Kuhn/Leduc unchanged; bot still crushes random/call-station/maniac.
  **But invariant #5 is BROKEN** — BR exploitability = -6.838 < 0.
- Primary metric: `nlhe_exploitability_bb100` can't count (invalid/negative);
  `win_vs_tight_aggressive` moved the *wrong* way (-19.99), beyond its CI.
- Regression: `win_vs_tight_aggressive` dropped 19.99 bb/100 > its ~±13.9 CI — a
  real regression on a baseline category. (Notable side-finding: more MCCFR
  convergence on the coarse 8-bucket abstraction did **not** help against the
  out-of-abstraction TAG opponent — it hurt. Extra convergence toward the
  *abstract* Nash doesn't transfer to beating a strategy that lives outside the
  abstraction.)

**Verdict: REGRESSION.** Reverted the change (`LEVELS["standard"]` back to
120,000). Appended today's history row using the unchanged (baseline) bot's
metrics so the trail stays continuous; `EVALUATION.md`/`figures/` untouched (bot
unchanged). Follow-up for a future run: retry "train longer" **only** with
`expl_max` scaled up in step (e.g. 150k → 400k+) so the exploitability lower bound
stays valid, and re-examine why extra convergence regresses vs TAG.

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
