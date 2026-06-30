"""Flat compiled game tree + fast CFR/DCFR and exact best response.

For games whose tree we can enumerate (Kuhn, Leduc) it is far faster to compile
the tree once into integer-indexed arrays and run CFR over those, avoiding the
per-node Python object allocation of a fresh ``GameState`` walk.  The compiled
representation also gives every tree node a unique id, so best-response value
memoization is trivially correct (no information-set/signature aliasing).

``GameTree.build(game)`` walks the game once.  ``TreeCFR`` runs the same
vanilla / CFR+ / DCFR updates as :mod:`pokerbot.solve.cfr` but ~20x faster, and
``exploitability`` computes an exact best response on the flat tree.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..games.base import Game
from .cfr import TabularStrategy

# Node kinds.
TERMINAL, CHANCE, DECISION = 0, 1, 2


class GameTree:
    def __init__(self) -> None:
        self.kind: List[int] = []
        # Terminal: payoff to player 0 (zero-sum -> p1 = -p0).
        self.term_u0: List[float] = []
        # Chance: parallel lists of child ids and probabilities.
        self.chance_children: List[List[int]] = []
        self.chance_probs: List[List[float]] = []
        # Decision: acting player, infoset id, child id per legal action.
        self.dec_player: List[int] = []
        self.dec_infoset: List[int] = []
        self.dec_children: List[List[int]] = []
        self.dec_actions: List[List[int]] = []
        # Infoset metadata.
        self.infoset_key: List[str] = []
        self.infoset_nactions: List[int] = []
        self.infoset_actions: List[List[int]] = []
        self.infoset_player: List[int] = []
        self._key_to_infoset: Dict[str, int] = {}
        self.root: int = -1

    @staticmethod
    def build(game: Game) -> "GameTree":
        t = GameTree()
        t.root = t._add(game.new_initial_state())
        return t

    def _new_node(self, kind: int) -> int:
        nid = len(self.kind)
        self.kind.append(kind)
        self.term_u0.append(0.0)
        self.chance_children.append([])
        self.chance_probs.append([])
        self.dec_player.append(-1)
        self.dec_infoset.append(-1)
        self.dec_children.append([])
        self.dec_actions.append([])
        return nid

    def _infoset(self, key: str, actions: List[int], player: int) -> int:
        ii = self._key_to_infoset.get(key)
        if ii is None:
            ii = len(self.infoset_key)
            self._key_to_infoset[key] = ii
            self.infoset_key.append(key)
            self.infoset_nactions.append(len(actions))
            self.infoset_actions.append(list(actions))
            self.infoset_player.append(player)
        return ii

    def _add(self, state) -> int:
        if state.is_terminal():
            nid = self._new_node(TERMINAL)
            self.term_u0[nid] = state.returns()[0]
            return nid
        if state.is_chance():
            nid = self._new_node(CHANCE)
            children, probs = [], []
            for action, prob in state.chance_outcomes():
                children.append(self._add(state.apply_action(action)))
                probs.append(prob)
            self.chance_children[nid] = children
            self.chance_probs[nid] = probs
            return nid
        nid = self._new_node(DECISION)
        legal = state.legal_actions()
        player = state.current_player()
        ii = self._infoset(state.information_set_key(), legal, player)
        self.dec_player[nid] = player
        self.dec_infoset[nid] = ii
        self.dec_actions[nid] = legal
        self.dec_children[nid] = [self._add(state.apply_action(a)) for a in legal]
        return nid

    @property
    def num_nodes(self) -> int:
        return len(self.kind)

    @property
    def num_infosets(self) -> int:
        return len(self.infoset_key)


class TreeCFR:
    def __init__(self, tree: GameTree, variant: str = "dcfr",
                 alpha: float = 1.5, beta: float = 0.0, gamma: float = 2.0,
                 alternating: bool = False):
        if variant not in ("vanilla", "cfr+", "dcfr", "linear"):
            raise ValueError(f"unknown variant {variant!r}")
        self.tree = tree
        self.variant = variant
        self.alpha, self.beta, self.gamma = alpha, beta, gamma
        self.alternating = alternating
        self.iterations = 0
        self.player_iters = [0, 0]
        n = tree.num_infosets
        self.regret: List[List[float]] = [[0.0] * tree.infoset_nactions[i]
                                          for i in range(n)]
        self.strat_sum: List[List[float]] = [[0.0] * tree.infoset_nactions[i]
                                             for i in range(n)]

    def run(self, iterations: int) -> None:
        tree = self.tree
        for _ in range(iterations):
            self.iterations += 1
            if self.alternating:
                p = (self.iterations - 1) % 2
                self.player_iters[p] += 1
                self._cfr(tree.root, 1.0, 1.0, 1.0, p)
                self._discount(self.player_iters[p], p)
            else:
                self._cfr(tree.root, 1.0, 1.0, 1.0, None)
                self._discount(self.iterations, None)

    def _cfr(self, node: int, r0: float, r1: float, rc: float,
             up) -> Tuple[float, float]:
        tree = self.tree
        kind = tree.kind[node]
        if kind == TERMINAL:
            u0 = tree.term_u0[node]
            return u0, -u0
        if kind == CHANCE:
            v0 = v1 = 0.0
            for ci, p in zip(tree.chance_children[node], tree.chance_probs[node]):
                c0, c1 = self._cfr(ci, r0, r1, rc * p, up)
                v0 += p * c0
                v1 += p * c1
            return v0, v1

        player = tree.dec_player[node]
        ii = tree.dec_infoset[node]
        children = tree.dec_children[node]
        regret = self.regret[ii]
        n = len(children)

        # Regret matching.
        pos_total = 0.0
        for r in regret:
            if r > 0.0:
                pos_total += r
        if pos_total > 0.0:
            strategy = [(r / pos_total if r > 0.0 else 0.0) for r in regret]
        else:
            strategy = [1.0 / n] * n

        util0 = [0.0] * n
        util1 = [0.0] * n
        nv0 = nv1 = 0.0
        for i in range(n):
            si = strategy[i]
            if player == 0:
                c0, c1 = self._cfr(children[i], r0 * si, r1, rc, up)
            else:
                c0, c1 = self._cfr(children[i], r0, r1 * si, rc, up)
            util0[i] = c0
            util1[i] = c1
            nv0 += si * c0
            nv1 += si * c1

        if up is None or player == up:
            strat_sum = self.strat_sum[ii]
            if player == 0:
                cf = r1 * rc
                for i in range(n):
                    regret[i] += cf * (util0[i] - nv0)
                    strat_sum[i] += r0 * strategy[i]
            else:
                cf = r0 * rc
                for i in range(n):
                    regret[i] += cf * (util1[i] - nv1)
                    strat_sum[i] += r1 * strategy[i]
        return nv0, nv1

    def _discount(self, t: float, player) -> None:
        """Discount accumulators; in alternating mode only ``player``'s sets."""
        v = self.variant
        if v == "vanilla":
            return
        tree = self.tree
        if v == "cfr+":
            sf = t / (t + 1.0)

            def apply(regret, ss):
                for i in range(len(regret)):
                    if regret[i] < 0.0:
                        regret[i] = 0.0
                    ss[i] *= sf
        elif v == "linear":
            f = t / (t + 1.0)

            def apply(regret, ss):
                for i in range(len(regret)):
                    regret[i] *= f
                    ss[i] *= f
        else:  # dcfr
            ta = t ** self.alpha
            pos = ta / (ta + 1.0)
            tb = t ** self.beta
            neg = tb / (tb + 1.0)
            sf = (t / (t + 1.0)) ** self.gamma

            def apply(regret, ss):
                for i in range(len(regret)):
                    regret[i] *= pos if regret[i] > 0.0 else neg
                    ss[i] *= sf

        for ii in range(tree.num_infosets):
            if player is None or tree.infoset_player[ii] == player:
                apply(self.regret[ii], self.strat_sum[ii])

    def average_strategy(self) -> TabularStrategy:
        tree = self.tree
        table: Dict[str, Dict[int, float]] = {}
        for ii in range(tree.num_infosets):
            ss = self.strat_sum[ii]
            actions = tree.infoset_actions[ii]
            total = sum(ss)
            if total > 0.0:
                probs = {actions[i]: ss[i] / total for i in range(len(actions))}
            else:
                probs = {a: 1.0 / len(actions) for a in actions}
            table[tree.infoset_key[ii]] = probs
        return TabularStrategy(table)


class _TreeBestResponse:
    """Exact best response over the compiled tree (node-id memoization)."""

    def __init__(self, tree: GameTree, strategy: TabularStrategy, br_player: int):
        self.tree = tree
        self.br = br_player
        # Precompute opponent action probabilities per infoset.
        self.opp_probs: List[List[float]] = []
        for ii in range(tree.num_infosets):
            actions = tree.infoset_actions[ii]
            pd = strategy.action_probs(tree.infoset_key[ii], actions)
            self.opp_probs.append([pd.get(a, 0.0) for a in actions])
        # Gather best-responder nodes per infoset with opponent+chance reach.
        self.infoset_members: Dict[int, List[Tuple[int, float]]] = {}
        self._collect(tree.root, 1.0)
        self._br_action: Dict[int, int] = {}
        self._value: Dict[int, float] = {}

    def _collect(self, node: int, reach: float) -> None:
        tree = self.tree
        kind = tree.kind[node]
        if kind == TERMINAL:
            return
        if kind == CHANCE:
            for ci, p in zip(tree.chance_children[node], tree.chance_probs[node]):
                self._collect(ci, reach * p)
            return
        ii = tree.dec_infoset[node]
        if tree.dec_player[node] == self.br:
            self.infoset_members.setdefault(ii, []).append((node, reach))
            for ci in tree.dec_children[node]:
                self._collect(ci, reach)
        else:
            probs = self.opp_probs[ii]
            for idx, ci in enumerate(tree.dec_children[node]):
                if probs[idx] > 0.0:
                    self._collect(ci, reach * probs[idx])

    def _br_action_index(self, ii: int) -> int:
        cached = self._br_action.get(ii)
        if cached is not None:
            return cached
        members = self.infoset_members[ii]
        nactions = self.tree.infoset_nactions[ii]
        best_idx, best_v = 0, float("-inf")
        for idx in range(nactions):
            v = 0.0
            for node, reach in members:
                if reach != 0.0:
                    v += reach * self.value(self.tree.dec_children[node][idx])
            if v > best_v:
                best_v, best_idx = v, idx
        self._br_action[ii] = best_idx
        return best_idx

    def value(self, node: int) -> float:
        cached = self._value.get(node)
        if cached is not None:
            return cached
        tree = self.tree
        kind = tree.kind[node]
        if kind == TERMINAL:
            u0 = tree.term_u0[node]
            v = u0 if self.br == 0 else -u0
        elif kind == CHANCE:
            v = 0.0
            for ci, p in zip(tree.chance_children[node], tree.chance_probs[node]):
                v += p * self.value(ci)
        else:
            ii = tree.dec_infoset[node]
            if tree.dec_player[node] == self.br:
                idx = self._br_action_index(ii)
                v = self.value(tree.dec_children[node][idx])
            else:
                probs = self.opp_probs[ii]
                v = 0.0
                for idx, ci in enumerate(tree.dec_children[node]):
                    if probs[idx] > 0.0:
                        v += probs[idx] * self.value(ci)
        self._value[node] = v
        return v


def best_response_value(tree: GameTree, strategy: TabularStrategy,
                        br_player: int) -> float:
    return _TreeBestResponse(tree, strategy, br_player).value(tree.root)


def exploitability(tree: GameTree, strategy: TabularStrategy) -> float:
    br0 = best_response_value(tree, strategy, 0)
    br1 = best_response_value(tree, strategy, 1)
    return (br0 + br1) / 2.0
