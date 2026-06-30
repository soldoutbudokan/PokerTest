"""Compute the bot's objective metrics in one place.

Everything that measures "how good the bot is" lives here so the report
(:mod:`pokerbot.evaluate`), the visualizations (:mod:`pokerbot.visualize`) and
the daily-improvement routine all read the *same* numbers.

``compute_metrics(level=...)`` returns a nested dict:

```
{
  "evaluator": {"counts": {...}, "ok": bool},
  "kuhn":   {"curve": [[iter, expl, value], ...], "exploitability", "game_value"},
  "leduc":  {"curve": [[iter, expl], ...], "exploitability", "infosets"},
  "nlhe":   {
     "config", "train_iters", "infosets",
     "baselines": {name: {"bb100", "ci95", "significant"}},
     "exploit_curve": [[br_iters, br_bb100], ...],
     "exploitability_bb100",
     "pushfold": {"jam": {hand: freq}, "jam_pct"},
     "preflop": {hand: {action_label: prob}},
  },
}
```

``flatten(metrics)`` returns a flat one-row summary and ``append_history`` writes
it (with a date) to ``metrics_history.csv`` for the progress-over-time chart.
"""
from __future__ import annotations

import csv
import os
import random
from itertools import combinations
from typing import Dict, List

from .agents.base import StrategyAgent
from .agents.baselines import (AlwaysRaiseAgent, CallStationAgent, RandomAgent,
                               TightAggressiveAgent)
from .cards import RANKS
from .eval.arena import play_match
from .evaluator import CATEGORY_NAMES, category_of, eval5
from .games.kuhn import KuhnPoker
from .games.leduc import LeducPoker
from .games.nlhe import ALL_IN, CALL, FOLD, RAISE_BASE, NLHEConfig, NLHEGame
from .games.nlhe_abstraction import StrengthAbstraction, preflop_index
from .solve.cfr import CFRSolver
from .solve.exploitability import exploitability as kuhn_exploit
from .solve.exploitability import expected_value
from .solve.nlhe_tree import (CompiledBettingTree, FastExploiterCFR,
                              FastNLHECFR, matchup_value)
from .solve.tree import GameTree, TreeCFR
from .solve.tree import exploitability as tree_exploit

LEVELS = {
    # (kuhn, leduc, nlhe_train, eval_pairs, expl_max, expl_eval, pf_train)
    "quick":    (3000, 8000, 40000, 2000, 60000, 20000, 100000),
    "standard": (8000, 30000, 120000, 5000, 150000, 50000, 250000),
    "full":     (20000, 60000, 250000, 10000, 250000, 60000, 400000),
}


def _log_milestones(n: int) -> List[int]:
    out, step = [], 1
    while step <= n:
        for m in (1, 2, 5):
            v = step * m
            if v <= n and v not in out:
                out.append(v)
        step *= 10
    if n not in out:
        out.append(n)
    return sorted(out)


def _hand_name(idx: int) -> str:
    if idx < 13:
        return RANKS[idx] + RANKS[idx]
    i2 = idx - 13 if idx < 91 else idx - 91
    hi = 1
    while hi * (hi + 1) // 2 <= i2:
        hi += 1
    lo = i2 - hi * (hi - 1) // 2
    return RANKS[hi] + RANKS[lo] + ("s" if idx < 91 else "o")


def evaluator_metrics() -> Dict:
    from collections import Counter
    counts = Counter()
    for combo in combinations(range(52), 5):
        counts[category_of(eval5(combo))] += 1
    expected = [1302540, 1098240, 123552, 54912, 10200, 5108, 3744, 624, 40]
    by_name = {CATEGORY_NAMES[c]: counts[c] for c in range(9)}
    ok = all(counts[c] == expected[c] for c in range(9))
    return {"counts": by_name, "expected": dict(zip(CATEGORY_NAMES, expected)),
            "ok": ok}


def kuhn_metrics(iters: int) -> Dict:
    g = KuhnPoker()
    s = CFRSolver(g, variant="dcfr")
    curve = []
    for m in _log_milestones(iters):
        while s.iterations < m:
            s.run(1)
        strat = s.average_strategy()
        curve.append([m, kuhn_exploit(g, strat), expected_value(g, strat)])
    strat = s.average_strategy()
    return {"curve": curve, "exploitability": curve[-1][1],
            "game_value": expected_value(g, strat),
            "analytic_value": -1.0 / 18.0}


def leduc_metrics(iters: int) -> Dict:
    tree = GameTree.build(LeducPoker())
    s = TreeCFR(tree, variant="dcfr")
    curve = []
    for m in _log_milestones(iters):
        while s.iterations < m:
            s.run(1)
        curve.append([m, tree_exploit(tree, s.average_strategy())])
    return {"curve": curve, "exploitability": curve[-1][1],
            "infosets": tree.num_infosets, "nodes": tree.num_nodes}


def nlhe_metrics(train_iters: int, eval_pairs: int, expl_max: int,
                 expl_eval: int, pf_train: int, seed: int = 0) -> Dict:
    cfg = NLHEConfig(stack=20.0, bet_sizes=(1.0,), max_raises_per_street=3)
    ab = StrengthAbstraction(postflop_buckets=8)
    g = NLHEGame(cfg, ab)
    tree = CompiledBettingTree.build(g)
    trainer = FastNLHECFR(g, tree)
    trainer.run(train_iters, random.Random(seed))
    bot = trainer.average_strategy()
    bot_agent = StrategyAgent(bot, "cfr-bot")

    baselines = {}
    for opp in (RandomAgent(), CallStationAgent(), AlwaysRaiseAgent(),
                TightAggressiveAgent()):
        res = play_match(g, bot_agent, opp, num_pairs=eval_pairs, seed=seed + 5)
        baselines[opp.name] = {"bb100": res.bb_per_100,
                               "ci95": res.ci95_bb_per_100,
                               "significant": res.significant}

    # Best-response exploitability as a function of BR training (lower bound that
    # rises toward the true value as the responder is trained longer).
    exploit_curve = []
    ms = [m for m in (10000, 25000, 50000, 100000, 150000, 200000, 250000)
          if m <= expl_max]
    if expl_max not in ms:
        ms.append(expl_max)
    ms = sorted(set(ms))
    ex0 = FastExploiterCFR(g, bot, exploiter=0, tree=tree)
    ex1 = FastExploiterCFR(g, bot, exploiter=1, tree=tree)
    rng0, rng1 = random.Random(seed + 1), random.Random(seed + 2)
    for m in ms:
        while ex0.iterations < m:
            ex0.run(m - ex0.iterations, rng0)
        while ex1.iterations < m:
            ex1.run(m - ex1.iterations, rng1)
        e0, _ = matchup_value(g, ex0.average_strategy(), bot, expl_eval,
                              random.Random(seed + 11), tree=tree)
        e1, _ = matchup_value(g, bot, ex1.average_strategy(), expl_eval,
                              random.Random(seed + 22), tree=tree)
        exploit_curve.append([m, (e0 * 100.0 - e1 * 100.0) / 2.0])
    exploitability_bb100 = exploit_curve[-1][1]

    # Push/fold (10 BB) jam grid + the deep-stack bot's pre-flop SB strategy.
    pf_g = NLHEGame(NLHEConfig(stack=10.0, bet_sizes=(), push_fold=True), ab)
    pf = FastNLHECFR(pf_g)
    pf.run(pf_train, random.Random(seed + 7))
    pf_strat = pf.average_strategy()
    jam = {}
    for idx in range(169):
        probs = pf_strat.table.get(f"{idx}|", {})
        jam[_hand_name(idx)] = probs.get(ALL_IN, 0.0)
    jam_pct = 100.0 * sum(1 for v in jam.values() if v > 0.5) / 169.0

    preflop = {}
    labels = {FOLD: "fold", CALL: "call", ALL_IN: "allin"}
    for i in range(len(cfg.bet_sizes)):
        labels[RAISE_BASE + i] = f"raise{cfg.bet_sizes[i]:g}pot"
    for idx in range(169):
        probs = bot.table.get(f"{idx}|", {})
        preflop[_hand_name(idx)] = {labels.get(a, str(a)): p
                                    for a, p in probs.items()}

    return {
        "config": {"stack": 20.0, "bet_sizes": list(cfg.bet_sizes),
                   "max_raises": cfg.max_raises_per_street},
        "train_iters": train_iters, "infosets": len(trainer.nodes),
        "baselines": baselines, "exploit_curve": exploit_curve,
        "exploitability_bb100": exploitability_bb100,
        "pushfold": {"jam": jam, "jam_pct": jam_pct},
        "preflop": preflop,
    }


def compute_metrics(level: str = "standard", seed: int = 0) -> Dict:
    k, l, tr, ep, em, ee, pf = LEVELS[level]
    return {
        "level": level,
        "evaluator": evaluator_metrics(),
        "kuhn": kuhn_metrics(k),
        "leduc": leduc_metrics(l),
        "nlhe": nlhe_metrics(tr, ep, em, ee, pf, seed=seed),
    }


def flatten(metrics: Dict) -> Dict:
    n = metrics["nlhe"]
    return {
        "level": metrics["level"],
        "kuhn_exploitability": round(metrics["kuhn"]["exploitability"], 6),
        "leduc_exploitability": round(metrics["leduc"]["exploitability"], 6),
        "nlhe_exploitability_bb100": round(n["exploitability_bb100"], 3),
        "nlhe_infosets": n["infosets"],
        "win_vs_random": round(n["baselines"]["random"]["bb100"], 2),
        "win_vs_call_station": round(n["baselines"]["call-station"]["bb100"], 2),
        "win_vs_maniac": round(n["baselines"]["maniac"]["bb100"], 2),
        "win_vs_tight_aggressive":
            round(n["baselines"]["tight-aggressive"]["bb100"], 2),
        "pushfold_jam_pct": round(n["pushfold"]["jam_pct"], 1),
    }


HISTORY_COLUMNS = ["date", "level", "kuhn_exploitability", "leduc_exploitability",
                   "nlhe_exploitability_bb100", "nlhe_infosets", "win_vs_random",
                   "win_vs_call_station", "win_vs_maniac",
                   "win_vs_tight_aggressive", "pushfold_jam_pct"]


def append_history(summary: Dict, date: str,
                   path: str = "metrics_history.csv") -> None:
    """Append a dated metrics row (creating the file with a header if needed)."""
    row = {"date": date, **summary}
    exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in HISTORY_COLUMNS})
