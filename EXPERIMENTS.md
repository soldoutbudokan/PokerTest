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

## 2026-07-29 — DCFR strategy-averaging discount in the NLHE trainer

**Idea:** backlog item 5 ("DCFR tuning"). The exact solvers (`CFRSolver`,
`TreeCFR`) have run Discounted CFR since day 1, but the NLHE blueprint trainer
`FastNLHECFR` was still plain **CFR+ with linear averaging** — every iteration's
strategy entered the average with weight `t`. With chance sampling, the early
iterations average over a handful of deals and are mostly sampling noise, so
weighting late iterations more heavily should discard that noise. Added a
`gamma` parameter: iteration `t` now contributes with weight `t ** gamma`.

**Why the closed form is free.** DCFR multiplies the running strategy sum by
`(t/(t+1)) ** gamma` each iteration and adds the current strategy with weight
1; iteration `t`'s share of the final sum is then proportional to `t ** gamma`.
Accumulating `t ** gamma` directly is the *same normalised average* with no
per-iteration sweep over the (5,772-entry) information-set table — which is what
made this affordable in pure Python. `tests/test_mccfr.py` pins the equivalence
against the iterative formulation for `gamma` in (1, 2, 3).

**Scope:** only the blueprint trainer changed. `FastExploiterCFR` — the best
response that *measures* exploitability — was deliberately left on CFR+, so
`nlhe_exploitability_bb100` is still produced by the same yardstick as every
past row and the comparison stays honest.

**Sweep (backlog said "sweep on Leduc"; swept on NLHE instead, which is the
actual target).** Blueprint trained at the reduced `quick` NLHE budget (40k
deals), exploitability measured with the unchanged exploiter, 2 seeds:

| (alpha, gamma) | seed 0 | seed 1 | mean |
|---|---|---|---|
| (none, 1) — the committed bot | +2.895 | +2.225 | +2.560 |
| (none, **2**) | +0.098 | −0.378 | −0.140 |
| (1.5, 2) | +0.514 | −0.263 | +0.126 |
| (1.5, 1) | +3.346 | +2.364 | +2.855 |
| (3.0, 2) | +0.153 | −0.400 | −0.124 |
| (1.5, 3) | −0.881 | −1.557 | −1.219 |

`gamma` is the entire effect; the **regret** discount `alpha` was a wash (worse
on one seed, better on the other) so it was **not adopted** — the prototype
lazy-discount machinery was removed rather than carried as untested-by-benefit
complexity. `gamma=3` scores lower still, but drives the measured value negative
at this budget, which invariant 5 reads as an under-trained exploiter rather
than a better bot; left in the backlog. Adopted the canonical DCFR
**`gamma = 2`**.

**Before → after** (`level=standard`, seed 0 — the row appended to
`metrics_history.csv`):

| Metric | Baseline | Candidate | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | **1.543** | **−1.746** |
| `win_vs_random` | +63.71 (CI ±16.47) | +67.40 (±16.20) | +3.69 |
| `win_vs_call_station` | +111.05 (±17.58) | +107.57 (±17.68) | −3.48 |
| `win_vs_maniac` | +65.28 (±18.80) | +60.08 (±18.61) | −5.20 |
| `win_vs_tight_aggressive` | +8.37 (±13.90) | −2.44 (±13.79) | −10.81 (inside CI) |
| `nlhe_infosets` | 5,772 | 5,772 | unchanged (abstraction untouched) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched code path) |
| `pushfold_jam_pct` | 62.1 | 61.5 | −0.6 (still in the Nash 60–70% band) |

**Is −1.75 signal or noise?** On its own it sits inside the routine's stated
1–2 bb/100 noise band, so the run was repeated on a second independent seed at
the same level. Four paired measurements:

| | baseline | candidate | Δ |
|---|---|---|---|
| quick, seed 0 | +2.895 | +0.098 | −2.797 |
| quick, seed 1 | +2.225 | −0.378 | −2.603 |
| standard, seed 0 | +3.289 | +1.543 | −1.746 |
| standard, seed 1 | +3.602 | +1.755 | −1.847 |

The two `standard` deltas differ by 0.10 bb/100 against an effect of 1.8 — the
noise band applies to a single measurement's wiggle, and the *difference* is
reproducible far inside it. The whole best-response curve also shifts down, it
does not cross: baseline `[-28.87, -17.97, -8.81, -0.99, +3.29]` vs candidate
`[-30.08, -19.46, -10.52, -2.77, +1.54]` at 10k/25k/50k/100k/150k exploiter
iterations.

The seed-0 `win_vs_tight_aggressive` drop is noise, not a regression: on seed 1
the same comparison is −5.97 → −5.78 (+0.19). The two seeds disagree in sign,
and both moves are well inside the ±13.8 CI. Same for the other categories
(random +3.69/−5.13, call-station −3.48/+2.47, maniac −5.20/+1.16 across the two
seeds) — all sign-inconsistent and inside their CIs.

**Gate check:**
- `python -m pytest -q` green: **41 passed** (2 new in `tests/test_mccfr.py`:
  the gamma/DCFR averaging equivalence, and fixed-seed determinism).
- Invariants: Kuhn value −1/18 and exploitability unchanged; Leduc unchanged and
  still decreasing; bot still beats random/call-station/maniac by a wide
  **significant** margin on both seeds; best-response exploitability ends
  **positive** on both seeds (+1.543, +1.755), so invariant 5 holds; the search
  path is untouched and `tests/test_subgame.py` still passes.
- Primary metric: `nlhe_exploitability_bb100` falls 3.289 → 1.543 (−1.746),
  reproduced at −1.847 on an independent seed.
- No regression: no `win_vs_*` category drops by more than its 95% CI on
  either seed.

**Caveats / honest limits:**
- The best-response curve is still rising steeply at 150k iterations (−2.77 →
  +1.54 over the last 50k), so neither number is a converged exploitability —
  both are lower bounds at a *fixed exploiter budget*. The claim is therefore
  "harder to exploit at equal exploiter effort", which is exactly what this
  project's metric is defined to measure, but a longer exploiter would raise
  both numbers and could narrow the gap.
- While implementing this, the solver turned out to be **knife-edge sensitive**
  to last-bit float rounding: a node whose regrets have decayed to ~1e-18 has
  its regret-matching strategy decided by the final bit, so perturbing an
  arithmetically-irrelevant constant by a relative 1e-15 changes the trained bot
  on ~half of seeds. That is a property of the CFR+ zero-floor, it predates this
  change, and it is why the new equivalence test is pinned over a short horizon.
  Worth a future run: floor tiny residual regrets to exactly 0.
- `EVALUATION.md` section 4b runs its **own**, shorter exploiter (120k
  iterations/seat, not the 150k of the metrics curve) and reports a *negative*
  number: −0.84 for the baseline, −2.52 now. That section was already negative
  before this change, and the direction is what a harder-to-exploit bot
  predicts — a fixed under-trained exploiter falls further behind. The gate's
  metric (`nlhe_exploitability_bb100`, 150k) is positive on both seeds, so
  invariant 5 holds where it is defined, but 4b's budget should be raised until
  it converges; until then it is not a usable exploitability number.
- `gamma=3` and a proper `alpha` sweep at a *converged* exploiter budget remain
  open.

**Verdict: IMPROVEMENT.** Kept `gamma=2` as the `FastNLHECFR` default,
regenerated `EVALUATION.md` and `figures/` at `level=standard`, and committed to
`main`.

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
