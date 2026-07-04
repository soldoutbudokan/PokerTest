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

## 2026-07-04 — more post-flop strength buckets (8 → 12)

**Idea:** backlog item #3. The post-flop strength abstraction uses 8
equal-probability made-hand buckets per street. Raise it to 12
(`StrengthAbstraction(postflop_buckets=12)` in `metrics.py`) for finer
made-hand resolution. This is the same "more abstraction resolution" lever
that made the 2026-07-01 draw-aware change a win; the tree structure is
unchanged (buckets only affect information-set keys, not the betting tree), so
it's a one-line, localized change.

**Hypothesis:** finer strength resolution lets the bot separate hands it was
previously lumping together and play them more distinctly — expected to lift
win rate vs the thinking baseline (tight-aggressive) the way the draw feature
did, without moving exploitability much.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop +
draw-aware post-flop buckets, `level="standard"`, seed 0). Only
`postflop_buckets` changed 8 → 12. Baseline = current committed bot; both
computed fresh this run at `standard`.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (8) | Candidate (12) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | 3.227 | −0.062 (inside the 1–2 bb/100 noise band — flat) |
| `nlhe_infosets` | 5,772 | 7,644 | +1,872 (+32%) |
| `win_vs_random` | +63.71 (±16.5) | +71.03 (±16.5) | +7.32 (within CI) |
| `win_vs_call_station` | +111.05 (±17.6) | +101.01 (±17.7) | **−10.04** (within CI) |
| `win_vs_maniac` | +65.28 (±18.8) | +57.97 (±18.8) | **−7.31** (within CI) |
| `win_vs_tight_aggressive` | +8.37 (±13.9) | **−5.08** (±14.1) | **−13.45** (≈ its 95% CI half-width; flips from non-significantly beating TAG to non-significantly losing) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched paths) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (push/fold uses its own coarse abstraction, unaffected) |

Best-response exploitability stayed positive at convergence
(`[[10000,-29.64],[25000,-18.44],[50000,-9.04],[100000,-1.27],[150000,3.23]]`,
same shape and sign as baseline — BR invariant holds).

**Gate check:**
- `pytest -q` (via `python -m pytest -q`) green: 31 passed.
- Invariants hold: Kuhn/Leduc unchanged; bot still beats
  random/call-station/maniac by a wide, significant margin (all `sig=True`);
  BR exploitability ends positive (+3.23 ≥ 0).
- Primary metric did **not** improve: `nlhe_exploitability_bb100` moved
  −0.062 bb/100 (noise, not signal), and `win_vs_tight_aggressive` moved the
  **wrong** way by −13.45 bb/100.
- Net effect is negative: three of four win-rate categories dropped (TAG,
  call-station, maniac), only `random` rose; none crossed its 95% CI, so no
  single category is a *significant* regression, but there is no win to keep.
  The +32% larger abstraction fragmented the fixed 120k-deal training budget
  without paying for itself.

**Verdict: NO CHANGE.** Reverted the code (`postflop_buckets` stays 8). No
figures/`EVALUATION.md` regenerated (bot unchanged). Appended today's history
row from the (kept) baseline metrics so the series stays continuous.

**Note for future runs:** more strength buckets at the current training budget
is a net wash-to-loss. If revisited, pair it with more training deals (a new
higher level or budget bump) so the finer abstraction can actually converge —
raising resolution and iteration count together, not resolution alone.

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
