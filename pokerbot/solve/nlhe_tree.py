"""Compiled-betting-tree MCCFR for No-Limit Hold'em (fast path).

The betting tree's *structure* — legal actions, transitions, pot sizes, fold
payoffs — depends only on the chips in play, never on the cards.  Only the
showdown winner and the information-set buckets depend on the deal.  So we
compile the betting tree once and, per sampled deal, merely

* compute the showdown winner sign (one comparison, lazily, only if a showdown
  is reached), and
* look up the 8 card buckets (2 players x 4 streets, lazily).

This removes all per-node game-object allocation, hand evaluation and string
formatting from the inner loop, giving a ~20x speedup over walking ``NLHEState``
directly.  The exported average strategy uses the same ``"{bucket}|{history}"``
keys as :meth:`NLHEState.information_set_key`, so a :class:`StrategyAgent` plays
it directly.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from ..evaluator import evaluate
from ..games.nlhe import RIVER, NLHEGame
from .cfr import TabularStrategy
from .mccfr import _Node

FOLD_T, SHOWDOWN_T, DECISION = 0, 1, 2


class CompiledBettingTree:
    def __init__(self) -> None:
        self.kind: List[int] = []
        self.fold_payoff0: List[float] = []
        self.stake: List[float] = []
        self.dec_player: List[int] = []
        self.dec_street: List[int] = []
        self.dec_actions: List[List[int]] = []
        self.dec_children: List[List[int]] = []
        self.dec_hist: List[str] = []
        self.root: int = -1

    def _new(self, kind: int) -> int:
        nid = len(self.kind)
        self.kind.append(kind)
        self.fold_payoff0.append(0.0)
        self.stake.append(0.0)
        self.dec_player.append(-1)
        self.dec_street.append(-1)
        self.dec_actions.append([])
        self.dec_children.append([])
        self.dec_hist.append("")
        return nid

    @staticmethod
    def build(game: NLHEGame) -> "CompiledBettingTree":
        t = CompiledBettingTree()
        dummy = (((0, 1), (2, 3)), (4, 5, 6, 7, 8))   # distinct placeholder cards
        t.root = t._add(game.new_initial_state(dummy))
        return t

    def _add(self, state) -> int:
        if state.is_terminal():
            if state.folder != -1:
                nid = self._new(FOLD_T)
                self.fold_payoff0[nid] = state.returns()[0]   # card-independent
                return nid
            nid = self._new(SHOWDOWN_T)
            self.stake[nid] = min(state.contrib)
            return nid
        nid = self._new(DECISION)
        self.dec_player[nid] = state.current_player()
        self.dec_street[nid] = state.street
        self.dec_hist[nid] = state.hist
        legal = state.legal_actions()
        self.dec_actions[nid] = legal
        self.dec_children[nid] = [self._add(state.apply_action(a)) for a in legal]
        return nid

    @property
    def num_nodes(self) -> int:
        return len(self.kind)


class FastNLHECFR:
    """Chance-sampling CFR+ over the compiled betting tree."""

    def __init__(self, game: NLHEGame, tree: Optional[CompiledBettingTree] = None):
        self.game = game
        self.tree = tree or CompiledBettingTree.build(game)
        self.nodes: Dict[Tuple[int, object], _Node] = {}
        self.iterations = 0

    def run(self, iterations: int, rng: Optional[random.Random] = None) -> None:
        rng = rng or random.Random()
        ab = self.game.abstraction
        deal = self.game.deal
        root = self.tree.root
        for _ in range(iterations):
            self.iterations += 1
            hole, board = deal(rng)
            self._cfr(root, 1.0, 1.0, float(self.iterations), hole, board,
                      ab, {}, [None])

    def _cfr(self, nid, r0, r1, t, hole, board, ab, bucket_cache, sign):
        tree = self.tree
        kind = tree.kind[nid]
        if kind == FOLD_T:
            p0 = tree.fold_payoff0[nid]
            return p0, -p0
        if kind == SHOWDOWN_T:
            if sign[0] is None:
                s0 = evaluate(list(hole[0]) + list(board))
                s1 = evaluate(list(hole[1]) + list(board))
                sign[0] = 1 if s0 > s1 else (-1 if s1 > s0 else 0)
            p0 = sign[0] * tree.stake[nid]
            return p0, -p0

        player = tree.dec_player[nid]
        street = tree.dec_street[nid]
        bkey = (player, street)
        bucket = bucket_cache.get(bkey)
        if bucket is None:
            bucket = ab.bucket(hole[player], board, street)
            bucket_cache[bkey] = bucket
        ikey = (nid, bucket)
        node = self.nodes.get(ikey)
        if node is None:
            node = _Node(tree.dec_actions[nid])
            self.nodes[ikey] = node
        strat = node.strategy()
        children = tree.dec_children[nid]
        n = len(children)

        util0 = [0.0] * n
        util1 = [0.0] * n
        nv0 = nv1 = 0.0
        for i in range(n):
            si = strat[i]
            if player == 0:
                c0, c1 = self._cfr(children[i], r0 * si, r1, t, hole, board,
                                   ab, bucket_cache, sign)
            else:
                c0, c1 = self._cfr(children[i], r0, r1 * si, t, hole, board,
                                   ab, bucket_cache, sign)
            util0[i] = c0
            util1[i] = c1
            nv0 += si * c0
            nv1 += si * c1

        rs = node.regret_sum
        ss = node.strategy_sum
        if player == 0:
            cf = r1
            for i in range(n):
                v = rs[i] + cf * (util0[i] - nv0)
                rs[i] = v if v > 0.0 else 0.0
                ss[i] += t * r0 * strat[i]
        else:
            cf = r0
            for i in range(n):
                v = rs[i] + cf * (util1[i] - nv1)
                rs[i] = v if v > 0.0 else 0.0
                ss[i] += t * r1 * strat[i]
        return nv0, nv1

    def average_strategy(self) -> TabularStrategy:
        tree = self.tree
        table: Dict[str, Dict[int, float]] = {}
        for (nid, bucket), node in self.nodes.items():
            key = f"{bucket}|{tree.dec_hist[nid]}"
            avg = node.average()
            table[key] = {a: avg[i] for i, a in enumerate(node.legal)}
        return TabularStrategy(table)


def matchup_value(game: NLHEGame, strat0: TabularStrategy,
                  strat1: TabularStrategy, num_deals: int,
                  rng: Optional[random.Random] = None,
                  tree: Optional[CompiledBettingTree] = None):
    """Expected bb/hand to player 0 when seat 0 plays ``strat0``, seat 1
    ``strat1``.

    Both players' action distributions are enumerated exactly per deal (only the
    cards are sampled), so this has far lower variance than playing out sampled
    hands — ideal for measuring small edges like exploitability.  Returns
    ``(mean_bb_per_hand, stderr_bb_per_hand)``.
    """
    import math
    rng = rng or random.Random()
    tree = tree or CompiledBettingTree.build(game)
    ab = game.abstraction

    def ev(nid, hole, board, bucket_cache, sign):
        kind = tree.kind[nid]
        if kind == FOLD_T:
            return tree.fold_payoff0[nid]
        if kind == SHOWDOWN_T:
            if sign[0] is None:
                s0 = evaluate(list(hole[0]) + list(board))
                s1 = evaluate(list(hole[1]) + list(board))
                sign[0] = 1 if s0 > s1 else (-1 if s1 > s0 else 0)
            return sign[0] * tree.stake[nid]
        player = tree.dec_player[nid]
        street = tree.dec_street[nid]
        bkey = (player, street)
        bucket = bucket_cache.get(bkey)
        if bucket is None:
            bucket = ab.bucket(hole[player], board, street)
            bucket_cache[bkey] = bucket
        actions = tree.dec_actions[nid]
        key = f"{bucket}|{tree.dec_hist[nid]}"
        probs = (strat0 if player == 0 else strat1).action_probs(key, actions)
        v = 0.0
        for i, ci in enumerate(tree.dec_children[nid]):
            p = probs.get(actions[i], 0.0)
            if p > 0.0:
                v += p * ev(ci, hole, board, bucket_cache, sign)
        return v

    total = 0.0
    sq = 0.0
    for _ in range(num_deals):
        hole, board = game.deal(rng)
        x = ev(tree.root, hole, board, {}, [None])
        total += x
        sq += x * x
    mean = total / num_deals
    if num_deals > 1:
        # Unbiased sample variance (n-1 denominator) for the standard error.
        var = max(0.0, (sq - num_deals * mean * mean) / (num_deals - 1))
        return mean, math.sqrt(var / num_deals)
    return mean, float("inf")


class FastExploiterCFR:
    """Best response to a fixed strategy over the compiled betting tree."""

    def __init__(self, game: NLHEGame, fixed: TabularStrategy, exploiter: int,
                 tree: Optional[CompiledBettingTree] = None):
        self.game = game
        self.fixed = fixed
        self.exploiter = exploiter
        self.tree = tree or CompiledBettingTree.build(game)
        self.nodes: Dict[Tuple[int, object], _Node] = {}
        self.iterations = 0

    def run(self, iterations: int, rng: Optional[random.Random] = None) -> None:
        rng = rng or random.Random()
        ab = self.game.abstraction
        deal = self.game.deal
        root = self.tree.root
        for _ in range(iterations):
            self.iterations += 1
            hole, board = deal(rng)
            self._cfr(root, 1.0, 1.0, float(self.iterations), hole, board, ab,
                      {}, [None])

    def _cfr(self, nid, reach_exp, reach_opp, t, hole, board, ab, bucket_cache,
             sign):
        tree = self.tree
        kind = tree.kind[nid]
        if kind == FOLD_T:
            p0 = tree.fold_payoff0[nid]
            return p0 if self.exploiter == 0 else -p0
        if kind == SHOWDOWN_T:
            if sign[0] is None:
                s0 = evaluate(list(hole[0]) + list(board))
                s1 = evaluate(list(hole[1]) + list(board))
                sign[0] = 1 if s0 > s1 else (-1 if s1 > s0 else 0)
            p0 = sign[0] * tree.stake[nid]
            return p0 if self.exploiter == 0 else -p0

        player = tree.dec_player[nid]
        street = tree.dec_street[nid]
        bkey = (player, street)
        bucket = bucket_cache.get(bkey)
        if bucket is None:
            bucket = ab.bucket(hole[player], board, street)
            bucket_cache[bkey] = bucket
        children = tree.dec_children[nid]
        actions = tree.dec_actions[nid]

        if player != self.exploiter:
            key = f"{bucket}|{tree.dec_hist[nid]}"
            probs = self.fixed.action_probs(key, actions)
            value = 0.0
            for i in range(len(children)):
                p = probs.get(actions[i], 0.0)
                if p > 0.0:
                    value += p * self._cfr(children[i], reach_exp, reach_opp * p,
                                           t, hole, board, ab, bucket_cache, sign)
            return value

        ikey = (nid, bucket)
        node = self.nodes.get(ikey)
        if node is None:
            node = _Node(actions)
            self.nodes[ikey] = node
        strat = node.strategy()
        n = len(children)
        util = [0.0] * n
        nv = 0.0
        for i in range(n):
            util[i] = self._cfr(children[i], reach_exp * strat[i], reach_opp, t,
                                hole, board, ab, bucket_cache, sign)
            nv += strat[i] * util[i]
        rs = node.regret_sum
        ss = node.strategy_sum
        for i in range(n):
            # Counterfactual reach for a best response is the fixed opponent's
            # reach to this node (chance is sampled, so its reach is 1).
            v = rs[i] + reach_opp * (util[i] - nv)
            rs[i] = v if v > 0.0 else 0.0
            ss[i] += t * reach_exp * strat[i]
        return nv

    def average_strategy(self) -> TabularStrategy:
        tree = self.tree
        table: Dict[str, Dict[int, float]] = {}
        for (nid, bucket), node in self.nodes.items():
            key = f"{bucket}|{tree.dec_hist[nid]}"
            avg = node.average()
            table[key] = {a: avg[i] for i, a in enumerate(node.legal)}
        return TabularStrategy(table)

