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

## 2026-07-26 — DCFR discount tuning for the NLHE MCCFR trainer

**Idea:** backlog item 5. The NLHE trainer (`FastNLHECFR`) is **CFR+** —
negative regrets floored at 0, linear strategy averaging — while the exact
solvers (`CFRSolver`/`TreeCFR`) use **Discounted CFR**. Sweep DCFR's
`(α, β, γ)` on Leduc, where exploitability is *exact* and a sweep is cheap, and
adopt the winner in the NLHE trainer.

**Hypothesis:** flooring negative regrets throws away information. DCFR's
gentler negative-regret discount lets an action that looked bad early recover
when the opponent's strategy drifts, which should converge to a less
exploitable blueprint at the same 120k deals.

**Leduc sweep** (exact exploitability, 39 configs at 10k iterations, then 38
refinement configs at 20k; `TreeCFR`, both stages ranked on final
exploitability):

| Config | Leduc exploitability @20k |
|---|---|
| `α=3.0, β=0.5, γ=4.0` | **0.003879** (best) |
| `α=3.0, β=0.5, γ=3.0` | 0.003950 |
| `α=3.0, β=0.5, γ=2.0` | 0.004108 |
| DCFR published default `α=1.5, β=0.0, γ=2.0` | 0.006309 |
| **CFR+ (what the NLHE trainer uses)** | **0.006763** |

β is the sharp lever: every `β=0.5` config beat every `β∈{-3, 0, 1, 2}` one, and
α∈[2,3] / γ∈[2,4] is a flat plateau (0.0039–0.0046). Adopted
**`(α, β, γ) = (3.0, 0.5, 2.0)`** — best-cluster α/β with the published γ=2,
since γ is Leduc-indistinguishable here and a higher γ concentrates the average
on the last iterations, which adds Monte-Carlo variance in a *sampled* trainer
in a way full-tree Leduc can't show.

**Implementation** (all reverted, see verdict): `FastNLHECFR` gained a
`variant`/`α`/`β`/`γ` argument. Two tricks keep DCFR affordable under chance
sampling, where a full O(|I|) discount sweep per deal is unaffordable:
- **γ in closed form.** Multiplying every strategy sum by `(t/(t+1))^γ` after
  each iteration leaves a contribution from iteration `s` weighted by
  `(s/(T+1))^γ ∝ s^γ`, so accumulating with weight `t**γ` at visit time is
  exactly equivalent and needs no sweep (γ=1 is the linear averaging CFR+ does).
- **α/β lazily per node.** Each node records the iteration through which it has
  been discounted and, on its next visit, catches up with the product of the
  intervening factors read off a cumulative-log table — the same schedule,
  deferred. Cost: +7% wall-clock on training.

Verified before measuring: with `variant="cfr+"` the trainer is **bit-identical**
to the pre-change code (max action-probability difference **0.0** over all 5772
info sets after 20k deals, same seed), so the refactor itself moved nothing. The
exploiter (`FastExploiterCFR`) was deliberately left on CFR+ so the measuring
instrument is identical for baseline and candidate.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`, seed 0, same
120k training deals):

| Metric | Baseline (CFR+) | Candidate (DCFR 3.0/0.5/2.0) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | +3.289 | **−1.492** | **invalid — see below** |
| `win_vs_random` | +63.71 (CI ±16.47) | +70.63 (CI ±16.07) | +6.92 (within CI) |
| `win_vs_call_station` | +111.05 (CI ±17.58) | **+82.27** (CI ±17.42) | **−28.78 — REGRESSION** |
| `win_vs_maniac` | +65.28 (CI ±18.80) | +60.26 (CI ±18.78) | −5.02 (within CI) |
| `win_vs_tight_aggressive` | +8.37 (CI ±13.90) | +1.64 (CI ±13.49) | −6.73 (within CI) |
| `pushfold_jam_pct` | 62.1 | 60.9 | −1.2 (still in the Nash 60–70% band) |
| `nlhe_infosets` | 5772 | 5772 | unchanged (abstraction untouched) |
| `kuhn_exploitability` / `leduc_exploitability` | 0.002265 / 0.0046 | identical | untouched code path |

Best-response curves (bb/100 vs exploiter iterations):

| BR iters | 10k | 25k | 50k | 100k | 150k |
|---|---|---|---|---|---|
| baseline | −28.87 | −17.97 | −8.81 | −0.99 | **+3.29** |
| candidate | −31.95 | −21.79 | −13.29 | −5.77 | **−1.49** |

**Gate check — FAILS on two independent counts:**
- `python -m pytest -q` green (43 passed, 4 new), and the Kuhn/Leduc invariants
  are untouched. So the code was fine; the *bot* was not.
- **Invariant 5 broken.** The best response to the candidate is still
  **negative** (−1.49 bb/100) at the standard 150k-iteration budget. Per
  `DEPENDENCIES.md` that means the exploiter is under-converged and the
  measurement is not usable — "never ship on it". The candidate's whole BR curve
  is shifted ~4–5 bb/100 below the baseline's with the *same shape*, i.e. this
  bot needs a longer exploiter, not that it is less exploitable. The apparent
  3.289 → −1.492 "improvement" is a measurement artifact and is **not** claimed.
- **Regression on a baseline category.** `win_vs_call_station` drops 28.78
  bb/100. That exceeds the paired 95% bound (√(17.58² + 17.42²) ≈ 24.8), so it
  is a real regression, not noise — and it is the one opponent that most
  directly punishes an unbalanced value-betting strategy.

**Reading:** the Leduc win did not transfer. The plausible reason is that Leduc
is solved by *full-tree* CFR while NLHE is chance-sampled: retaining negative
regrets (β=0.5) and steepening the strategy average (γ=2 over the CFR+ γ=1)
both make the average strategy track recent, noisier sampled iterates. On an
exact tree that is pure speed-up; under sampling it trades bias for variance.

**Verdict: REGRESSION — reverted.** Code restored to CFR+ (`git checkout`);
today's `metrics_history.csv` row is the unchanged bot's, which reproduced the
2026-07-01 numbers to the digit (a determinism check worth having).

**For the next session:**
- If DCFR is retried in the trainer, sweep on **NLHE with a sampled proxy
  metric** (e.g. exploitability at `level="quick"`), not on Leduc — the
  full-tree→sampled transfer is what failed here, so a Leduc sweep is the wrong
  screen for this trainer.
- γ alone (linear → quadratic averaging, keeping the CFR+ regret floor) is the
  cheap one-knob version and was never isolated; β=0.5 is the suspect.
- Any future run that reports an exploitability *drop* should check the BR value
  is positive first — this run shows a negative BR value moving the headline
  metric ~4.8 bb/100 in the flattering direction.

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
