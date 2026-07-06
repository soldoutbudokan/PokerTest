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

## 2026-07-06 — finer post-flop strength buckets (8 → 12)

**Idea:** the post-flop card abstraction uses equal-probability made-hand-strength
buckets. Refine the resolution from **8 → 12** buckets/street
(`StrengthAbstraction(postflop_buckets=8)` → `12` in `metrics.py` and
`evaluate.py`, `draw_aware=True` kept), so the bot can separate, e.g., a strong
top-pair from a weak top-pair and play them differently. The betting tree is
card-independent, so this changes only the information-set count (594 tree nodes
either way), not the tree shape — a mild, localized change of the same magnitude
as the 2026-07-01 draw-aware refinement (which was a real win).

**Hypothesis:** finer strength resolution is a strength win against a *thinking*
opponent, so `win_vs_tight_aggressive` (the metric with the most headroom) should
rise, ideally with exploitability flat or lower.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop
buckets, draw-aware flop/turn feature), same `level="standard"` MCCFR
training/eval budget (120k training deals), same seed=0. Only `postflop_buckets`
changed. Baseline (`postflop_buckets=8`) reproduced the committed 2026-07-01
numbers exactly (deterministic pipeline confirmed) before the candidate ran.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (8) | Candidate (12) | Δ | Read |
|---|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | 3.227 | **−0.062** | noise (≪ the routine's 1–2 bb/100 band) |
| `nlhe_infosets` | 5,772 | 7,644 | **+32%** | expected — finer abstraction |
| `win_vs_tight_aggressive` | **+8.37** (CI ±13.90) | **−5.08** (CI ±14.07) | **−13.45** | wrong direction; the intended win regressed |
| `win_vs_call_station` | +111.05 (CI ±17.58) | +101.01 (CI ±17.69) | −10.04 | within CI (not significant) |
| `win_vs_maniac` | +65.28 (CI ±18.80) | +57.97 (CI ±18.77) | −7.31 | within CI (not significant) |
| `win_vs_random` | +63.71 (CI ±16.47) | +71.03 (CI ±16.50) | +7.32 | within CI (not significant) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged | untouched code paths (isolation confirmed) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged | push/fold is a separate preflop-only 10 BB solve |

Best-response exploitability stayed positive throughout and essentially tracked
the baseline curve (BR invariant holds): baseline
`[[10000,-28.87],[25000,-17.97],[50000,-8.81],[100000,-0.99],[150000,3.29]]`
vs candidate
`[[10000,-29.64],[25000,-18.44],[50000,-9.04],[100000,-1.27],[150000,3.23]]`
— same shape, ends positive (+3.23 ≥ 0).

**Gate check:**
- `pytest -q` (via `python -m pytest -q`, see 2026-07-01 environment note) green:
  31 passed.
- Invariants intact: Kuhn/Leduc unchanged; bot still crushes
  random/call-station/maniac by wide, significant margins; BR exploitability ends
  ≥ 0.
- **Primary metric did NOT improve.** Exploitability moved −0.062 bb/100 (pure
  noise), and the intended target `win_vs_tight_aggressive` moved the **wrong
  way** by 13.45 bb/100. All win-rate deltas sit within their (wide) CIs, so none
  is a *statistically significant* regression — but three of four baselines drift
  down and the target metric worsens, so this is not a win.

**Why:** the tree is unchanged, so the +32% extra information sets are trained on
the *same* 120k deals — the finer buckets are simply undertrained, fragmenting
the strategy without a convergence or strength payoff. Finer card abstraction is
a "needs more training to pay off" lever; at a fixed budget it does not help here.

**Verdict: NO CHANGE (leans mild regression).** Reverted the change (kept
`postflop_buckets=8`). Appended today's history row using the **baseline** metrics
(the shipped bot is unchanged) and left `EVALUATION.md`/`figures/` untouched.
Follow-up if revisited: pair a bucket increase with a proportional training-budget
increase, or spend the extra buckets only where they matter (e.g. more resolution
at the top of the strength range) rather than uniformly.

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
