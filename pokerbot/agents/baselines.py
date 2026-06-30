"""Baseline opponents for the No-Limit Hold'em arena.

These span a range of styles so a bot's win rate is informative:

* ``RandomAgent``        – uniform over legal actions (a noise floor).
* ``CallStationAgent``   – always checks/calls, never folds or raises.
* ``AlwaysRaiseAgent``   – maniac: raises/jams whenever possible.
* ``TightAggressiveAgent`` – a hand-strength heuristic that folds weak hands,
  calls medium ones and raises strong ones (a reasonable rule-based player).

All are deterministic given the rng and depend only on the public state plus the
acting player's own cards.
"""
from __future__ import annotations

import random
from typing import List

from ..evaluator import evaluate
from ..games.nlhe import (ALL_IN, CALL, FOLD, PREFLOP, RAISE_BASE, NLHEState)
from ..games.nlhe_abstraction import preflop_index
from .base import Agent


class RandomAgent(Agent):
    name = "random"

    def act(self, state, rng):
        return rng.choice(state.legal_actions())


class CallStationAgent(Agent):
    name = "call-station"

    def act(self, state, rng):
        return CALL


class AlwaysRaiseAgent(Agent):
    """Raises the maximum available; jams given the chance; never folds."""
    name = "maniac"

    def act(self, state, rng):
        legal = state.legal_actions()
        # Prefer the biggest aggressive action.
        if ALL_IN in legal:
            return ALL_IN
        raises = [a for a in legal if a >= RAISE_BASE]
        if raises:
            return max(raises)
        return CALL


# Pre-flop hand-strength score in [0, 1] from the 169-hand index, used by the
# heuristic agents.  Pairs and high/connected/suited hands score higher.
def _preflop_strength(hole) -> float:
    c0, c1 = hole
    r0, r1 = c0 // 4, c1 // 4
    suited = (c0 % 4) == (c1 % 4)
    hi, lo = max(r0, r1), min(r0, r1)
    if r0 == r1:                                   # pair
        return 0.5 + r0 / 24.0                     # 22 -> .5, AA -> ~.99
    gap = hi - lo
    score = (hi + lo) / 36.0                       # high cards
    if suited:
        score += 0.10
    if gap == 1:
        score += 0.06                              # connected
    elif gap == 2:
        score += 0.03
    return min(score, 0.85)


class TightAggressiveAgent(Agent):
    """Folds weak hands, calls medium, raises strong (hand-strength heuristic)."""
    name = "tight-aggressive"

    def __init__(self, fold_below: float = 0.33, raise_above: float = 0.55):
        self.fold_below = fold_below
        self.raise_above = raise_above

    def _strength(self, state: NLHEState) -> float:
        me = state.to_act
        hole = state.hole[me]
        if state.street == PREFLOP:
            return _preflop_strength(hole)
        n = {1: 3, 2: 4, 3: 5}[state.street if state.street >= 0 else 3]
        s = evaluate(list(hole) + list(state.board[:n]))
        return s / 7462.0                          # made-hand percentile-ish

    def act(self, state, rng):
        legal = state.legal_actions()
        strength = self._strength(state)
        owe = state.owe
        if strength >= self.raise_above:
            raises = [a for a in legal if a >= RAISE_BASE]
            if raises:
                return min(raises)                 # a modest raise
            if ALL_IN in legal and strength > 0.8:
                return ALL_IN
            return CALL
        if strength < self.fold_below and owe > 0 and FOLD in legal:
            return FOLD
        return CALL
