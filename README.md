# PokerTest — a CFR poker bot with an objective evaluation

This repository builds the strongest poker bot it reasonably can **and**, just
as importantly, an *objective* way to measure how good it is. In computer
poker the gold-standard quality metric is **exploitability** — the distance from
a game-theoretic optimal (Nash) strategy. A perfect bot is unexploitable; the
closer to 0, the better. Where the game is small enough we compute
exploitability *exactly* and prove near-optimality; where it isn't (real
No-Limit Hold'em) we bound it and corroborate with head-to-head results and
comparison to published theory.

## What's here

| Component | File(s) | What it does |
|---|---|---|
| Hand evaluator | `pokerbot/evaluator.py` | Exact 5–7 card evaluator (Cactus-Kev-style lookup tables), validated against textbook hand frequencies. |
| Extensive-form games | `pokerbot/games/` | Kuhn, Leduc, and heads-up No-Limit Hold'em behind one interface. |
| Solvers | `pokerbot/solve/cfr.py`, `tree.py` | Vanilla CFR, CFR+, **Discounted CFR**; exact best-response / exploitability. |
| Monte-Carlo CFR | `pokerbot/solve/mccfr.py`, `nlhe_tree.py` | Chance-sampling MCCFR for NLHE over a compiled betting tree (fast). |
| Agents | `pokerbot/agents/` | The trained bot plus a panel of baselines. |
| Evaluation | `pokerbot/eval/` | Mirrored-deal arena (mbb/100 + 95% CIs), best-response exploitability. |
| Report | `pokerbot/evaluate.py` | Runs every objective check and writes `EVALUATION.md`. |

## The objective evaluation

Four independent checks, each reproducible from the code:

1. **Hand evaluator** — enumerate all 2,598,960 five-card hands; the per-category
   counts must match the textbook exactly (they do), and there must be exactly
   7462 distinct hand values.
2. **Kuhn poker** — the solver must drive exploitability to ~0, recover a
   strategy on the *analytic* Nash one-parameter family, and reproduce the
   known game value of **−1/18** to the first player.
3. **Leduc hold'em** — on the exact 288-information-set game tree, CFR must
   drive exploitability monotonically toward 0.
4. **No-Limit Hold'em bot** —
   - win rate vs a panel of baselines in **mbb/100** with 95% confidence
     intervals, using *mirrored (duplicate) deals* so we measure skill, not card
     luck;
   - an **in-abstraction exploitability** estimate from a best response trained
     against the fixed bot;
   - a short-stack **push/fold** range compared to the known Nash push/fold
     equilibrium.

Why this matters: beating weak baselines is necessary but not sufficient — a bot
can crush calling stations yet be wildly exploitable. Exploitability is the
honest metric, so it's front and center here.

## Reproduce

```bash
pip install numpy pytest          # numpy is optional; only pytest is needed to test
python -m pokerbot.evaluate --quick                # fast pass
python -m pokerbot.evaluate --out EVALUATION.md    # the committed report
pytest -q                                          # correctness tests
```

## Method notes

- **Discounted CFR (DCFR)** is the default solver: positive/negative regrets and
  the average-strategy weights get separate polynomial discounts, which
  outperforms vanilla CFR on Leduc-scale games.
- The NLHE bot uses an **action abstraction** (pot-sized bet + all-in) and a
  **card abstraction** (lossless 169 pre-flop hands + made-hand-strength buckets
  post-flop). The post-flop abstraction ignores draw potential — a documented
  approximation that trades some strength for the speed needed to train in pure
  Python.
- The betting tree's *structure* is card-independent, so it is **compiled once**
  and each Monte-Carlo deal only plugs in the showdown winner and the card
  buckets — about a 20× speedup over walking game objects.

See `EVALUATION.md` for the latest numbers.
