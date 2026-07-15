"""Real-time **river subgame re-solving** ("endgame search") for NLHE.

When play reaches the river, the blueprint plays a strategy over a *coarse* card
abstraction (8 made-hand-strength buckets), and that abstraction error is the
dominant source of exploitability.  This module re-solves the river subgame from
the real node at (near-)unabstracted granularity, using the opponent's — and the
hero's own — river *range* implied by the blueprint.

Why this is safe to bolt on:

* The river betting subtree is **card-independent** and already compiled into
  :class:`~pokerbot.solve.nlhe_tree.CompiledBettingTree`; only showdown values
  depend on the cards, and those are computed *exactly* with the real evaluator.
  The subtrees are tiny (a few dozen nodes).
* The re-solve is a **full enumeration** (vector CFR over the whole subtree, no
  Monte-Carlo inside), so it is a deterministic function of
  ``(board, river_root, blueprint)``.  There is no unseeded randomness: the only
  RNG in the play path is the outer deal-sampling and the agent's final action
  sample, both already seeded by the caller.

Granularity: hands are collapsed to their **exact showdown strength class**
(``evaluate`` value on the final board), which on the river is a *lossless*
reduction for showdown ordering — two hands of equal strength are strategically
identical there — and is far finer than the 8 blueprint buckets.  This ignores
card-removal / *blocker* effects (an opponent can't hold a card you hold); that
is a documented second-order approximation which keeps the solve fast enough for
the evaluation loop.  Recovering blockers is future work (and belongs with the
safe/nested gadget).

Range derivation (the belief that reaches the subgame): for each candidate hand
``h`` the blueprint *reach* to the river root is the product, over that player's
decision nodes on the public betting path, of the blueprint probability of the
action actually taken, evaluated at that player's abstraction bucket for ``h``.
Summed by strength class and normalised, this is the conditional range.  The
subgame is the standard range-vs-range endgame; the hero then plays the refined
strategy for its actual hand's strength.

This is **unsafe** ("unnested") re-solving in the sense of Burch/Moravcik: it
does not yet constrain the opponent to their blueprint counterfactual values, so
a clever opponent could in principle exploit the seam between blueprint and
re-solve.  We *measure* exploitability after enabling it (see
``pokerbot.metrics``); the range-constrained safe gadget is step 2.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from ..evaluator import evaluate
from .cfr import TabularStrategy
from .nlhe_tree import DECISION, FOLD_T, SHOWDOWN_T, CompiledBettingTree


def river_root_hist(hist: str) -> Optional[str]:
    """The betting history at the river *root* for a river node's ``hist``.

    A river node's history has exactly three ``/`` separators (pre-flop, flop,
    turn all closed); the river root is the prefix up to and including the third
    ``/`` (river betting empty).  Returns ``None`` if ``hist`` is not on the
    river.
    """
    slashes = 0
    for i, ch in enumerate(hist):
        if ch == "/":
            slashes += 1
            if slashes == 3:
                return hist[:i + 1]
    return None


class _SubtreeIndex:
    """Static, blueprint-independent indexing of the compiled betting tree.

    Maps histories to node ids and reconstructs the public path to a river root.
    Built once and reused for every solve (cheap; no card information involved).
    """

    def __init__(self, tree: CompiledBettingTree):
        self.tree = tree
        self.hist_to_nid: Dict[str, int] = {}
        for nid in range(tree.num_nodes):
            if tree.kind[nid] == DECISION:
                self.hist_to_nid[tree.dec_hist[nid]] = nid

    def path_to(self, target_nid: int) -> List[Tuple[int, int, int, str, int]]:
        """Decision nodes from the root down to ``target_nid`` (exclusive).

        Each entry is ``(nid, player, street, hist, action_taken)`` — the action
        that continues the public betting toward ``target_nid``.
        """
        tree = self.tree
        target_hist = tree.dec_hist[target_nid]
        path: List[Tuple[int, int, int, str, int]] = []
        nid = tree.root
        while nid != target_nid:
            chosen = None
            for a, c in zip(tree.dec_actions[nid], tree.dec_children[nid]):
                if tree.kind[c] == DECISION and target_hist.startswith(
                        tree.dec_hist[c]):
                    chosen = (a, c)
                    break
            if chosen is None:                       # pragma: no cover - defensive
                raise ValueError(f"no path to node {target_nid} ({target_hist!r})")
            a, c = chosen
            path.append((nid, tree.dec_player[nid], tree.dec_street[nid],
                         tree.dec_hist[nid], a))
            nid = c
        return path


class _Solution:
    """Solved river subgame: average strategies keyed by (node, strength class).

    ``strengths`` is the sorted list of distinct showdown strengths in play;
    ``avg[nid]`` is a ``(num_classes, num_actions)`` probability table for the
    node's acting player.  A hand is looked up by its ``evaluate`` strength.
    """

    def __init__(self, strengths: np.ndarray, avg: Dict[int, np.ndarray],
                 actions: Dict[int, List[int]]):
        self.strengths = strengths
        self._row = {int(v): i for i, v in enumerate(strengths)}
        self.avg = avg
        self.actions = actions

    def action_probs(self, node_nid: int, strength: int) -> Optional[Dict[int, float]]:
        acts = self.actions.get(node_nid)
        if acts is None:
            return None
        row = self._row.get(int(strength))
        if row is None:
            return None
        probs = self.avg[node_nid][row]
        return {a: float(probs[i]) for i, a in enumerate(acts)}


def _showdown_value(reach_opp: np.ndarray, stake: float) -> np.ndarray:
    """Per-strength-class showdown value against ``reach_opp`` (classes ascending).

    For class ``i``: ``stake * (win_mass - lose_mass)`` where win/lose are the
    opponent reach on strictly weaker / stronger classes.  With classes sorted
    ascending and distinct this equals ``stake*(2*cumsum - reach_opp - total)``.
    """
    if reach_opp.size == 0:
        return reach_opp
    csum = np.cumsum(reach_opp)
    total = csum[-1]
    return stake * (2.0 * csum - reach_opp - total)


class _BoardData:
    """Per-board precompute shared by every river root on that board.

    Enumerating the 1081 candidate hands and evaluating their showdown strength
    and pre-river buckets is the expensive part of a solve; it depends only on
    the board, so it is computed once and reused across the (up to 25) river
    roots and across mirrored/repeated deals.
    """
    __slots__ = ("hands", "uniq", "class_of", "street_buckets")

    def __init__(self, hands, uniq, class_of, street_buckets):
        self.hands = hands                    # list of (c, c)
        self.uniq = uniq                      # sorted distinct strengths
        self.class_of = class_of              # hand index -> strength-class index
        self.street_buckets = street_buckets  # street -> (int ids array, [bucket objs])


class RiverSubgameSolver:
    """Re-solves river subgames on demand and caches the result.

    ``iterations`` CFR+ passes over the (tiny) subtree.  Everything is
    deterministic — solves depend only on ``(board, river_root, blueprint)``.
    """

    def __init__(self, game, blueprint: TabularStrategy,
                 tree: Optional[CompiledBettingTree] = None,
                 iterations: int = 120):
        self.game = game
        self.blueprint = blueprint
        self.tree = tree or CompiledBettingTree.build(game)
        self.index = _SubtreeIndex(self.tree)
        self.abstraction = game.abstraction
        self.iterations = iterations
        self._cache: Dict[Tuple, _Solution] = {}
        self._board_cache: Dict[Tuple, _BoardData] = {}
        self.solves = 0                 # instrumentation: distinct solves computed

    # -- range derivation ---------------------------------------------------
    def _board_data(self, board: Tuple[int, ...]) -> _BoardData:
        bd = self._board_cache.get(board)
        if bd is not None:
            return bd
        ab = self.abstraction
        board_set = set(board)
        deck = [c for c in range(52) if c not in board_set]
        hands = [(deck[i], deck[j])
                 for i in range(len(deck)) for j in range(i + 1, len(deck))]
        strengths = np.array([evaluate(list(h) + list(board)) for h in hands])
        uniq = np.unique(strengths)
        class_of = np.searchsorted(uniq, strengths)     # every strength is in uniq
        street_buckets: Dict[int, Tuple[np.ndarray, list]] = {}
        for street in (0, 1, 2):                          # pre-river streets only
            bmap: Dict[object, int] = {}
            objs: list = []
            ids = np.empty(len(hands), dtype=np.int32)
            for k, h in enumerate(hands):
                b = ab.bucket(h, board, street)
                bid = bmap.get(b)
                if bid is None:
                    bid = len(objs)
                    bmap[b] = bid
                    objs.append(b)
                ids[k] = bid
            street_buckets[street] = (ids, objs)
        bd = _BoardData(hands, uniq, class_of, street_buckets)
        self._board_cache[board] = bd
        return bd

    def _classes(self, board: Tuple[int, ...], path):
        """Distinct strength classes with each player's normalised range mass.

        The blueprint action probability at a path node depends on the hand only
        through its bucket, so we look it up once per distinct bucket (there are
        at most a couple dozen) and broadcast to hands.
        """
        bd = self._board_data(board)
        tree = self.tree
        nh = len(bd.hands)
        w0 = np.ones(nh)
        w1 = np.ones(nh)
        for (nid, pl, street, hist, action) in path:
            ids, objs = bd.street_buckets[street]
            legal = tree.dec_actions[nid]
            prob_by_id = np.array(
                [self.blueprint.action_probs(f"{o}|{hist}", legal).get(action, 0.0)
                 for o in objs])
            (w0 if pl == 0 else w1)[:] *= prob_by_id[ids]
        reach0 = np.zeros(len(bd.uniq))
        reach1 = np.zeros(len(bd.uniq))
        np.add.at(reach0, bd.class_of, w0)
        np.add.at(reach1, bd.class_of, w1)
        for reach in (reach0, reach1):
            s = reach.sum()
            if s > 0:
                reach /= s
            else:                       # blueprint never reaches here for this
                reach[:] = 1.0 / len(reach)   # player: fall back to uniform range
        return bd.uniq, reach0, reach1

    # -- the solve ----------------------------------------------------------
    def solve(self, board: Tuple[int, ...], river_root_nid: int) -> _Solution:
        cache_key = (board, river_root_nid)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        path = self.index.path_to(river_root_nid)
        strengths, reach0, reach1 = self._classes(board, path)
        sol = self._run_cfr(river_root_nid, strengths, reach0, reach1)
        self._cache[cache_key] = sol
        self.solves += 1
        return sol

    def _run_cfr(self, river_root_nid, strengths, reach0, reach1):
        tree = self.tree
        n = len(strengths)
        regret: Dict[int, np.ndarray] = {}
        stratsum: Dict[int, np.ndarray] = {}
        actions: Dict[int, List[int]] = {}

        def alloc(nid):
            if tree.kind[nid] != DECISION or nid in regret:
                return
            na = len(tree.dec_actions[nid])
            regret[nid] = np.zeros((n, na))
            stratsum[nid] = np.zeros((n, na))
            actions[nid] = list(tree.dec_actions[nid])
            for c in tree.dec_children[nid]:
                alloc(c)

        alloc(river_root_nid)

        def cfv(nid, r0, r1, t):
            kind = tree.kind[nid]
            if kind == FOLD_T:
                p0 = tree.fold_payoff0[nid]
                return np.full(n, p0 * r1.sum()), np.full(n, -p0 * r0.sum())
            if kind == SHOWDOWN_T:
                s = tree.stake[nid]
                # Each player's value is computed on its OWN strength axis vs the
                # opponent's reach; the +stake / perspective flip is captured by
                # the ordering, so both use +s (not -s).
                return _showdown_value(r1, s), _showdown_value(r0, s)

            p = tree.dec_player[nid]
            reg = regret[nid]
            pos = np.maximum(reg, 0.0)
            tot = pos.sum(axis=1, keepdims=True)
            na = reg.shape[1]
            sigma = np.where(tot > 0.0, pos / np.where(tot > 0.0, tot, 1.0), 1.0 / na)
            children = tree.dec_children[nid]
            v0 = np.zeros(n)
            v1 = np.zeros(n)
            if p == 0:
                child0 = []
                for ai, c in enumerate(children):
                    cv0, cv1 = cfv(c, r0 * sigma[:, ai], r1, t)
                    child0.append(cv0)
                    v0 += sigma[:, ai] * cv0
                    v1 += cv1
                for ai in range(na):
                    reg[:, ai] = np.maximum(reg[:, ai] + (child0[ai] - v0), 0.0)
                stratsum[nid] += t * r0[:, None] * sigma
            else:
                child1 = []
                for ai, c in enumerate(children):
                    cv0, cv1 = cfv(c, r0, r1 * sigma[:, ai], t)
                    child1.append(cv1)
                    v1 += sigma[:, ai] * cv1
                    v0 += cv0
                for ai in range(na):
                    reg[:, ai] = np.maximum(reg[:, ai] + (child1[ai] - v1), 0.0)
                stratsum[nid] += t * r1[:, None] * sigma
            return v0, v1

        for it in range(1, self.iterations + 1):
            cfv(river_root_nid, reach0.copy(), reach1.copy(), float(it))

        avg: Dict[int, np.ndarray] = {}
        for nid, ss in stratsum.items():
            tot = ss.sum(axis=1, keepdims=True)
            na = ss.shape[1]
            avg[nid] = np.where(tot > 0.0, ss / np.where(tot > 0.0, tot, 1.0), 1.0 / na)
        return _Solution(strengths, avg, actions)

    # -- convenience for callers (agent / exploiter / matchup) --------------
    def river_action_probs(self, board: Tuple[int, ...], hist: str,
                           hole: Tuple[int, int], player: int,
                           legal: List[int]) -> Optional[Dict[int, float]]:
        """Blueprint-range-resolved action probs for ``player`` holding ``hole``
        at the river node ``hist``.  ``None`` if not resolvable (the caller then
        falls back to the blueprint)."""
        rr = river_root_hist(hist)
        if rr is None:
            return None
        river_root_nid = self.index.hist_to_nid.get(rr)
        node_nid = self.index.hist_to_nid.get(hist)
        if river_root_nid is None or node_nid is None:
            return None
        sol = self.solve(board, river_root_nid)
        strength = evaluate(list(hole) + list(board))
        return sol.action_probs(node_nid, strength)


def subgame_exploitability(sol: "_Solution", solver: RiverSubgameSolver,
                           board: Tuple[int, ...], river_root_nid: int) -> float:
    """Best-response value against the solved strategy, in chips (for tests).

    In a two-player zero-sum game the sum of the two seats' best-response values
    equals the exploitability of the strategy pair (the game value cancels): at
    Nash each seat's best response earns exactly the game value, so the sum is 0.
    A converged solve drives this toward 0.
    """
    tree = solver.tree
    path = solver.index.path_to(river_root_nid)
    _, reach0, reach1 = solver._classes(board, path)
    n = len(sol.strengths)

    def br_value(br_player: int) -> float:
        def rec(nid, reach_opp):
            kind = tree.kind[nid]
            if kind == FOLD_T:
                p0 = tree.fold_payoff0[nid]
                val = p0 if br_player == 0 else -p0
                return np.full(n, val * reach_opp.sum())
            if kind == SHOWDOWN_T:
                s = tree.stake[nid]
                return _showdown_value(reach_opp, s)
            p = tree.dec_player[nid]
            children = tree.dec_children[nid]
            if p == br_player:
                return np.maximum.reduce([rec(c, reach_opp) for c in children])
            probs = sol.avg[nid]
            out = None
            for ai, c in enumerate(children):
                child = rec(c, reach_opp * probs[:, ai])
                out = child if out is None else out + child
            return out

        own = reach0 if br_player == 0 else reach1
        opp = reach1 if br_player == 0 else reach0
        return float(own @ rec(river_root_nid, opp.copy()))

    return br_value(0) + br_value(1)
