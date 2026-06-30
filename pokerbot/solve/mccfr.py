"""Monte-Carlo CFR (chance sampling) for No-Limit Hold'em.

Each iteration samples one full deal (hole cards + board) and runs a complete
CFR traversal of that deal's betting tree, which is small and deterministic.
Sampling deals uniformly makes the accumulated updates an unbiased estimate of
full CFR, while keeping per-iteration cost tiny.  Updates are simultaneous
(both players at their own nodes) and use CFR+ style regret-matching-plus with
linear strategy averaging — both applied lazily per visited node, so there is
no global sweep over the (large) information-set table.

The per-deal information-set buckets are precomputed once per deal (2 players x
4 streets), instead of re-evaluating the hand at every node, which is the main
speed win.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from ..games.nlhe import NLHEGame, NLHEState, RIVER
from .cfr import TabularStrategy


class _Node:
    __slots__ = ("legal", "regret_sum", "strategy_sum")

    def __init__(self, legal: List[int]):
        self.legal = legal
        n = len(legal)
        self.regret_sum = [0.0] * n
        self.strategy_sum = [0.0] * n

    def strategy(self) -> List[float]:
        pos_total = 0.0
        for r in self.regret_sum:
            if r > 0.0:
                pos_total += r
        n = len(self.legal)
        if pos_total > 0.0:
            return [(r / pos_total if r > 0.0 else 0.0) for r in self.regret_sum]
        return [1.0 / n] * n

    def average(self) -> List[float]:
        total = sum(self.strategy_sum)
        n = len(self.legal)
        if total > 0.0:
            return [s / total for s in self.strategy_sum]
        return [1.0 / n] * n


class ChanceSampledCFR:
    def __init__(self, game: NLHEGame):
        self.game = game
        self.nodes: Dict[str, _Node] = {}
        self.iterations = 0

    def _node(self, key: str, legal: List[int]) -> _Node:
        node = self.nodes.get(key)
        if node is None:
            node = _Node(legal)
            self.nodes[key] = node
        return node

    def run(self, iterations: int, rng: Optional[random.Random] = None) -> None:
        rng = rng or random.Random()
        ab = self.game.abstraction
        for _ in range(iterations):
            self.iterations += 1
            deal = self.game.deal(rng)
            hole, board = deal
            # Precompute buckets: (player, street) -> bucket.
            buckets = {}
            for p in (0, 1):
                for st in (0, 1, 2, 3):
                    buckets[(p, st)] = ab.bucket(hole[p], board, st)
            root = self.game.new_initial_state(deal)
            self._cfr(root, 1.0, 1.0, float(self.iterations), buckets)

    def _cfr(self, state: NLHEState, r0: float, r1: float, t: float,
             buckets) -> List[float]:
        if state.is_terminal():
            return state.returns()

        player = state.current_player()
        eff_st = state.street if state.street >= 0 else RIVER
        key = f"{buckets[(player, eff_st)]}|{state.hist}"
        legal = state.legal_actions()
        node = self._node(key, legal)
        strat = node.strategy()
        n = len(legal)

        util0 = [0.0] * n
        util1 = [0.0] * n
        nv0 = nv1 = 0.0
        for i in range(n):
            si = strat[i]
            child = state.apply_action(legal[i])
            if player == 0:
                cv = self._cfr(child, r0 * si, r1, t, buckets)
            else:
                cv = self._cfr(child, r0, r1 * si, t, buckets)
            util0[i] = cv[0]
            util1[i] = cv[1]
            nv0 += si * cv[0]
            nv1 += si * cv[1]

        # Simultaneous CFR+ update at the acting player's node.
        rs = node.regret_sum
        ss = node.strategy_sum
        if player == 0:
            cf = r1
            for i in range(n):
                v = rs[i] + cf * (util0[i] - nv0)
                rs[i] = v if v > 0.0 else 0.0      # regret-matching-plus
                ss[i] += t * r0 * strat[i]         # linear averaging
        else:
            cf = r0
            for i in range(n):
                v = rs[i] + cf * (util1[i] - nv1)
                rs[i] = v if v > 0.0 else 0.0
                ss[i] += t * r1 * strat[i]
        return [nv0, nv1]

    def average_strategy(self) -> TabularStrategy:
        table: Dict[str, Dict[int, float]] = {}
        for key, node in self.nodes.items():
            avg = node.average()
            table[key] = {a: avg[i] for i, a in enumerate(node.legal)}
        return TabularStrategy(table)


class ExploiterCFR:
    """Trains a best response to a *fixed* opponent strategy via MCCFR.

    Only ``exploiter`` updates regrets; the other player plays ``fixed`` at every
    node.  The exploiter's average strategy converges to a best response within
    the action/card abstraction, so its win rate against the fixed bot is a
    lower bound on the bot's exploitability.
    """

    def __init__(self, game: NLHEGame, fixed: TabularStrategy,
                 exploiter: int):
        self.game = game
        self.fixed = fixed
        self.exploiter = exploiter
        self.nodes: Dict[str, _Node] = {}
        self.iterations = 0

    def _node(self, key: str, legal: List[int]) -> _Node:
        node = self.nodes.get(key)
        if node is None:
            node = _Node(legal)
            self.nodes[key] = node
        return node

    def run(self, iterations: int, rng: Optional[random.Random] = None) -> None:
        rng = rng or random.Random()
        ab = self.game.abstraction
        for _ in range(iterations):
            self.iterations += 1
            deal = self.game.deal(rng)
            hole, board = deal
            buckets = {}
            for p in (0, 1):
                for st in (0, 1, 2, 3):
                    buckets[(p, st)] = ab.bucket(hole[p], board, st)
            root = self.game.new_initial_state(deal)
            self._cfr(root, 1.0, 1.0, float(self.iterations), buckets)

    def _cfr(self, state, reach_exp, reach_opp, t, buckets):
        if state.is_terminal():
            return state.returns()[self.exploiter]
        player = state.current_player()
        eff_st = state.street if state.street >= 0 else RIVER
        key = f"{buckets[(player, eff_st)]}|{state.hist}"
        legal = state.legal_actions()

        if player != self.exploiter:
            probs = self.fixed.action_probs(key, legal)
            value = 0.0
            for a in legal:
                p = probs.get(a, 0.0)
                if p > 0.0:
                    value += p * self._cfr(state.apply_action(a), reach_exp,
                                           reach_opp * p, t, buckets)
            return value

        node = self._node(key, legal)
        strat = node.strategy()
        n = len(legal)
        util = [0.0] * n
        nv = 0.0
        for i in range(n):
            util[i] = self._cfr(state.apply_action(legal[i]),
                                reach_exp * strat[i], reach_opp, t, buckets)
            nv += strat[i] * util[i]
        rs = node.regret_sum
        ss = node.strategy_sum
        for i in range(n):
            v = rs[i] + reach_opp * (util[i] - nv)   # cf reach = opponent reach
            rs[i] = v if v > 0.0 else 0.0
            ss[i] += t * reach_exp * strat[i]
        return nv

    def average_strategy(self) -> TabularStrategy:
        table: Dict[str, Dict[int, float]] = {}
        for key, node in self.nodes.items():
            avg = node.average()
            table[key] = {a: avg[i] for i, a in enumerate(node.legal)}
        return TabularStrategy(table)

