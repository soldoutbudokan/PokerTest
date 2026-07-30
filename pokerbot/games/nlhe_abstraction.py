"""Card abstraction for No-Limit Hold'em information sets.

* Pre-flop is *lossless*: the 1326 two-card combos collapse to the 169
  strategically distinct hands (13 pairs + 78 suited + 78 offsuit).
* Post-flop hands are bucketed by made-hand strength into equal-probability
  buckets, with the bucket boundaries learned once by sampling (so each bucket
  holds ~1/N of random hands).  The boundaries are conditioned on a cheap
  **board-texture** class, so a bucket means "this percentile *on this kind of
  board*" rather than "this percentile over all boards".  This is a fast,
  deterministic abstraction.

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


def _board_texture(board: List[int]) -> int:
    """A cheap class for how much *the board itself* inflates absolute
    made-hand strength.

    Absolute strength (the 1..7462 evaluator rank) is not comparable across
    boards: on a paired or three-suited board almost every holding makes two
    pair or better, so a hand that is only average *for that board* still
    scores in the top absolute percentiles; on a dry rainbow board top pair is
    a monster but scores mid-table.  Bucketing on absolute percentiles
    therefore mixes "nuts here" with "air here" in one bucket.  Conditioning
    the percentile cuts on this class fixes that at no extra information-set
    cost.

    Bit 0: the board is paired (two board cards share a rank).
    Bit 1: a flush is possible (3+ board cards of one suit).
    Bit 2: a straight is possible (3+ board ranks inside a 5-rank window).
    """
    suit_counts = [0, 0, 0, 0]
    rank_counts = [0] * 13
    for c in board:
        suit_counts[c % 4] += 1
        rank_counts[c // 4] += 1

    tex = 0
    if any(k > 1 for k in rank_counts):
        tex |= 1
    if max(suit_counts) >= 3:
        tex |= 2

    ranks = [r for r in range(13) if rank_counts[r]]
    if rank_counts[12]:          # the ace also plays low (wheel straights)
        ranks.insert(0, -1)
    for i, r in enumerate(ranks):
        if sum(1 for x in ranks[i:] if x <= r + 4) >= 3:
            tex |= 4
            break
    return tex


class StrengthAbstraction(Abstraction):
    """Equal-probability post-flop strength buckets (boundaries sampled once),
    refined on the flop/turn by a redraw-potential feature so the abstraction
    is no longer draw-blind (made-hand strength alone can't tell a dead
    middle pair from a middle pair with a flush draw).

    The bucket boundaries are learned **per board-texture class**
    (:func:`_board_texture`), so bucket ``b`` means "the ``b``-th eighth of
    holdings *on a board like this one*".  The texture itself is deliberately
    kept out of the bucket key: hands of equal relative strength are pooled,
    which is the pooling an equal-probability abstraction is meant to express,
    and the information-set count is unchanged.  Pass ``texture_aware=False``
    for the earlier scheme (one set of absolute-percentile cuts per street).

    ``samples`` was raised from 30k to 60k alongside this so the rarer texture
    classes still get their boundaries from a few thousand hands each; classes
    below :attr:`MIN_TEXTURE_SAMPLES` reuse the pooled cuts.  Learning the cuts
    is a one-off cost (a few seconds) paid when the abstraction is first used.
    """

    #: A texture class needs at least this many samples before it gets its own
    #: cuts; rarer boards fall back to the street's pooled cuts rather than to
    #: boundaries estimated from a handful of hands.
    MIN_TEXTURE_SAMPLES = 2000

    def __init__(self, postflop_buckets: int = 8, samples: int = 60000,
                 seed: int = 12345, draw_aware: bool = True,
                 texture_aware: bool = True):
        self.nb = postflop_buckets
        self.samples = samples
        self.seed = seed
        self.draw_aware = draw_aware
        self.texture_aware = texture_aware
        self._thresholds: Optional[dict] = None

    def _cuts(self, strengths: List[int]) -> List[int]:
        """Equal-probability boundaries: ``nb - 1`` cuts over the samples.

        Sorts ``strengths`` in place (it is scratch data in every caller, and
        these lists run to tens of thousands of entries)."""
        strengths.sort()
        return [strengths[min(len(strengths) - 1,
                              (i + 1) * len(strengths) // self.nb)]
                for i in range(self.nb - 1)]

    def _ensure(self) -> None:
        if self._thresholds is not None:
            return
        rng = random.Random(self.seed)
        thresholds = {}
        for street, n_board in ((1, 3), (2, 4), (3, 5)):
            strengths: List[int] = []
            by_texture: dict = {}
            for _ in range(self.samples):
                deck = list(range(52))
                rng.shuffle(deck)
                board = deck[2:2 + n_board]
                s = evaluate(deck[:2] + board)
                strengths.append(s)
                if self.texture_aware:
                    by_texture.setdefault(_board_texture(board), []).append(s)
            base = self._cuts(strengths)
            per_texture = {t: self._cuts(v) for t, v in by_texture.items()
                           if len(v) >= self.MIN_TEXTURE_SAMPLES}
            thresholds[street] = (base, per_texture)
        self._thresholds = thresholds

    def bucket(self, hole, board, street):
        if street == 0:
            return preflop_index(hole)
        self._ensure()
        n = _BOARD_COUNT[street]
        board_cards = list(board[:n])
        cards = list(hole) + board_cards
        strength = evaluate(cards)
        base, per_texture = self._thresholds[street]
        cuts = base
        if self.texture_aware and per_texture:
            cuts = per_texture.get(_board_texture(board_cards), base)
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
