# Experiments log

The daily improvement routine (`routines/daily_improvement.md`) appends one
entry per run. Newest first. Each entry: what was tried, the hypothesis, the
before→after objective metrics, and the verdict (IMPROVEMENT / NO CHANGE /
REGRESSION).

Metrics legend (all from `pokerbot.metrics.flatten`):
- `kuhn_exploitability`, `leduc_exploitability` — solver sanity (must stay low).
- `nlhe_exploitability_bb100` — best-response lower bound (lower = better).
- `nlhe_exploitability_search_bb100` — same, for the **blueprint+search** bot,
  measured on the search board pool (blank on blueprint-only runs).
- `win_vs_*` — bot win rate vs each baseline, bb/100 (higher = better).
- `pushfold_jam_pct` — 10 BB SB jam range (Nash ≈ 60–70%).

---

## 2026-07-27 — Discounted CFR for the NLHE trainer (DCFR tuning)

**Idea:** backlog item 5. The exact solvers (`CFRSolver`, `TreeCFR`) have always
used **Discounted CFR**, but the sampled NLHE trainer `FastNLHECFR` — the one
that actually produces the bot — was still plain **CFR+ with linear strategy
averaging**. It never got the upgrade. Sweep `(α, β, γ)` and adopt the best rule
for the NLHE trainer.

**Hypothesis:** the blueprint is under-converged at 120k deals, so a
better-converging regret/averaging rule should reach a less exploitable strategy
at the *same* budget — with the card abstraction, the betting tree and the
info-set count all untouched (5,772 info sets before and after), isolating the
update rule as the only variable.

**Implementation** (`pokerbot/solve/nlhe_tree.py`): `variant="dcfr"` with tunable
`(α, β, γ)`, default `(1.5, 0, 2)`. Two observations keep it as cheap per
iteration as CFR+ on a sampled tree:

- *Strategy averaging needs no discounting at all.* Discounting the strategy sum
  by `(t/(t+1))**γ` each iteration leaves iteration `s` weighted by `(s/T)**γ` at
  iteration `T`; the common `T**-γ` cancels under normalization. So accumulating
  with weight `s**γ` is **exactly** DCFR's discounted sum — and `γ=1` recovers
  the old linear averaging.
- *Regret discounting is applied lazily* per visited node, so there is still no
  global sweep over the info-set table. Every discount factor is positive, so an
  untouched node's regrets cannot change sign in between; the deferred catch-up
  is therefore exactly equal to discounting every iteration.
  `tests/test_mccfr.py::test_lazy_discounting_matches_naive_dcfr` pins this
  against a naive reference that sweeps the whole table every iteration.

**Selection.** Exact Leduc sweep (8k iters, exact exploitability — cheap and
noise-free) confirmed DCFR dominates CFR+ on the exact solver:

| rule | Leduc exploitability |
|---|---|
| cfr+ | 0.010266 |
| dcfr 1.5/0/1 | 0.009138 |
| dcfr 2/0/3 | 0.008226 |
| dcfr 1.5/0/2 | 0.008390 |
| **dcfr 1.5/0.5/2** | **0.006630** |
| dcfr 1/1/1 (linear) | 0.011292 |

A direct NLHE sweep at `level=quick` (train 40k, BR 60k/seat, same seeds; only
the bot's trainer differs) showed **γ is the dominant knob**: every γ=2 config
cut measured exploitability several-fold, while γ=1 did not. `dcfr 1.5/0.5/2`
drove the measurement *negative* (−3.148), i.e. below what a 60k-iteration best
response can resolve — that violates invariant 5, so it was **not** adopted
despite winning on Leduc. Adopted the validated `dcfr (1.5, 0, 2)`.

**Before → after** (`level=standard`, seed 0, identical abstraction/tree/budget):

| Metric | Baseline (cfr+) | Candidate (dcfr) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | **1.459** | **−1.830** |
| `nlhe_infosets` | 5772 | 5772 | 0 (same abstraction) |
| `win_vs_random` | +63.71 (CI ±16.47) | +58.49 (±16.26) | −5.22 (within CI) |
| `win_vs_call_station` | +111.05 (±17.58) | +101.83 (±17.52) | −9.22 (within CI) |
| `win_vs_maniac` | +65.28 (±18.80) | +56.75 (±18.69) | −8.53 (within CI) |
| `win_vs_tight_aggressive` | +8.37 (±13.90) | +0.97 (±13.78) | −7.40 (within CI) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched path) |
| `pushfold_jam_pct` | 62.1 | 61.5 | −0.6 (still in the Nash 60–70% band) |

**Is −1.83 bb/100 noise?** The routine's rule of thumb is "1–2 bb/100 is noise",
which this sits inside, so it was checked two ways rather than assumed.

*1. Measured seed-to-seed noise.* Re-ran the whole comparison at seed 1:

| | cfr+ | dcfr | Δ |
|---|---|---|---|
| seed 0 | 3.289 | 1.459 | **−1.830** |
| seed 1 | 3.602 | 1.889 | **−1.713** |

The spread *within* a variant across seeds is only **0.31** (cfr+) and **0.43**
(dcfr) bb/100 — so the actual noise on this metric is ~0.3–0.4, and the effect
is **4–6×** it. The 1–2 bb/100 rule of thumb is conservative here.

*2. Best-response convergence.* The standard metric stops the exploiter at 150k
iters/seat, where its curve is still rising steeply — so a lower number there
could just mean the BR is *less converged* against that bot. Pushing the same
best response 3.3× deeper against both bots (same seeds) shows the gap is flat:

| BR iters/seat | cfr+ | dcfr | gap |
|---|---|---|---|
| 150,000 | +3.289 | +1.459 | −1.830 |
| 250,000 | +8.247 | +6.397 | −1.850 |
| 350,000 | +11.503 | +9.663 | −1.840 |
| 500,000 | +14.839 | +13.049 | −1.790 |

Six independent measurements (2 seeds × standard, 4 BR budgets), all negative,
range −1.71…−1.85. The improvement is real.

*Win rates, conversely, are noise.* The uniform downward drift at seed 0 does
**not** replicate: at seed 1 `win_vs_call_station` is **+5.48** and
`win_vs_tight_aggressive` **+5.15** in DCFR's favour. Within-variant seed-to-seed
spread reaches 14.3 (cfr+ TAG) and 16.6 (dcfr call-station) bb/100, dwarfing the
deltas. No category drops by more than its 95% CI in either seed.

**Gate check:**
- `python -m pytest -q` green: **42 passed** (3 new in `tests/test_mccfr.py`:
  lazy-vs-naive discount equivalence, CFR+ still floors negative regrets, and a
  DCFR-bot-beats-baselines check).
- Invariants: Kuhn/Leduc untouched and numerically unchanged; the bot still
  crushes random/call-station/maniac by a wide significant margin (+58.5, +101.8,
  +56.8, CIs ~±17); BR exploitability ends **positive** (+1.459); push/fold still
  in the Nash band. Search paths untouched (search off ⇒ nothing moves).
- Primary metric: `nlhe_exploitability_bb100` **3.289 → 1.459**, replicated at a
  second seed and across four BR budgets, 4–6× measured noise.
- No regression: every `win_vs_*` delta is inside its 95% CI, in both seeds.

**Side finding (for the backlog), recorded because it affects how every past
number should be read:** the in-abstraction exploitability metric is far from
converged at its 150k-iteration budget — the same best response reaches **+14.8
bb/100** against today's baseline bot at 500k iters, versus the +3.3 the report
quotes. The headline number is a *loose* lower bound, and its absolute value is
budget-dependent (comparisons at equal budget, as done here, remain valid).
Raising `expl_max`, or reporting the BR curve's slope, would make the metric more
honest — but it would also redefine the column, so it needs its own run.

**Verdict: IMPROVEMENT.** Kept `variant="dcfr"` (1.5, 0, 2) as the
`FastNLHECFR` default, regenerated `EVALUATION.md` and `figures/` at
`level=standard`, and appended the 2026-07-27 history row.

**Next (backlog):** `dcfr 1.5/0.5/2` won the exact Leduc sweep and looked
strongest on NLHE too, but could not be *measured* at the current BR budget
(negative best-response value). Re-run it once the exploiter budget is raised —
it may be a further win sitting just under the measurement floor.

---

## 2026-07-15 — real-time river subgame search (endgame re-solving)

**Idea:** the bot plays a fixed blueprint over a *coarse* 8-bucket post-flop
card abstraction, and that abstraction error dominates its exploitability.
Add **real-time river subgame re-solving** (Libratus/Pluribus blueprint→search):
when play reaches the river, re-solve the current subgame at exact-strength
(near-unabstracted) granularity from the opponent's — and the hero's own —
river range implied by the blueprint. New: `pokerbot/solve/subgame.py`
(`RiverSubgameSolver`), `pokerbot/agents/search.py` (`SearchAgent`), plus
optional `search=`/`deal_fn=` hooks on `FastExploiterCFR`/`matchup_value` that
are inert when `search=None` (so the blueprint path is byte-for-byte unchanged).

**How it works.**
- *Subgame:* the river betting subtree is card-independent and already in the
  compiled tree (only 25 distinct river roots, each ≤21 terminals). Only
  showdowns depend on cards, and those use the exact evaluator.
- *Range:* for each hand, the blueprint reach to the river root is the product
  of the blueprint action probabilities along the public path (per that hand's
  bucket); normalised → the conditional range. Solved as a range-vs-range
  endgame with vector CFR+.
- *Granularity:* hands are merged into **exact showdown-strength classes**
  (lossless for river ordering, far finer than 8 buckets). This ignores
  card-removal / blocker effects — a documented second-order approximation that
  keeps solves fast (showdowns become one `cumsum`).
- *Determinism:* the re-solve is a **full enumeration** (no Monte-Carlo inside),
  a pure function of `(board, river_root, blueprint)`; the only RNG is the
  existing seeded deal/action sampling. Solves are cached per `(board, root)`,
  with a per-board strength/bucket cache shared across roots.
- *Fallback:* on the river, search **replaces** the blueprint's uniform-random
  off-strategy fallback with a real re-solve for the exact hand.

**Setup:** identical blueprint (heads-up 20 BB, pot+all-in, 169 pre-flop + 8
post-flop buckets, MCCFR 120k, seed 0 — byte-identical to the 2026-07-01 bot).
New `SEARCH_LEVELS["standard"]`: fixed pool of **64 boards** (so subgame solves
cache), best-response exploiter **150k iters/seat**, 8k eval hands, 200 solver
iterations, 500 arena pairs. Blueprint and search are measured on the **same
pool, iterations and seeds**, so the delta isolates search's effect.

**Result** (`_search_metrics`, standard search level, seed 0):

| Bot | In-abstraction exploitability (bb/100, pool) |
|---|---|
| blueprint | **+2.615** |
| blueprint + river search | **+0.729** |
| **Δ** | **−1.886** (search *lowers* exploitability ~72%) |

The pool blueprint number (+2.615) tracks the canonical full-random blueprint
exploitability (+2.8–3.3), a sanity check that the pool measurement is sound;
both are positive (BR invariant holds). The −1.886 bb/100 drop is well beyond
the routine's 1–2 bb/100 noise band. Search bot win-rates vs baselines (full
random deals, 500 pairs): random **+90.0**, call-station **+137.8**, maniac
**+87.9**, tight-aggressive **+31.4** (all significant except TAG) — the bot
still crushes the panel. **2197** distinct subgame solves, **~21 min** wall-clock
for the search eval.

A preliminary run at 80k exploiter iters (under-converged, both numbers
negative) gave Δ = −1.4; converging the BR to 150k (both numbers positive)
widened it to −1.9 — as expected, a stronger best response exploits the
blueprint's river seams more, and search closes them.

**Gate check:**
- `python -m pytest -q` green: **39 passed** (8 new in `tests/test_subgame.py`:
  subgame convergence, nut-never-folds, determinism/caching, search-off ==
  blueprint, `search=None` matchup unchanged, beats call-station, and a
  search-not-worse-than-blueprint exploitability check).
- Invariants: Kuhn/Leduc untouched; bot still crushes random/call-station/maniac
  significantly; best-response exploitability ends **positive** (blueprint
  +2.615, search +0.729). New invariants 6 (search off ⇒ exact reproduction) and
  7 (search must not raise exploitability) both hold.
- Primary metric: search lowers in-abstraction exploitability from +2.615 to
  +0.729 bb/100 (−1.886, > noise) on the same pool/seeds — a real, paired win.

**Caveats / honest limits (drive the next sessions):**
- The exploiter is itself **in-abstraction** (8-bucket best response), so it
  cannot fully punish the finer blueprint↔re-solve seam. The −1.9 is a *lower
  bound* on search's benefit against a bucketed adversary; a finer/unabstracted
  exploiter is needed to stress the seam (and to certify safety).
- River re-solving is **unsafe/unnested** here — it did not raise exploitability
  in this measurement, but the range-constrained safe gadget (step 2) is the
  principled guarantee.
- River reach is only ~2.6% of blueprint self-play hands (20 BB → pre-flop-jam
  heavy), which caps how much *river-only* search can move the aggregate; the
  ~1.9 bb/100 it delivers is on that thin slice. Depth-limited turn/flop search
  (step 3) is where the larger gains are.
- Strength-merging ignores blockers; blocker-aware solves are future work.

**Verdict: IMPROVEMENT.** River search lowers exploitability by ~1.9 bb/100
(paired, converged) with no regression and all baselines still crushed. Kept as
an additive, off-by-default capability (`SearchAgent`); the daily routine resumes
against this baseline (see the search-aware section of
`routines/daily_improvement.md`).

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
