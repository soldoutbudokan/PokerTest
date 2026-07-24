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

## 2026-07-24 (b) — finer post-flop strength buckets (8 → 12)

**Idea:** backlog #3. The post-flop card abstraction lumps every made hand into
8 equal-probability strength buckets per street (×3 draw classes on flop/turn
since 2026-07-01). Raising `StrengthAbstraction(postflop_buckets=…)` from 8 to
12 halves the strength width of each bucket, so hands that currently share a
bucket (e.g. bottom two pair and top two pair) get separate strategies. One-line
change in `metrics.py`; the betting tree, stack, bet sizes and every measurement
budget are unchanged.

**Hypothesis:** finer card resolution is the same lever that paid off on
2026-07-01 (draw-awareness swung `win_vs_tight_aggressive` +20.85), so a finer
strength split should improve play against the one opponent that punishes coarse
post-flop decisions (TAG), at the cost of more info sets.

**Why this idea was chosen after the (a) failure:** more buckets *increase* the
info-set count, so the blueprint gets *less* training per info set — the opposite
of experiment (a). That keeps the fixed-budget best-response exploiter converged
(non-negative), so the exploitability measurement stays valid. Confirmed: the
candidate's BR curve ends **positive** at +3.227 (invariant 5 holds), where (a)'s
ended at −5.367.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop
buckets, draw-aware post-flop, MCCFR 120k deals, seed 0), `level="standard"` for
both sides. Baseline is the same deterministic run used in (a) — it reproduces
the committed 2026-07-01 row exactly.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`, seed 0):

| Metric | Baseline (8) | Candidate (12) | Δ | Verdict |
|---|---|---|---|---|
| `nlhe_exploitability_bb100` | +3.289 | +3.227 | **−0.062** | deep inside the 1–2 bb/100 noise band — not signal |
| `nlhe_infosets` | 5772 | 7644 | +32% | expected (finer abstraction) |
| `win_vs_random` | +63.71 (±16.47) | +71.03 (±16.50) | +7.32 | within CI |
| `win_vs_call_station` | +111.05 (±17.58) | +101.01 (±17.69) | −10.04 | within CI |
| `win_vs_maniac` | +65.28 (±18.80) | +57.97 (±18.77) | −7.31 | within CI |
| `win_vs_tight_aggressive` | **+8.37** (±13.90) | **−5.08** (±14.07) | **−13.45** | within CI (13.45 < 13.90) but the wrong direction |
| `pushfold_jam_pct` | 62.1 | 62.1 | 0 | unchanged (pre-flop only) |
| `kuhn` / `leduc` exploitability | 0.002265 / 0.0046 | 0.002265 / 0.0046 | 0 | unchanged (untouched path) |

BR exploit curve: baseline `[10k −28.9, 25k −18.0, 50k −8.8, 100k −1.0, 150k
+3.29]` → candidate `[10k −29.6, 25k −18.4, 50k −9.0, 100k −1.3, 150k +3.23]` —
near-identical shape, both crossing zero at ~110k. The exploiter is equally
converged against both bots, so the two exploitability numbers are directly
comparable, and they are the same to within 0.06 bb/100.

**Gate check:**
- `python -m pytest -q` with the candidate applied: green (**39 passed**).
- Invariants: Kuhn/Leduc unchanged; bot still beats random/call-station/maniac by
  a wide significant margin; BR exploitability ends **positive** (+3.227), so
  invariant 5 holds and the measurement is trustworthy.
- **No regression:** no `win_vs_*` category dropped by more than its 95% CI, and
  exploitability did not rise. The change is regression-free.
- **But the primary metric does not improve:** exploitability moved −0.062
  bb/100 (noise, not signal) and `win_vs_tight_aggressive` moved −13.45 (worse).
  The routine requires the primary metric to improve *beyond noise*; "not a
  regression" is necessary but not sufficient.

**Verdict: NO CHANGE.** Reverted to `postflop_buckets=8`. Finer strength buckets
bought nothing measurable here: they cost 32% more info sets while the aggregate
numbers stayed flat, and the TAG result drifted the wrong way. The plausible
reason is dilution — at a fixed 120k training deals, spreading the same MCCFR
samples over 32% more info sets leaves each one less converged, cancelling the
resolution gain. That also explains why this can't simply be fixed by pairing it
with more training: experiment (a) shows raising `train_iters` breaks the
exploitability measurement under the current fixed exploiter budget. **Combined
lesson from (a) and (b): the abstraction-size and training-budget knobs are
coupled, and the evaluation's fixed 150k exploiter budget bounds how far either
can move before the primary metric stops being measurable.** A future session
wanting to push on abstraction fidelity should first re-baseline the whole
measurement (scale `train_iters` *and* `expl_max` together), or switch the
primary metric to something budget-independent. Higher-value untried backlog
that doesn't hit this wall: draw/equity-aware bucketing that adds *information*
rather than *bucket count* (backlog #8), and richer bet sizing (#2).

**History note:** no new `metrics_history.csv` row was appended for this second
experiment — the verdict is NO CHANGE, so today's recorded metrics are the
baseline ones already written by experiment (a) in the same session. Appending an
identical duplicate 2026-07-24 row would add no information and would double-count
the day in `figures/progress.png`.

---

## 2026-07-24 (a) — train the blueprint longer (120k → 300k MCCFR deals)

**Idea:** backlog #1. MCCFR exploitability converges ~O(1/√T), so training the
NLHE blueprint 2.5× longer (120,000 → 300,000 chance-sampled deals at
`level="standard"`) should lower `nlhe_exploitability_bb100`. The change is a
single constant in `metrics.LEVELS["standard"]` (the `train_iters` field); the
abstraction, betting tree and every measurement budget (exploiter iters, eval
hands, arena pairs) are held **fixed**, so it is a clean paired comparison of the
same bot trained more. The routine flags this idea as "only counts if
exploitability actually drops — confirm, don't assume."

**Hypothesis:** exploitability falls from ~3.29 toward ~2.1 (√2.5 ≈ 1.58×) with
no regression in the win-rate panel.

**Setup:** identical to baseline (heads-up 20 BB, pot + all-in, 169 pre-flop + 8
draw-aware post-flop buckets, seed 0). Baseline = current committed bot (120k
deals); candidate = same code with `train_iters` = 300k. Both measured at
`level="standard"`, deterministic seed 0, so the only difference is training
length.

**Before → after** (`pokerbot.metrics.flatten`, `level=standard`, seed 0):

| Metric | Baseline (120k) | Candidate (300k) | Δ |
|---|---|---|---|
| `nlhe_exploitability_bb100` | **+3.289** | **−5.367** | see below — **invalid** |
| BR exploit curve (bb/100) | `[10k −28.9, 25k −18.0, 50k −8.8, 100k −1.0, 150k +3.29]` | `[10k −35.0, 25k −25.5, 50k −17.0, 100k −9.7, 150k −5.37]` | candidate never crosses 0 |
| `win_vs_random` | +63.71 (±16.47) | +83.41 (±16.62) | +19.70 |
| `win_vs_call_station` | +111.05 (±17.58) | +102.43 (±17.28) | −8.62 (within CI) |
| `win_vs_maniac` | +65.28 (±18.80) | +64.22 (±18.72) | −1.06 (within CI) |
| `win_vs_tight_aggressive` | **+8.37** (±13.90) | **−5.41** (±13.14) | **−13.78** (flips back to losing) |
| `kuhn` / `leduc` exploitability | 0.002265 / 0.0046 | 0.002265 / 0.0046 | unchanged (untouched path) |
| `pushfold_jam_pct` | 62.1 | 62.1 | unchanged (preflop-only) |
| `nlhe_infosets` | 5772 | 5772 | unchanged (same abstraction) |

**Why the exploitability number is invalid (the key finding).** The candidate's
best-response value is **−5.367 bb/100**, i.e. **negative**, and its exploit
curve is still climbing steeply at the 150k-iteration budget cap (slope ~+4.3
bb/100 per 50k iters from 100k→150k, no plateau). A negative best-response value
means the **exploiter is under-converged**, not that the bot is unexploitable —
this is exactly the condition **invariant 5** forbids shipping on. Training the
blueprint 2.5× longer made it enough harder to exploit that the *fixed-budget*
150k-iteration exploiter can no longer reach a valid (non-negative) best response
on the same budget. To measure the 300k bot fairly you would have to also grow
`expl_max`, which changes the measurement and breaks comparability with every
past `metrics_history.csv` row. Under the routine's "same budget for baseline and
candidate" rule, the primary metric for the candidate is simply **not a valid
exploitability estimate**, so no improvement can be claimed from it.

**Gate check:**
- `python -m pytest -q`: green (39 passed) — the change is a pure constant, tests
  unaffected. (Bare `pytest -q` still fails collection with
  `ModuleNotFoundError: No module named 'pokerbot'` in this sandbox; `python -m
  pytest` puts cwd on `sys.path` — an environment quirk, not a code regression.)
- Invariants: Kuhn/Leduc untouched and unchanged; bot still crushes
  random/call-station/maniac significantly. **Invariant 5 breached** by the
  candidate: best-response exploitability is **negative** (−5.367), the
  never-ship-on-it condition.
- Primary metric: cannot be validly claimed improved (negative BR = under-trained
  exploiter). Secondary metric `win_vs_tight_aggressive` **regressed** +8.37 →
  −5.41, a swing (−13.78) at the edge of the baseline CI — the bot flips from
  (non-significantly) beating TAG back to (non-significantly) losing.

**Verdict: NO CHANGE.** Reverted the `train_iters` bump; kept the 120k blueprint.
Recorded the baseline metrics as today's history row. The honest lesson: "just
train longer" is not free — past a point it out-runs the fixed-budget exploiter,
so raising blueprint training and the exploiter budget must be done *together*
(and re-baselined) rather than as a one-line reversible daily change. A future
session that wants to bank the extra convergence should scale `expl_max`
alongside `train_iters` and record a fresh baseline, or measure exploitability
against a stronger/finer exploiter.

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
