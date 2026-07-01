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


def _draw_feature(cards: List[int]) -> int:
    """Redraw potential of a made hand that isn't final yet (flop/turn only).

    Returns 0 (no meaningful redraw), 1 (weak: backdoor flush or gutshot), or
    2 (strong: made flush draw or open-ended straight draw). Made-hand
    strength already lives in the strength bucket; this distinguishes hands
    that are live going forward from ones that are pure air/showdown-only.
    """
    suit_counts = [0, 0, 0, 0]
    for c in cards:
        suit_counts[c % 4] += 1
    flush_draw = max(suit_counts) == 4
    backdoor_flush = max(suit_counts) == 3

    ranks = set(c // 4 for c in cards)
    if 12 in ranks:          # ace also plays low (wheel draws)
        ranks.add(-1)
    sorted_ranks = sorted(ranks)
    oesd = gutshot = False
    for r in sorted_ranks:
        window = [x for x in sorted_ranks if r <= x <= r + 4]
        if len(window) >= 4:
            span = window[-1] - window[0]
            if span == 3:
                oesd = True
            elif span == 4:
                gutshot = True

    if flush_draw or oesd:
        return 2
    if backdoor_flush or gutshot:
        return 1
    return 0


class StrengthAbstraction(Abstraction):
    """Equal-probability post-flop strength buckets (boundaries sampled once),
    refined on the flop/turn by a redraw-potential feature so the abstraction
    is no longer draw-blind (made-hand strength alone can't tell a dead
    middle pair from a middle pair with a flush draw)."""

    def __init__(self, postflop_buckets: int = 8, samples: int = 30000,
                 seed: int = 12345, draw_aware: bool = True):
        self.nb = postflop_buckets
        self.samples = samples
        self.seed = seed
        self.draw_aware = draw_aware
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
        cards = list(hole) + list(board[:n])
        strength = evaluate(cards)
        cuts = self._thresholds[street]
        b = 0
        for c in cuts:
            if strength > c:
                b += 1
            else:
                break
        # The river has no future cards to draw to, so the feature is moot
        # there; keep it flop/turn-only to avoid needlessly splitting river
        # buckets (which would just add infosets with no signal).
        if self.draw_aware and street in (1, 2):
            return (street, b, _draw_feature(cards))
        return (street, b)
