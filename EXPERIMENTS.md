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

## 2026-07-12 — richer bet sizing (add a 0.5-pot bet)

**Idea:** the action abstraction offered only a pot-sized bet + all-in. Backlog
item #2 suggested adding a half-pot size (`bet_sizes=(0.5, 1.0)`) so the bot can
size its bets more finely — the standard lever for shrinking action-abstraction
exploitability in NLHE. Change was a single line in `nlhe_metrics`
(`bet_sizes=(1.0,)` → `bet_sizes=(0.5, 1.0)`); everything downstream (legal
actions, labels, tree build, preflop grid) already handles multiple sizes
generically, so nothing else needed touching. **Training budget was held
identical** (same `level="standard"`, same 120k deals, same seed) so the history
rows stay comparable.

**Hypothesis:** a finer bet menu lets the bot approximate a mixed/geometric
sizing strategy, lowering `nlhe_exploitability_bb100` and/or giving it tools to
out-play the tight-aggressive opponent.

**Setup:** identical to baseline except `bet_sizes=(0.5, 1.0)` (heads-up 20 BB,
169 pre-flop + 8 draw-aware post-flop buckets, `max_raises_per_street=3`), same
`level="standard"` MCCFR training/eval budget, same seed 0.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline | Candidate | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | **4.733** | **+1.444 (WORSE)** — full BR curve worse at convergence (150k: 3.29→4.73) |
| `nlhe_infosets` | 5,772 | 61,802 | **+970%** — the half-pot size explodes the betting tree |
| `win_vs_random` | +63.71 (CI±16.47) | +90.66 (CI±17.21) | +26.95 (better, sig) |
| `win_vs_call_station` | +111.05 (CI±17.58) | +105.88 (CI±17.42) | −5.17 (within CI, noise) |
| `win_vs_maniac` | +65.28 (CI±18.80) | +68.95 (CI±18.92) | +3.67 (within CI, noise) |
| `win_vs_tight_aggressive` | **+8.37** (CI±13.90, not sig) | **−15.78** (CI±13.96, **sig**) | **−24.15 — a REGRESSION** far beyond either 95% CI; the bot flips from (non-sig) beating TAG to *significantly losing* to it |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched path — confirms isolation) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (push/fold uses `bet_sizes=()`, unaffected) |

**Gate check:**
- `pytest -q` (via `python -m pytest -q`): green, 31 passed.
- Invariants intact: Kuhn/Leduc unchanged; push/fold 62.1% (in the Nash 60–70%
  band); BR exploitability positive (4.73 ≥ 0); bot still crushes
  random/call-station/maniac by wide significant margins.
- Primary metric: **neither** improved. `nlhe_exploitability_bb100` rose by 1.44
  bb/100 (wrong direction); `win_vs_tight_aggressive` fell by 24.15 bb/100.
- Regression: `win_vs_tight_aggressive` dropped 24.15 bb/100, ≈1.7× its own 95%
  CI half-width — a statistically significant regression against the one
  sophisticated baseline.

**Why:** at a *fixed* 120k-deal training budget, the half-pot size blew the
abstraction up 10.7× (5,772 → 61,802 info sets), so each info set received
roughly one-tenth the MCCFR visits. The bot is badly under-trained on the larger
tree — more exploitable, and much weaker against TAG, which punishes imprecise
play. Confirms the backlog's own caveat ("bigger tree, slower training; check
it's a net win"). A richer bet menu would likely need a proportionally larger
training budget (and/or external-sampling MCCFR) to pay off.

**Verdict: REGRESSION.** Reverted the code change (`bet_sizes` back to `(1.0,)`);
kept the baseline bot. `EVALUATION.md` and `figures/` are unchanged (bot
unchanged). Appended the baseline metrics as today's history row so the trail
stays continuous.

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
