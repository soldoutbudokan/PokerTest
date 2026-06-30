"""Hand evaluator correctness tests."""
from itertools import combinations

import pytest

from pokerbot.cards import parse_cards
from pokerbot.evaluator import (CATEGORY_NAMES, category_of, eval5, eval7,
                                evaluate)


def test_category_frequencies():
    """Enumerate all 2,598,960 five-card hands; counts must match the textbook."""
    from collections import Counter
    counts = Counter()
    distinct = set()
    for combo in combinations(range(52), 5):
        s = eval5(combo)
        counts[category_of(s)] += 1
        distinct.add(s)
    expected = {
        "High Card": 1302540, "Pair": 1098240, "Two Pair": 123552,
        "Three of a Kind": 54912, "Straight": 10200, "Flush": 5108,
        "Full House": 3744, "Four of a Kind": 624, "Straight Flush": 40,
    }
    for cat in range(9):
        assert counts[cat] == expected[CATEGORY_NAMES[cat]], CATEGORY_NAMES[cat]
    assert len(distinct) == 7462


@pytest.mark.parametrize("strong,weak", [
    ("As Ks Qs Js Ts", "Ah Kh Qh Jh 9h"),   # royal flush > king-high flush
    ("2c 2d 2h 2s 3c", "Ac Ad Ah Ks Qd"),    # quad deuces > aces full
    ("5c 6c 7c 8c 9c", "Ac Ad Ah As Kd"),    # straight flush > quads
    ("Ac Ad Ah Kc Kd", "Ac Ad Ah Qc Jd"),    # aces full > trip aces
    ("9h 9d 9s 2c 3d", "8h 8d 8s Ac Kd"),    # trip nines > trip eights
    ("Ah Kh Qh Jh 9h", "Ah Kd Qc Js 9h"),    # flush > ace-high
])
def test_pairwise_ordering(strong, weak):
    assert eval5(parse_cards(strong)) > eval5(parse_cards(weak))


def test_wheel_straight():
    wheel = eval5(parse_cards("Ah 2d 3c 4s 5h"))      # 5-high straight
    six_high = eval5(parse_cards("2h 3d 4c 5s 6h"))   # 6-high straight
    assert category_of(wheel) == category_of(six_high)
    assert wheel < six_high                            # wheel is the lowest


def test_eval7_picks_best_five():
    # Board makes a flush; the two extra cards shouldn't lower the score.
    seven = parse_cards("As Ks 7s 2s 9s 2d 2h")
    assert category_of(eval7(seven)) == 5              # flush, not the trip 2s
    # A seven-card hand with quads available.
    quads = parse_cards("Ac Ad Ah As Kc Kd 2h")
    assert category_of(evaluate(quads)) == 7           # four of a kind


def test_evaluate_six_cards():
    six = parse_cards("Ac Ad Ah Kc Kd 2h")             # aces full of kings
    assert category_of(evaluate(six)) == 6
