"""Fast, exact poker hand evaluator for 5-, 6- and 7-card hands.

The evaluator returns an integer *strength* in ``1..7462`` where **higher is
better** (7462 = royal flush, 1 = ``7-5-4-3-2`` offsuit).  It works by
precomputing three lookup tables once at import time:

* ``UNIQUE5`` – indexed by the 13-bit rank mask, for the 5-distinct-rank
  non-flush hands (high card and straight).
* ``FLUSH``   – same masks, for flush and straight-flush hands.
* ``PAIRED``  – a dict keyed by the product of rank primes, for every hand
  containing at least one pair (pair, two pair, trips, full house, quads).

A 7-card hand is scored as the maximum over its 21 five-card subsets.  The
table construction enumerates the 7462 distinct hand *types*, sorts them into
the canonical poker order, and assigns ascending strengths, so the result is
exact by construction.  ``tests/test_evaluator.py`` additionally checks the
per-category value counts against the textbook figures.
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Sequence

# Prime per rank index (0 -> deuce ... 12 -> ace). Products of these primes
# uniquely identify a multiset of ranks, which is how paired hands are keyed.
PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

# Category ordering, weakest -> strongest.
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
CATEGORY_NAMES = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight",
    "Flush", "Full House", "Four of a Kind", "Straight Flush",
]

# --- Straight rank masks (10 of them), ordered weakest -> strongest. ---
_STRAIGHT_MASKS: List[int] = []
# Wheel A-2-3-4-5 is the weakest straight.
_STRAIGHT_MASKS.append((1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 12))
for top in range(4, 13):  # 6-high (top=4) ... A-high (top=12)
    mask = 0
    for r in range(top - 4, top + 1):
        mask |= 1 << r
    _STRAIGHT_MASKS.append(mask)
_STRAIGHT_MASK_SET = set(_STRAIGHT_MASKS)

# Lookup tables, filled by _build_tables().  Named with a ``_TABLE`` suffix so
# they don't collide with the ``FLUSH`` category constant above.
UNIQUE5_TABLE: List[int] = [0] * (1 << 13)
FLUSH_TABLE: List[int] = [0] * (1 << 13)
PAIRED_TABLE: Dict[int, int] = {}


def _rank_mask(ranks: Sequence[int]) -> int:
    m = 0
    for r in ranks:
        m |= 1 << r
    return m


def _prime_product(ranks: Sequence[int]) -> int:
    p = 1
    for r in ranks:
        p *= PRIMES[r]
    return p


def _build_tables() -> None:
    """Enumerate the 7462 distinct hand types and assign ascending strengths."""
    # Each entry: (category, within_category_sort_key, kind, payload)
    # kind tells us which table to write and how to derive the key.
    entries = []

    # High card: 5 distinct ranks, not a straight.
    for combo in combinations(range(13), 5):
        mask = _rank_mask(combo)
        if mask in _STRAIGHT_MASK_SET:
            continue
        key = tuple(sorted(combo, reverse=True))
        entries.append((HIGH_CARD, key, "unique", mask))

    # Pair: pair rank + 3 distinct kickers.
    for pair in range(13):
        for kick in combinations([r for r in range(13) if r != pair], 3):
            key = (pair,) + tuple(sorted(kick, reverse=True))
            ranks = [pair, pair] + list(kick)
            entries.append((PAIR, key, "paired", _prime_product(ranks)))

    # Two pair: two pair ranks + 1 kicker.
    for hi, lo in combinations(range(13), 2):  # hi < lo as indices
        # We want the higher *rank* to dominate; iterate so that hi_rank>lo_rank.
        for kicker in range(13):
            if kicker == hi or kicker == lo:
                continue
            high_pair, low_pair = max(hi, lo), min(hi, lo)
            key = (high_pair, low_pair, kicker)
            ranks = [high_pair, high_pair, low_pair, low_pair, kicker]
            entries.append((TWO_PAIR, key, "paired", _prime_product(ranks)))

    # Trips: trip rank + 2 distinct kickers.
    for trip in range(13):
        for kick in combinations([r for r in range(13) if r != trip], 2):
            key = (trip,) + tuple(sorted(kick, reverse=True))
            ranks = [trip, trip, trip] + list(kick)
            entries.append((TRIPS, key, "paired", _prime_product(ranks)))

    # Straight (non-flush): ordered by position in _STRAIGHT_MASKS.
    for order, mask in enumerate(_STRAIGHT_MASKS):
        entries.append((STRAIGHT, (order,), "unique", mask))

    # Flush (non-straight): same masks as high card.
    for combo in combinations(range(13), 5):
        mask = _rank_mask(combo)
        if mask in _STRAIGHT_MASK_SET:
            continue
        key = tuple(sorted(combo, reverse=True))
        entries.append((FLUSH, key, "flush", mask))

    # Full house: trip rank + pair rank (distinct).
    for trip in range(13):
        for pair in range(13):
            if pair == trip:
                continue
            key = (trip, pair)
            ranks = [trip, trip, trip, pair, pair]
            entries.append((FULL_HOUSE, key, "paired", _prime_product(ranks)))

    # Quads: quad rank + kicker.
    for quad in range(13):
        for kicker in range(13):
            if kicker == quad:
                continue
            key = (quad, kicker)
            ranks = [quad, quad, quad, quad, kicker]
            entries.append((QUADS, key, "paired", _prime_product(ranks)))

    # Straight flush: same masks as straight.
    for order, mask in enumerate(_STRAIGHT_MASKS):
        entries.append((STRAIGHT_FLUSH, (order,), "flush", mask))

    # Sort: weakest first. Strength = 1-based rank after sorting.
    entries.sort(key=lambda e: (e[0], e[1]))
    for strength, (category, _key, kind, payload) in enumerate(entries, start=1):
        if kind == "unique":
            UNIQUE5_TABLE[payload] = strength
        elif kind == "flush":
            FLUSH_TABLE[payload] = strength
        else:  # paired
            PAIRED_TABLE[payload] = strength

    assert len(entries) == 7462, f"expected 7462 hand types, got {len(entries)}"


_build_tables()


def eval5(cards: Sequence[int]) -> int:
    """Evaluate exactly five cards (ints 0..51); higher strength is better."""
    c0, c1, c2, c3, c4 = cards
    is_flush = (c0 & 3) == (c1 & 3) == (c2 & 3) == (c3 & 3) == (c4 & 3)
    mask = (1 << (c0 >> 2)) | (1 << (c1 >> 2)) | (1 << (c2 >> 2)) \
        | (1 << (c3 >> 2)) | (1 << (c4 >> 2))
    if mask.bit_count() == 5:
        return FLUSH_TABLE[mask] if is_flush else UNIQUE5_TABLE[mask]
    # Paired hand: key by prime product.
    prod = PRIMES[c0 >> 2] * PRIMES[c1 >> 2] * PRIMES[c2 >> 2] \
        * PRIMES[c3 >> 2] * PRIMES[c4 >> 2]
    return PAIRED_TABLE[prod]


# Precompute the 21 index combinations of 7 choose 5 for the hot path.
_C7 = list(combinations(range(7), 5))


def eval7(cards: Sequence[int]) -> int:
    """Best 5-of-7 strength. ``cards`` must have length 7."""
    best = 0
    for a, b, c, d, e in _C7:
        s = eval5((cards[a], cards[b], cards[c], cards[d], cards[e]))
        if s > best:
            best = s
    return best


def evaluate(cards: Sequence[int]) -> int:
    """Evaluate a hand of 5, 6 or 7 cards."""
    n = len(cards)
    if n == 5:
        return eval5(cards)
    if n == 7:
        return eval7(cards)
    if n == 6 or n > 7:
        best = 0
        for combo in combinations(cards, 5):
            s = eval5(combo)
            if s > best:
                best = s
        return best
    raise ValueError(f"need 5..7 cards, got {n}")


def category_of(strength: int) -> int:
    """Map a strength value back to its category constant (HIGH_CARD..SF)."""
    # Boundaries derived from the textbook distinct-value counts.
    if strength <= 1277:
        return HIGH_CARD
    if strength <= 1277 + 2860:
        return PAIR
    if strength <= 1277 + 2860 + 858:
        return TWO_PAIR
    if strength <= 1277 + 2860 + 858 + 858:
        return TRIPS
    if strength <= 1277 + 2860 + 858 + 858 + 10:
        return STRAIGHT
    if strength <= 1277 + 2860 + 858 + 858 + 10 + 1277:
        return FLUSH
    if strength <= 1277 + 2860 + 858 + 858 + 10 + 1277 + 156:
        return FULL_HOUSE
    if strength <= 1277 + 2860 + 858 + 858 + 10 + 1277 + 156 + 156:
        return QUADS
    return STRAIGHT_FLUSH


def category_name(strength: int) -> str:
    return CATEGORY_NAMES[category_of(strength)]
