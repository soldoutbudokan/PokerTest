"""Card representation and parsing.

A card is encoded as an integer 0..51 with::

    rank = card // 4     # 0..12  (2,3,4,5,6,7,8,9,T,J,Q,K,A)
    suit = card % 4      # 0..3   (c,d,h,s)

This compact integer form keeps the hand evaluator and deck handling fast and
allocation-free, while the string helpers (``"As"``, ``"Td"``) are used for
parsing test cases and printing.
"""
from __future__ import annotations

from typing import Iterable, List

RANKS = "23456789TJQKA"
SUITS = "cdhs"

RANK_TO_INT = {r: i for i, r in enumerate(RANKS)}
SUIT_TO_INT = {s: i for i, s in enumerate(SUITS)}


def make_card(rank: int, suit: int) -> int:
    """Build a card integer from a 0-based rank (0=2 .. 12=A) and suit (0..3)."""
    if not (0 <= rank <= 12):
        raise ValueError(f"rank out of range: {rank}")
    if not (0 <= suit <= 3):
        raise ValueError(f"suit out of range: {suit}")
    return rank * 4 + suit


def card_rank(card: int) -> int:
    return card // 4


def card_suit(card: int) -> int:
    return card % 4


def parse_card(text: str) -> int:
    """Parse a two-character card such as ``"As"`` or ``"Td"`` into an int."""
    text = text.strip()
    if len(text) != 2:
        raise ValueError(f"invalid card string: {text!r}")
    rank_ch, suit_ch = text[0].upper(), text[1].lower()
    if rank_ch not in RANK_TO_INT:
        raise ValueError(f"invalid rank: {rank_ch!r}")
    if suit_ch not in SUIT_TO_INT:
        raise ValueError(f"invalid suit: {suit_ch!r}")
    return make_card(RANK_TO_INT[rank_ch], SUIT_TO_INT[suit_ch])


def parse_cards(text: str) -> List[int]:
    """Parse a string like ``"As Kd 2c"`` (whitespace separated) into ints."""
    return [parse_card(tok) for tok in text.split()]


def card_str(card: int) -> str:
    return RANKS[card_rank(card)] + SUITS[card_suit(card)]


def cards_str(cards: Iterable[int]) -> str:
    return " ".join(card_str(c) for c in cards)


def full_deck() -> List[int]:
    """Return a fresh 52-card deck as a list of ints 0..51."""
    return list(range(52))
