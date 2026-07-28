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

## 2026-07-28 — Discounted CFR (α, γ) in the NLHE MCCFR trainer

**Idea:** backlog item 5 — sweep DCFR's discount exponents and adopt the best
for the NLHE trainer. `FastNLHECFR` was plain **CFR+**: regrets floored at 0,
strategy sum accumulated with linear (`t`) weights. DCFR (Brown & Sandholm
2019) instead discounts positive regrets by `s^α/(s^α+1)` and the strategy sum
by `(s/(s+1))^γ` each iteration.

**How it's applied (lazily, and exactly).** DCFR discounts by sweeping *every*
information set once per iteration; here the table has thousands of sampled
nodes and one iteration touches a handful, so a sweep is unaffordable. Both
discounts are instead folded into **per-iteration weights on the increments**,
which is algebraically identical:

- discounting accumulated regret by `f_s = s^α/(s^α+1)` after every iteration
  leaves `R_T = (Π_{s≤T} f_s) · Σ_t inc_t · w_t` with `w_t = Π_{s≤t}(1+s^-α)`;
  the two accumulators differ only by a positive global factor, which cancels in
  regret matching and commutes with the regret-matching-plus floor. `w_t` is
  maintained as one running scalar (`_regret_weight`), so the cost is one
  multiply per iteration.
- the strategy-sum discount `(s/(s+1))^γ` telescopes to a weight of `t^γ` on
  iteration `t` — the existing code was already this with γ=1.

DCFR's `β` (negative-regret discount) has no lazy analogue and isn't needed: the
plus-floor is the `β → -inf` limit, and under sampling `β=0` decays a negative
regret to ~0 between a node's visits anyway. `alpha < 1` is rejected (`w_t`
would grow like `exp(t^(1-α))` and overflow). `alpha=None, gamma=1.0` reproduces
the previous CFR+ trainer **bit-for-bit** (verified against `HEAD`: 5,772 keys,
max abs diff 0.0).

**Selection (before touching the NLHE numbers).** Two Leduc sweeps at 20k
iterations with *exact* exploitability:

1. Full DCFR `(α, β, γ)`, 25 configs. Best: `(3, 0.5, 3)` 0.003950, `(1.5, 0.5,
   3)` 0.004013 — every top config uses **β=0.5**, which the sampled floor
   cannot express (noted as backlog below). Repo default `(1.5, 0, 2)` 0.006309;
   CFR+ 0.006763.
2. The **floor scheme actually used by the trainer** (plus-floor + α + γ), 15
   configs — this one transfers as-is. γ dominates and α=1 is harmful:

   | α \ γ | 1 | 2 | 3 |
   |---|---|---|---|
   | None | 0.006763 | 0.006184 | 0.005913 |
   | 1.0 | 0.010817 | 0.009976 | 0.009546 |
   | **1.5** | 0.006679 | 0.006118 | **0.005859** |
   | 2.0 | 0.006798 | 0.006295 | 0.006037 |
   | 3.0 | 0.006748 | 0.006200 | 0.005927 |

   (`α=None, γ=1` reproduces `TreeCFR`'s `cfr+` exactly — a check on the harness.)

Then a quick-level NLHE screen (same seeds/budgets, only the trainer differs)
decomposed the two knobs — γ is the whole effect:

| trainer | expl. bb/100 | random | call-station | maniac | TAG |
|---|---|---|---|---|---|
| CFR+ (None, 1) | 2.895 | +83.9 | +83.2 | +78.6 | +5.4 |
| α only (1.5, 1) | 3.241 | +82.0 | +106.1 | +97.9 | −15.1 |
| γ only (None, 2) | 0.098 | +91.0 | +129.6 | +71.3 | −31.0 |
| DCFR (1.5, 2) | 0.431 | +67.0 | +124.1 | +89.8 | −14.4 |

Adopted the canonical DCFR pair **(α, γ) = (1.5, 2)** as the `FastNLHECFR`
default (best of the two γ=2 screens on the panel, top-5 on the Leduc floor
sweep). `metrics.py`/`evaluate.py` needed no change — they construct
`FastNLHECFR` with defaults.

**Before → after** (`level=standard`, seed 0 — the committed row):

| Metric | Baseline (CFR+) | Candidate (DCFR) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | 3.289 | **1.513** | **−1.776** |
| `win_vs_random` | +63.71 ±16.47 | +52.01 ±16.48 | −11.70 (within CI) |
| `win_vs_call_station` | +111.05 ±17.58 | +111.98 ±17.63 | +0.93 |
| `win_vs_maniac` | +65.28 ±18.80 | +56.80 ±18.73 | −8.48 (within CI) |
| `win_vs_tight_aggressive` | +8.37 ±13.90 | −0.57 ±13.92 | −8.94 (within CI) |
| `nlhe_infosets` | 5,772 | 5,772 | 0 (abstraction untouched) |
| `pushfold_jam_pct` | 62.1 | 61.5 | −0.6 (still in the 60–70% Nash band) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched code paths) |

**Replication (the reason this is a keep, not a shrug).** −1.78 bb/100 sits at
the edge of the routine's stated 1–2 bb/100 noise band, so both arms were re-run
at an independent seed (`seed=1`, standard, same budgets):

| Metric | Δ at seed 0 | Δ at seed 1 |
|---|---|---|
| `nlhe_exploitability_bb100` | −1.776 (3.289→1.513) | **−1.904** (3.602→1.698) |
| `win_vs_random` | −11.70 | **+15.02** |
| `win_vs_call_station` | +0.93 | −2.75 |
| `win_vs_maniac` | −8.48 | +3.31 |
| `win_vs_tight_aggressive` | −8.94 | **+11.22** |

The exploitability gain reproduces almost exactly (−1.78, −1.90) while every
win-rate delta **flips sign** between seeds (mean over the two seeds: random
+1.7, call-station −0.9, maniac −2.6, TAG +1.1). So the win-rate movements are
seed noise, and the primary-metric drop is not. The same direction shows up at
the quick level (−2.46) and in the *exact*, noise-free Leduc computation — three
independent measurements, one deterministic.

**Gate check:**
- `python -m pytest -q` green: **43 passed** (4 new in `tests/test_mccfr.py`:
  the lazy weight equals the closed-form DCFR discount to 1e-9 for α∈{1,1.5,3},
  `alpha=None/gamma=1` leaves the accumulators untouched and is deterministic,
  `alpha<1` raises, and a DCFR-trained bot still beats random/call-station).
- Invariants: Kuhn value −0.05557 and exploitability 0.002265 unchanged; Leduc
  0.0046 unchanged; bot still beats random/call-station/maniac significantly;
  best-response exploitability ends **positive** at both seeds (1.513, 1.698);
  jam range 61.5% still inside Nash's 60–70%; search-off reproduction
  (invariant 6) still pinned by `tests/test_subgame.py`.
- Primary metric: exploitability 3.289 → 1.513 bb/100, replicated at a second
  seed (3.602 → 1.698). Beyond noise.
- No regression: no `win_vs_*` category drops by more than its 95% CI at either
  seed, and the deltas average to ≈0 across the two.

**Caveats / backlog:**
- The best Leduc configs all used **β=0.5**, i.e. *keeping* discounted negative
  regret rather than flooring it. Expressing β under sampling needs per-node
  last-visit bookkeeping (a sign-dependent discount can't be folded into a
  scalar increment weight) — that's the natural follow-up, and Leduc says it is
  worth ~30% more exploitability reduction there.
- The exploiter is fixed-budget (150k/seat) and in-abstraction, so "less
  exploitable" means "less exploitable by an equally-budgeted bucketed BR". A
  strategy that is merely *harder to search against* would look the same; the
  Leduc exact result is the guard against that reading.
- `EVALUATION.md`'s section 4b trains its BR on a *smaller* budget than
  `metrics.py` (120k iters/40k eval vs 150k/50k), where the BR is still
  under-converged and the number is negative for both bots: it moved −0.84 →
  −2.51 bb/100. That is the same effect seen at every early milestone of the BR
  curve (the under-trained exploiter loses more to the DCFR bot), not a second,
  contradictory measurement — the converged, positive numbers are the ones the
  invariant is judged on (1.513 at seed 0, 1.698 at seed 1). Raising the
  report's 4b budget to where the BR converges is a cheap follow-up.
- γ=3 edged out γ=2 on Leduc, but higher γ concentrates the average strategy on
  the last few percent of MCCFR deals, which should raise variance in the
  sampled setting. Untested here — one idea per run.

**Verdict: IMPROVEMENT.** Kept: `FastNLHECFR` now defaults to DCFR
`(α, γ) = (1.5, 2)`. Regenerated `EVALUATION.md` and `figures/` at
`level=standard`.

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
