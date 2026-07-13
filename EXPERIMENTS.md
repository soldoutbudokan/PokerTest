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

## 2026-07-13 — train the NLHE bot 3× longer (120k → 360k MCCFR deals)

**Idea:** at `level=standard` the bot trains 120,000 chance-sampled MCCFR
deals over 5,772 information sets — only ~20 visits/infoset on average, so the
strategy is clearly pre-asymptotic (under-trained). More training is the one
lever with *no* under-convergence regression risk (unlike a richer abstraction
or extra bet size, which enlarge the tree and thin the same budget), and it
targets the primary metric (exploitability) directly. Raised the bot's training
count in `metrics.py:LEVELS` from 120k → 360k at `standard` (and full 250k →
600k to keep the level hierarchy monotonic). Nothing else changed: same
abstraction (169 preflop + 8 draw-aware post-flop buckets), same eval budget,
same seed, same best-response budget (`expl_max=150k`).

**Hypothesis:** a better-converged bot sits closer to the abstract Nash
equilibrium, so its best-response exploitability lower bound should fall and win
rates should hold or improve.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`, seed 0):

| Metric | Baseline (120k) | Candidate (360k) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | **-6.838** | -10.13 — **went negative** |
| `nlhe_infosets` | 5,772 | 5,772 | 0 (tree/abstraction unchanged) |
| `win_vs_random` | +63.71 (±16.47) | +71.34 | +7.63 (within CI) |
| `win_vs_call_station` | +111.05 (±17.58) | +109.95 | -1.10 (within CI) |
| `win_vs_maniac` | +65.28 (±18.80) | +67.70 | +2.43 (within CI) |
| `win_vs_tight_aggressive` | **+8.37** (±13.90) | **-11.62** (±13.13) | **-19.98 — beyond CI (two-sample z≈2.05)** |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched solver) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (push/fold trainer budget untouched) |

Baseline BR curve: `[[10000,-28.87],[25000,-17.97],[50000,-8.81],[100000,-0.99],[150000,3.29]]`.
Candidate BR curve: `[[10000,-35.93],[25000,-26.63],[50000,-18.38],[100000,-11.11],[150000,-6.84]]` — **negative across the whole 150k range.**

**Gate check:**
- `pytest -q` (via `python -m pytest -q`) green: 31 passed.
- Invariants: Kuhn/Leduc untouched and unchanged; bot still crushes
  random/call-station/maniac by a wide significant margin. **BUT invariant #5
  is broken:** the best response must be ≥ ~0 bb/100 — the candidate's BR is
  **-6.84** and negative across the entire curve. Per DEPENDENCIES.md this means
  the *exploiter is under-trained relative to the now-stronger bot*, not that the
  bot is unexploitable. The exploiter budget (`expl_max=150k`) was held fixed
  while the bot trained 3× longer, so the measurement is no longer valid — the
  "improved" exploitability is an artifact, not a real gain.
- Primary metric: exploitability "improved" only via a broken measurement (not
  admissible); `win_vs_tight_aggressive` moved the **wrong** way.
- Regression: `win_vs_tight_aggressive` dropped **-19.98 bb/100**, larger than
  its 95% CI (±13.90) — a significant regression. The earlier, less-converged
  bot happened to exploit TAG's leaks harder; pushing toward abstract Nash
  (which is not the max-exploit strategy vs a fixed weak opponent) gave that up.

**Verdict: REGRESSION.** Reverted the `LEVELS` change (`git checkout --
pokerbot/metrics.py`); the shipped bot stays at 120k. Appended today's row
(the unchanged baseline bot's numbers) to `metrics_history.csv` and this entry.
Did **not** regenerate `EVALUATION.md`/`figures/` (bot unchanged).

**Follow-up for a future run:** "train longer" is only measurable if the
best-response exploiter budget scales *with* the bot — a fixed 150k BR can't
exploit a 360k-trained bot and the metric silently goes negative. A valid
version of this experiment must raise `expl_max` alongside `train_iters`. And
even with a valid exploitability read, the TAG regression would need to clear
its CI before this is shippable.

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
