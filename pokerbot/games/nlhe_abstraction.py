"""Card abstraction for No-Limit Hold'em information sets.

* Pre-flop is *lossless*: the 1326 two-card combos collapse to the 169
  strategically distinct hands (13 pairs + 78 suited + 78 offsuit).
* Post-flop hands are bucketed by made-hand strength into equal-probability
  buckets, with the bucket boundaries learned once by sampling (so each bucket
  holds ~1/N of random hands).  This is a fast, deterministic abstraction; it
  ignores draw potential, which we document as a known approximation.

``bucket(hole, board, street)`` returns a small hashable used in the
information-set key.
"""
from __future__ import annotations

import random
from typing import List, Optional, Tuple

from ..evaluator import evaluate

_BOARD_COUNT = {0: 0, 1: 3, 2: 4, 3: 5}   # cards visible per street


def preflop_index(hole: Tuple[int, int]) -> int:
    """Map two hole cards to a canonical 0..168 index (169 distinct hands)."""
    c0, c1 = hole
    r0, r1 = c0 // 4, c1 // 4
    s0, s1 = c0 % 4, c1 % 4
    if r0 == r1:
        return r0                      # 0..12 pairs
    hi, lo = (r0, r1) if r0 > r1 else (r1, r0)
    idx2 = hi * (hi - 1) // 2 + lo      # 0..77
    if s0 == s1:
        return 13 + idx2                # 13..90 suited
    return 91 + idx2                    # 91..168 offsuit


class Abstraction:
    def bucket(self, hole, board, street):
        raise NotImplementedError


class NullAbstraction(Abstraction):
    """Pre-flop lossless; post-flop a coarse fixed-width strength bucket.

    Needs no precomputation, so it's handy for rules tests and tiny games.
    """

    def __init__(self, postflop_buckets: int = 10):
        self.nb = postflop_buckets

    def bucket(self, hole, board, street):
        if street == 0:
            return preflop_index(hole)
        n = _BOARD_COUNT[street]
        strength = evaluate(list(hole) + list(board[:n]))
        b = (strength - 1) * self.nb // 7462
        return (street, b)


class StrengthAbstraction(Abstraction):
    """Equal-probability post-flop strength buckets (boundaries sampled once)."""

    def __init__(self, postflop_buckets: int = 8, samples: int = 30000,
                 seed: int = 12345):
        self.nb = postflop_buckets
        self.samples = samples
        self.seed = seed
        self._thresholds: Optional[dict] = None

    def _ensure(self) -> None:
        if self._thresholds is not None:
            return
        rng = random.Random(self.seed)
        thresholds = {}
        for street, n_board in ((1, 3), (2, 4), (3, 5)):
            strengths: List[int] = []
            for _ in range(self.samples):
                deck = list(range(52))
                rng.shuffle(deck)
                cards = deck[:2] + deck[2:2 + n_board]
                strengths.append(evaluate(cards))
            strengths.sort()
            cuts = [strengths[min(len(strengths) - 1,
                                  (i + 1) * len(strengths) // self.nb)]
                    for i in range(self.nb - 1)]
            thresholds[street] = cuts
        self._thresholds = thresholds

    def bucket(self, hole, board, street):
        if street == 0:
            return preflop_index(hole)
        self._ensure()
        n = _BOARD_COUNT[street]
        strength = evaluate(list(hole) + list(board[:n]))
        cuts = self._thresholds[street]
        b = 0
        for c in cuts:
            if strength > c:
                b += 1
            else:
                break
        return (street, b)
