# DEPENDENCIES — what depends on what

You are coming in cold. This file is the map: it tells you, for any change you
make, what else will move. Read the "Mental model" first, then use the
"If you change X" table whenever you touch something.

## Mental model

The project is a pipeline. Data flows **left to right**; nothing flows back.

```
        games + evaluator                solvers                 the bot
   ┌──────────────────────┐     ┌────────────────────┐     ┌───────────────┐
   │ cards, evaluator      │     │ cfr / tree (exact) │     │ trained NLHE  │
   │ kuhn, leduc, nlhe     │ ──▶ │ mccfr / nlhe_tree  │ ──▶ │ strategy      │
   │ nlhe_abstraction      │     │ exploitability     │     │ (TabularStrat)│
   └──────────────────────┘     └────────────────────┘     └──────┬────────┘
                                                                   │
                                  ┌────────────────────────────────┘
                                  ▼
                       ┌────────────────────┐
                       │ agents + eval/arena│  measures the bot
                       │ eval/exploit       │
                       └─────────┬──────────┘
                                 ▼
                       ┌────────────────────┐
                       │ metrics.py         │  ONE source of truth for numbers
                       └─────────┬──────────┘
              ┌──────────────────┼─────────────────────┐
              ▼                  ▼                     ▼
        evaluate.py        visualize.py        metrics_history.csv
       (EVALUATION.md)     (figures/*.png)     (appended daily)
```

Key idea: **`pokerbot/metrics.py` is the single source of truth** for "how good
is the bot". The report, the visualizations, and the daily history all read the
same numbers from it. If you want a new metric shown everywhere, add it there
once.

## The layers (bottom = no dependencies)

| Layer | Files | Depends on | Notes |
|---|---|---|---|
| Cards/eval | `cards.py`, `evaluator.py` | — | Pure, exhaustively tested. Rarely changes. |
| Games | `games/base.py`, `kuhn.py`, `leduc.py`, `nlhe.py`, `nlhe_abstraction.py` | cards, evaluator | Rules + the card **abstraction**. |
| Exact solvers | `solve/cfr.py`, `solve/tree.py`, `solve/exploitability.py` | games | CFR/DCFR + exact exploitability (Kuhn/Leduc). |
| MCCFR | `solve/mccfr.py`, `solve/nlhe_tree.py` | nlhe, abstraction, evaluator | Trains the NLHE bot; best-response exploiter; `matchup_value`. |
| Search | `solve/subgame.py` | nlhe_tree, evaluator | Real-time **river** subgame re-solver (endgame search); deterministic, cached. |
| Agents | `agents/base.py`, `agents/baselines.py`, `agents/search.py` | games, solvers | The bot wraps a `TabularStrategy`; `SearchAgent` adds river re-solving; baselines are heuristics. |
| Eval | `eval/arena.py`, `eval/exploit.py` | agents, nlhe_tree | Win rate (mirrored CIs) + exploitability. |
| Metrics | `metrics.py` | everything above | Computes the full metrics dict + history row. |
| Outputs | `evaluate.py`, `visualize.py` | metrics (+ lower layers) | `EVALUATION.md`, `figures/*.png`. |
| Tests | `tests/*.py` | the layer they test | Must stay green. |

## If you change X → Y moves

| You change… | …and these change / must be re-checked |
|---|---|
| **The card abstraction** (`nlhe_abstraction.py` buckets) | Information-set keys change ⇒ the trained bot, its size, win rates, exploitability, push/fold and pre-flop grids, the figures, and `EVALUATION.md`. Re-train + regenerate everything. `StrengthAbstraction` thresholds are sampled with a fixed seed — changing `samples`/`seed`/`postflop_buckets` reshuffles all buckets. |
| **The action abstraction / NLHE config** (`bet_sizes`, `stack`, `max_raises`) in `metrics.py`/`evaluate.py` | Betting tree shape changes ⇒ compiled tree, bot, all NLHE metrics and figures. Bigger trees train slower. |
| **The solver** (`cfr.py`/`tree.py`/`mccfr.py`/`nlhe_tree.py` update rule) | Convergence curves (Kuhn/Leduc), the bot, exploitability. **Guardrails:** Kuhn must still reach the analytic Nash (value −1/18, low exploitability) and Leduc exploitability must still fall — `tests/test_kuhn_leduc.py` enforces this. |
| **`FastNLHECFR`'s `variant`/`(α, β, γ)`** (the bot's update rule) | The bot only — the abstraction, betting tree and info-set count are untouched, so this is the cleanest single-variable experiment available. All NLHE metrics, figures and `EVALUATION.md` move; Kuhn/Leduc do not. Default is `dcfr (1.5, 0, 2)`; `variant="cfr+"` reproduces the pre-2026-07-27 trainer bit-for-bit. If you change the lazy-discount bookkeeping, `tests/test_mccfr.py::test_lazy_discounting_matches_naive_dcfr` must still pass — it pins the deferred discount against a naive full-table sweep. |
| **The evaluator** (`evaluator.py`) | Everything that scores showdowns. `tests/test_evaluator.py` (exhaustive frequency counts) must pass — if it fails, stop. |
| **The bot** (more training / new strategy) | `eval/*`, `metrics.py`, all `figures/*.png`, `EVALUATION.md`, and a new row in `metrics_history.csv`. Win rates and exploitability should not regress. |
| **`metrics.py`** (add/rename a metric) | Update `flatten()` + `HISTORY_COLUMNS` (or `metrics_history.csv` breaks), `visualize.py` (to plot it), and `evaluate.py` (to report it). |
| **The river search solver** (`solve/subgame.py`) or **`SearchAgent`** (`agents/search.py`) | Only the *search* numbers move: `nlhe.search`, the `nlhe_exploitability_search_bb100` column, section 4d of the report, the search series in `figures/progress.png`. The blueprint path (`StrengthAbstraction`/`FastNLHECFR`/existing metrics) is untouched **iff** you don't change the shared solvers' default (`search=None`) behaviour. Determinism: the re-solve must stay a pure function of `(board, river_root, blueprint)` — no unseeded RNG. |
| **`SEARCH_LEVELS`** (search eval budget) | The search exploitability magnitude and its wall-clock. Keep the baseline (blueprint) and candidate (search) on the **same** pool/iters/seeds, or the delta is meaningless. |
| **`visualize.py`** | Only `figures/*.png`. Safe; no other code depends on it. |
| **`metrics_history.csv` columns** | `visualize.py:fig_progress` and `metrics.py:HISTORY_COLUMNS` must agree. Append-only — don't rewrite past rows. |
| **The arena / CIs** (`eval/arena.py`) | Reported win rates and their significance everywhere. Keep the mirrored-deal design (it's the variance reduction). |

## Regenerate everything

```bash
pytest -q                                  # gate: must be green
python -m pokerbot.evaluate --out EVALUATION.md
python -m pokerbot.visualize --level standard   # writes figures/
```

`metrics_history.csv` is appended by the daily routine (see
`routines/daily_improvement.md`), not by the commands above.

## Invariants that must never break (your safety net)

1. `tests/test_evaluator.py` — the evaluator is exact.
2. Kuhn exploitability → ~0 and game value → −1/18.
3. Leduc exploitability decreases toward 0.
4. The bot beats `random`, `call-station`, `maniac` by a wide, significant margin.
5. A best response to the bot must be ≥ ~0 bb/100 (a negative number means the
   exploiter is under-trained or the measurement is wrong — never ship on it).
6. **Search off ⇒ nothing moves.** With river search disabled (`search=False`,
   the default), every existing number reproduces *exactly*. The search hooks on
   `FastExploiterCFR`/`matchup_value` and `SearchAgent` all default to the plain
   blueprint path — `tests/test_subgame.py` pins this (search-off agent decisions
   and `search=None` matchup values are bit-identical to the blueprint).
7. **Search must not raise exploitability (unsafe-solving guard).** Enabling
   river search must not increase best-response exploitability vs the blueprint
   beyond noise, measured on the *same* board pool / budget / seeds
   (`nlhe_exploitability_search_bb100` vs the blueprint's pool exploitability).
   River re-solving is currently *unsafe* (unnested): it can in principle raise
   exploitability by letting the opponent exploit the blueprint↔re-solve seam.
   A rise beyond noise is a regression — the fix is safe/nested re-solving
   (range-constrained gadget), not shipping the unsafe version.

If a change breaks any of these, it is a regression, not an improvement.

## River search and the off-blueprint fallback

A plain `StrategyAgent` plays **uniform random** on any info-set key it never
trained (`TabularStrategy.action_probs` fallback). `SearchAgent` **replaces that
fallback on the river**: instead of guessing uniformly at an unseen river key, it
re-solves the subgame for its exact hand. Off the river it still defers to the
blueprint (and the uniform fallback). This is additive and gated: `SearchAgent`
with `enabled=False`, and `search=None` on the solvers, are the blueprint path.
