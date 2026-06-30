"""Counterfactual Regret Minimization over an explicit game tree.

Three regret-minimizing variants are supported, all of which converge to a Nash
equilibrium of a two-player zero-sum game; they differ only in how the
accumulated regrets and average-strategy weights are discounted between
iterations:

* ``vanilla`` – plain CFR (uniform averaging, no discounting).
* ``cfr+``    – regret-matching-plus (regrets floored at 0) with linear
  averaging.
* ``dcfr``    – Discounted CFR (Brown & Sandholm 2019), the default; positive
  regrets, negative regrets and the strategy sum get separate polynomial
  discounts ``(α, β, γ) = (1.5, 0, 2)``.  Empirically the fastest and most
  robust on Leduc-scale games.

Chance nodes are enumerated exactly, so this solver is used for Kuhn and Leduc,
where the resulting average strategy can be checked for ~0 exploitability.
Updates are *alternating*: each iteration runs one traversal per training
player.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..games.base import Game, GameState


class _Node:
    """Regret and strategy accumulators for one information set."""
    __slots__ = ("legal", "regret_sum", "strategy_sum")

    def __init__(self, legal: List[int]):
        self.legal = legal
        n = len(legal)
        self.regret_sum = [0.0] * n
        self.strategy_sum = [0.0] * n

    def current_strategy(self) -> List[float]:
        """Regret-matching strategy from current positive regrets."""
        pos = [r if r > 0.0 else 0.0 for r in self.regret_sum]
        total = sum(pos)
        n = len(self.legal)
        if total > 0.0:
            return [p / total for p in pos]
        return [1.0 / n] * n

    def average_strategy(self) -> List[float]:
        total = sum(self.strategy_sum)
        n = len(self.legal)
        if total > 0.0:
            return [s / total for s in self.strategy_sum]
        return [1.0 / n] * n


class TabularStrategy:
    """A fixed average strategy queried by information-set key."""

    def __init__(self, table: Dict[str, Dict[int, float]]):
        self.table = table

    def action_probs(self, key: str, legal: List[int]) -> Dict[int, float]:
        probs = self.table.get(key)
        if probs is None:
            return {a: 1.0 / len(legal) for a in legal}
        return probs

    def __len__(self) -> int:
        return len(self.table)

    def save(self, path: str) -> None:
        import json
        serial = {k: {str(a): p for a, p in v.items()}
                  for k, v in self.table.items()}
        with open(path, "w") as f:
            json.dump(serial, f)

    @staticmethod
    def load(path: str) -> "TabularStrategy":
        import json
        with open(path) as f:
            serial = json.load(f)
        table = {k: {int(a): p for a, p in v.items()}
                 for k, v in serial.items()}
        return TabularStrategy(table)


class CFRSolver:
    def __init__(self, game: Game, variant: str = "dcfr",
                 alpha: float = 1.5, beta: float = 0.0, gamma: float = 2.0,
                 alternating: bool = False):
        if variant not in ("vanilla", "cfr+", "dcfr", "linear"):
            raise ValueError(f"unknown variant {variant!r}")
        self.game = game
        self.variant = variant
        self.alpha, self.beta, self.gamma = alpha, beta, gamma
        # Alternating updates (one player per iteration) converge faster than
        # simultaneous updates and are the standard pairing for CFR+/DCFR.
        self.alternating = alternating
        self.nodes: Dict[str, _Node] = {}
        self.iterations = 0

    def _node(self, key: str, legal: List[int]) -> _Node:
        node = self.nodes.get(key)
        if node is None:
            node = _Node(legal)
            self.nodes[key] = node
        return node

    def run(self, iterations: int) -> None:
        for _ in range(iterations):
            self.iterations += 1
            if self.alternating:
                update_player = (self.iterations - 1) % 2
            else:
                update_player = None
            self._cfr(self.game.new_initial_state(), 1.0, 1.0, 1.0,
                      update_player)
            self._discount(self.iterations)

    def _discount(self, t: float) -> None:
        v = self.variant
        if v == "vanilla":
            return
        if v == "cfr+":
            strat_factor = t / (t + 1.0)
            for node in self.nodes.values():
                rs, ss = node.regret_sum, node.strategy_sum
                for i in range(len(rs)):
                    if rs[i] < 0.0:
                        rs[i] = 0.0            # regret-matching-plus
                    ss[i] *= strat_factor      # linear averaging
            return
        if v == "linear":
            f = t / (t + 1.0)
            for node in self.nodes.values():
                rs, ss = node.regret_sum, node.strategy_sum
                for i in range(len(rs)):
                    rs[i] *= f
                    ss[i] *= f
            return
        # dcfr
        ta = t ** self.alpha
        pos_factor = ta / (ta + 1.0)
        tb = t ** self.beta
        neg_factor = tb / (tb + 1.0)
        strat_factor = (t / (t + 1.0)) ** self.gamma
        for node in self.nodes.values():
            rs, ss = node.regret_sum, node.strategy_sum
            for i in range(len(rs)):
                rs[i] *= pos_factor if rs[i] > 0.0 else neg_factor
                ss[i] *= strat_factor

    def _cfr(self, state: GameState, r0: float, r1: float, rc: float,
             update_player) -> List[float]:
        """CFR traversal returning the utility vector ``[u0, u1]``.

        ``r0``/``r1`` are the players' reach probabilities and ``rc`` the chance
        reach to this node.  Regrets/strategy are accumulated for
        ``update_player`` only (``None`` updates both — simultaneous mode).
        """
        if state.is_terminal():
            return state.returns()

        if state.is_chance():
            value = [0.0, 0.0]
            for action, prob in state.chance_outcomes():
                cv = self._cfr(state.apply_action(action), r0, r1, rc * prob,
                               update_player)
                value[0] += prob * cv[0]
                value[1] += prob * cv[1]
            return value

        player = state.current_player()
        legal = state.legal_actions()
        node = self._node(state.information_set_key(), legal)
        strategy = node.current_strategy()

        util = [None] * len(legal)
        node_util = [0.0, 0.0]
        for i, action in enumerate(legal):
            child = state.apply_action(action)
            if player == 0:
                cv = self._cfr(child, r0 * strategy[i], r1, rc, update_player)
            else:
                cv = self._cfr(child, r0, r1 * strategy[i], rc, update_player)
            util[i] = cv
            node_util[0] += strategy[i] * cv[0]
            node_util[1] += strategy[i] * cv[1]

        if update_player is None or player == update_player:
            cf_reach = (r1 if player == 0 else r0) * rc   # counterfactual π^{-i}
            own_reach = r0 if player == 0 else r1
            nu = node_util[player]
            for i in range(len(legal)):
                node.regret_sum[i] += cf_reach * (util[i][player] - nu)
                node.strategy_sum[i] += own_reach * strategy[i]
        return node_util

    def average_strategy(self) -> TabularStrategy:
        table: Dict[str, Dict[int, float]] = {}
        for key, node in self.nodes.items():
            avg = node.average_strategy()
            table[key] = {a: avg[i] for i, a in enumerate(node.legal)}
        return TabularStrategy(table)

    def current_strategy(self) -> TabularStrategy:
        table: Dict[str, Dict[int, float]] = {}
        for key, node in self.nodes.items():
            cur = node.current_strategy()
            table[key] = {a: cur[i] for i, a in enumerate(node.legal)}
        return TabularStrategy(table)


def train(game: Game, iterations: int, variant: str = "dcfr",
          log_every: Optional[int] = None) -> CFRSolver:
    """Build a solver and run it, optionally logging exploitability."""
    solver = CFRSolver(game, variant=variant)
    if log_every:
        from .exploitability import exploitability
        done = 0
        while done < iterations:
            step = min(log_every, iterations - done)
            solver.run(step)
            done += step
            expl = exploitability(game, solver.average_strategy())
            print(f"  iter {done:6d}  exploitability {expl:.6f}")
    else:
        solver.run(iterations)
    return solver
