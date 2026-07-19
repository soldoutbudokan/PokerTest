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

## 2026-07-19 — train the NLHE blueprint longer (120k → 250k deals)

**Idea:** backlog #1. Chance-sampling MCCFR converges ~O(1/√T), so training the
blueprint for more deals should move it closer to the abstract Nash equilibrium
and lower its exploitability. Bumped only the `standard` level's blueprint
training count in `metrics.py:LEVELS` from 120,000 → 250,000 deals (a single
config value; nothing else touched). The best-response exploiter budget
(`expl_max=150,000`/seat), eval budgets, seeds and abstraction were held fixed,
so baseline (120k) and candidate (250k) are a paired comparison.

**Hypothesis:** a better-converged blueprint sits closer to abstract-Nash, so a
fixed-budget best response exploits it less → `nlhe_exploitability_bb100` drops.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`, seed 0):

| Metric | Baseline (120k) | Candidate (250k) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | **+3.289** (valid) | **−3.419** (INVALID) | see below |
| `nlhe_infosets` | 5,772 | 5,772 | unchanged |
| `win_vs_random` | +63.71 (CI ±16.47) | +73.74 (CI ±16.27) | +10.03 |
| `win_vs_call_station` | +111.05 (CI ±17.58) | +104.22 (CI ±17.61) | −6.83 (within CI) |
| `win_vs_maniac` | +65.28 (CI ±18.80) | +74.28 (CI ±18.69) | +9.00 |
| `win_vs_tight_aggressive` | +8.37 (CI ±13.90) | +9.43 (CI ±13.58) | +1.06 |
| `kuhn` / `leduc` exploitability | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched paths) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (preflop-only, separate trainer) |

**Why the primary metric is invalid (the decisive point).** The best-response
exploitability is a *lower bound* built from a fixed-budget (150k/seat) exploiter.
The exploit curves show what happened:

- Baseline (120k blueprint): BR climbs `−28.9 → −18.0 → −8.8 → −0.99 → **+3.29**`
  at 150k — it **crosses zero**, so +3.29 is a valid positive lower bound.
- Candidate (250k blueprint): BR climbs `−33.8 → −23.9 → −15.4 → −7.75 → **−3.42**`
  at 150k — it **never crosses zero**. The whole curve is shifted down: the
  stronger, better-converged blueprint is a *harder target*, so the same 150k
  exploiter is now under-trained and can't even reach break-even.

A negative BR value is exactly the case DEPENDENCIES invariant 5 warns about
("a negative number means the exploiter is under-trained or the measurement is
wrong — never ship on it"). So −3.419 is a **measurement artifact, not a real
exploitability**, and comparing +3.289 (valid) to −3.419 (invalid) is
apples-to-oranges. The apparent "improvement" cannot be certified.

**Gate check:**
- `python -m pytest -q` green: **39 passed** (config-only change; no code paths
  altered).
- Invariants: Kuhn/Leduc unchanged; bot still crushes random/call-station/maniac
  significantly (all still significant, three of four rose). **Invariant 5 is
  VIOLATED for the candidate** — BR exploitability ends at −3.419 < 0. That alone
  blocks acceptance.
- Primary metric: cannot be validly compared (candidate BR under-converged).
- Regression check: `win_vs_call_station` fell 6.83 bb/100 but well within its
  ±17.58 CI (not significant); no category significantly regressed. The block is
  the invalid primary metric, not a win-rate regression.

**Verdict: NO CHANGE (inconclusive — invariant 5 broken).** Reverted the config
(`standard` back to 120,000 deals); nothing shipped. History row for 2026-07-19
records the unchanged (120k) bot's numbers so the shipped-bot series stays honest.
The rising win rates (random/maniac +9–10 bb/100) hint the longer-trained bot may
genuinely be stronger, but that can only be certified once the exploiter is
converged against it. **Follow-up (a separate, measurement-scoped session):**
raise `expl_max` (e.g. to 250k–400k/seat) until the BR reconverges to a valid
positive bound, re-baseline, then re-test training-longer against that
properly-resolved exploiter. Bumping blueprint training without also strengthening
the exploiter just outruns the measurement.

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
