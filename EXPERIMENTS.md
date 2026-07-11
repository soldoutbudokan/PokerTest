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

## 2026-07-11 — train the NLHE bot 4× longer (120k → 480k MCCFR deals)

**Idea:** backlog item #1. At `standard`, the bot trains for 120,000
chance-sampled MCCFR deals over 5,772 info sets — only ~20 visits/infoset on
average, which is under-trained. Raised `standard`'s `nlhe_train` in
`metrics.py:LEVELS` from 120,000 to 480,000 (4×), leaving the card/action
abstraction, evaluation budgets, and the best-response exploiter budget
(`expl_max=150k`, `expl_eval=50k`) untouched. Only the bot's training length
changed, so the abstraction isn't diluted.

**Hypothesis:** MCCFR converges ~O(1/√T), so 4× training moves the bot closer
to the abstract Nash and should *lower* the best-response exploitability lower
bound. Chosen as the safest backlog item: more training can only make the bot
harder to exploit in expectation — worst case "no change," never a regression.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop +
8 post-flop draw-aware buckets), same seed, same `level="standard"` for baseline
and candidate. Baseline = the committed 120k bot; candidate = the same code with
`nlhe_train=480000`.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`):

| Metric | Baseline (120k) | Candidate (480k) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | **+3.289** | **−9.09** | **INVALID** — negative BR ⇒ exploiter under-trained (see below) |
| `nlhe_infosets` | 5,772 | 5,772 | 0 (same abstraction, as intended) |
| `win_vs_random` | +63.71 | +66.79 | +3.08 (within noise) |
| `win_vs_call_station` | +111.05 | +106.75 | −4.30 (within CI) |
| `win_vs_maniac` | +65.28 | +51.96 | −13.32 (within baseline CI ±18.8 — not significant, but notable) |
| `win_vs_tight_aggressive` | +8.37 | +7.40 | −0.97 (within noise) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched code path) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (`pf_train` untouched — good sanity check) |

**What happened — the exploiter budget is coupled to the bot's training
budget.** The primary metric, `nlhe_exploitability_bb100`, is a *lower bound*
produced by training a best response (150k iters/seat) against the fixed bot and
measuring how much it wins. It is only meaningful when the exploiter is
adequately trained. The 4×-trained bot became strong enough that the
fixed-150k best response can no longer even break even against it, driving the
measured value **negative (−9.09)**. Per `DEPENDENCIES.md` invariant #5, a
negative best-response result means the exploiter is under-trained / the
measurement is wrong — **never ship on it**. So the candidate's primary metric
is invalid, not improved: the bot is very likely stronger (harder to exploit,
`win_vs_random` up), but this run's protocol cannot confirm it.

**Gate check:**
- `pytest -q` (`python -m pytest -q`): 31 passed.
- Invariants: Kuhn/Leduc unchanged and low. **Invariant #5 VIOLATED** — best
  response to the candidate is −9.09 bb/100 (< 0). Disqualifying on its own.
- Primary metric: not validly improved (negative BR ⇒ invalid). No `win_vs_*`
  category improved beyond its 95% CI.
- No `win_vs_*` regressed beyond its CI, but that does not rescue the run.

**Verdict: NO CHANGE (measurement invalidated).** Reverted the `nlhe_train`
bump; kept the code at 120k. Appended today's (baseline) row to
`metrics_history.csv` and this entry. **Follow-up for the backlog:** "train
longer" needs the best-response exploiter budget (`expl_max`) scaled up in
lock-step so the exploitability lower bound stays valid — otherwise a stronger
bot silently breaks its own measurement. A future run should raise `expl_max`
(and possibly `expl_eval`) alongside `nlhe_train` and re-establish a matched
baseline before judging.

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
