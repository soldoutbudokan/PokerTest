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
import time
from itertools import combinations
from typing import Dict, List, Optional

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

# Budget for the *search* (river re-solving) evaluation.  Its cost is dominated
# by re-solving river subgames; solves are cached per ``(board, river_root)`` so
# using a fixed pool of boards caps the number of distinct solves independently
# of the exploiter iteration count.  The blueprint and search bots are always
# measured on the SAME pool/budget so the delta isolates search's effect.
#   (pool_boards, exploiter_iters, eval_hands, solver_iters, arena_pairs)
# The exploiter needs enough iterations to reach a non-negative (converged)
# best-response value (the BR invariant); on the fixed pool the extra iterations
# are cheap because subgame solves are already cached.
SEARCH_LEVELS = {
    "quick":    (32, 40000, 6000, 150, 250),
    "standard": (64, 150000, 8000, 200, 500),
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


def _board_pool_dealer(n: int, seed: int):
    """A fixed pool of ``n`` boards and a deal fn that draws a pool board plus
    random (disjoint) hole cards.  Fixing the board set caps the number of
    distinct subgame solves, so search evaluation is bounded."""
    r = random.Random(seed)
    pool = [tuple(r.sample(range(52), 5)) for _ in range(n)]

    def deal_fn(rng: random.Random):
        board = pool[rng.randrange(len(pool))]
        board_set = set(board)
        deck = [c for c in range(52) if c not in board_set]
        rng.shuffle(deck)
        return ((deck[0], deck[1]), (deck[2], deck[3])), board

    return pool, deal_fn


def _pool_exploitability(g, bot, tree, deal_fn, exploiter_iters, eval_hands,
                         seed, solver=None) -> float:
    """Two-seat best-response exploitability of ``bot`` on the pool (bb/100).

    With ``solver`` given, the bot's *river* nodes are re-solved (search bot);
    with ``solver=None`` it is the plain blueprint on the same boards/seeds — so
    the two are a paired comparison."""
    from .solve.nlhe_tree import FastExploiterCFR, matchup_value
    ex0 = FastExploiterCFR(g, bot, exploiter=0, tree=tree, search=solver,
                           deal_fn=deal_fn)
    ex0.run(exploiter_iters, random.Random(seed + 1))
    e0, _ = matchup_value(g, ex0.average_strategy(), bot, eval_hands,
                          random.Random(seed + 11), tree=tree, search=solver,
                          search_seats=(1,), deal_fn=deal_fn)
    ex1 = FastExploiterCFR(g, bot, exploiter=1, tree=tree, search=solver,
                           deal_fn=deal_fn)
    ex1.run(exploiter_iters, random.Random(seed + 2))
    e1, _ = matchup_value(g, bot, ex1.average_strategy(), eval_hands,
                          random.Random(seed + 22), tree=tree, search=solver,
                          search_seats=(0,), deal_fn=deal_fn)
    return (e0 * 100.0 - e1 * 100.0) / 2.0


def _search_metrics(g, tree, bot, seed: int, params) -> Dict:
    """Measure blueprint vs blueprint+search on a shared board pool + budget."""
    from .agents.search import SearchAgent
    from .solve.subgame import RiverSubgameSolver
    pool_n, expl_iters, eval_hands, solver_iters, arena_pairs = params
    t0 = time.time()
    _, deal_fn = _board_pool_dealer(pool_n, seed + 101)

    # Same seeds/boards for both; the only difference is the river re-solve.
    bl = _pool_exploitability(g, bot, tree, deal_fn, expl_iters, eval_hands,
                              seed + 200, solver=None)
    solver = RiverSubgameSolver(g, bot, tree=tree, iterations=solver_iters)
    se = _pool_exploitability(g, bot, tree, deal_fn, expl_iters, eval_hands,
                              seed + 200, solver=solver)

    # Search bot win-rates vs the baseline panel (full random deals).
    sbot = SearchAgent(bot, g, tree=tree, iterations=solver_iters, solver=solver)
    baselines = {}
    for opp in (RandomAgent(), CallStationAgent(), AlwaysRaiseAgent(),
                TightAggressiveAgent()):
        res = play_match(g, sbot, opp, num_pairs=arena_pairs, seed=seed + 5)
        baselines[opp.name] = {"bb100": res.bb_per_100,
                               "ci95": res.ci95_bb_per_100,
                               "significant": res.significant}
    return {
        "pool_size": pool_n, "exploiter_iters": expl_iters,
        "eval_hands": eval_hands, "solver_iters": solver_iters,
        "arena_pairs": arena_pairs,
        "blueprint_pool_bb100": bl, "search_pool_bb100": se,
        "delta_bb100": se - bl, "baselines": baselines,
        "solves": solver.solves, "seconds": time.time() - t0,
    }


def nlhe_metrics(train_iters: int, eval_pairs: int, expl_max: int,
                 expl_eval: int, pf_train: int, seed: int = 0,
                 search: bool = False, search_params=None) -> Dict:
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

    out = {
        "config": {"stack": 20.0, "bet_sizes": list(cfg.bet_sizes),
                   "max_raises": cfg.max_raises_per_street},
        "train_iters": train_iters, "infosets": len(trainer.nodes),
        "baselines": baselines, "exploit_curve": exploit_curve,
        "exploitability_bb100": exploitability_bb100,
        "pushfold": {"jam": jam, "jam_pct": jam_pct},
        "preflop": preflop,
        # Populated only when search is enabled; kept as a key so downstream
        # consumers can rely on its presence.
        "exploitability_search_bb100": None,
        "search": None,
    }
    if search:
        out["search"] = _search_metrics(g, tree, bot, seed, search_params)
        out["exploitability_search_bb100"] = out["search"]["search_pool_bb100"]
    return out


def compute_metrics(level: str = "standard", seed: int = 0,
                    search: bool = False,
                    search_level: str = "standard") -> Dict:
    k, l, tr, ep, em, ee, pf = LEVELS[level]
    search_params = SEARCH_LEVELS[search_level] if search else None
    return {
        "level": level,
        "search_level": search_level if search else None,
        "evaluator": evaluator_metrics(),
        "kuhn": kuhn_metrics(k),
        "leduc": leduc_metrics(l),
        "nlhe": nlhe_metrics(tr, ep, em, ee, pf, seed=seed, search=search,
                             search_params=search_params),
    }


def flatten(metrics: Dict) -> Dict:
    n = metrics["nlhe"]
    # Blueprint+search exploitability is only present on search runs; keep it as
    # an empty cell otherwise so past (blueprint-only) rows stay comparable and
    # the ``nlhe_exploitability_bb100`` column is never silently redefined.
    se = n.get("exploitability_search_bb100")
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
        "nlhe_exploitability_search_bb100":
            round(se, 3) if se is not None else "",
    }


HISTORY_COLUMNS = ["date", "level", "kuhn_exploitability", "leduc_exploitability",
                   "nlhe_exploitability_bb100", "nlhe_infosets", "win_vs_random",
                   "win_vs_call_station", "win_vs_maniac",
                   "win_vs_tight_aggressive", "pushfold_jam_pct",
                   "nlhe_exploitability_search_bb100"]


def append_history(summary: Dict, date: str,
                   path: str = "metrics_history.csv") -> None:
    """Append a dated metrics row (creating the file with a header if needed).

    If the file already exists with an *older* header (a column was added since
    it was written), it is migrated in place: the header is extended and past
    rows are padded with empty cells for the new columns.  Existing values are
    never changed — this only extends the schema so old and new rows stay in one
    comparable table."""
    row = {"date": date, **summary}
    if os.path.exists(path):
        with open(path, newline="") as f:
            reader = csv.reader(f)
            old = next(reader, None)
            if old is not None and old != HISTORY_COLUMNS:
                f.seek(0)
                rows = list(csv.DictReader(f))
                with open(path, "w", newline="") as out:
                    w = csv.DictWriter(out, fieldnames=HISTORY_COLUMNS)
                    w.writeheader()
                    for r in rows:
                        w.writerow({k: r.get(k, "") for k in HISTORY_COLUMNS})
    exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in HISTORY_COLUMNS})
