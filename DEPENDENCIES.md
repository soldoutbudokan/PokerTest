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
| Agents | `agents/base.py`, `agents/baselines.py` | games, solvers | The bot wraps a `TabularStrategy`; baselines are heuristics. |
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
| **The evaluator** (`evaluator.py`) | Everything that scores showdowns. `tests/test_evaluator.py` (exhaustive frequency counts) must pass — if it fails, stop. |
| **The bot** (more training / new strategy) | `eval/*`, `metrics.py`, all `figures/*.png`, `EVALUATION.md`, and a new row in `metrics_history.csv`. Win rates and exploitability should not regress. |
| **`metrics.py`** (add/rename a metric) | Update `flatten()` + `HISTORY_COLUMNS` (or `metrics_history.csv` breaks), `visualize.py` (to plot it), and `evaluate.py` (to report it). |
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

If a change breaks any of these, it is a regression, not an improvement.
