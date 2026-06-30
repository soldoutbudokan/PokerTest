"""No-Limit Hold'em engine rules and arena statistics."""
import random

import pytest

from pokerbot.agents.baselines import (CallStationAgent, RandomAgent,
                                       TightAggressiveAgent)
from pokerbot.cards import parse_cards
from pokerbot.eval.arena import play_match
from pokerbot.games.nlhe import (ALL_IN, CALL, FOLD, RAISE_BASE, NLHEConfig,
                                 NLHEGame)
from pokerbot.games.nlhe_abstraction import NullAbstraction, preflop_index


def _fixed_deal():
    hole = ((parse_cards("As Ah")[0], parse_cards("As Ah")[1]),
            (parse_cards("Ks Kh")[0], parse_cards("Ks Kh")[1]))
    board = tuple(parse_cards("2c 3d 4h 7s 9c"))
    return hole, board


def _game(bet_sizes=(1.0,), **kw):
    return NLHEGame(NLHEConfig(stack=100.0, bet_sizes=bet_sizes, **kw),
                    NullAbstraction())


def test_zero_sum_random_play():
    g = _game(bet_sizes=(0.5, 1.0))
    rng = random.Random(123)
    for _ in range(5000):
        s = g.new_initial_state(rng=rng)
        depth = 0
        while not s.is_terminal():
            s = s.apply_action(rng.choice(s.legal_actions()))
            depth += 1
            assert depth < 300
        r = s.returns()
        assert r[0] + r[1] == pytest.approx(0.0, abs=1e-9)


def test_fold_and_blind_accounting():
    g = _game()
    hole, board = _fixed_deal()
    # SB folds pre-flop -> loses the small blind only.
    s = g.new_initial_state((hole, board)).apply_action(FOLD)
    assert s.returns() == [-0.5, 0.5]
    # SB raises pot, BB folds -> SB wins the big blind.
    s = g.new_initial_state((hole, board)).apply_action(RAISE_BASE).apply_action(FOLD)
    assert s.returns() == [1.0, -1.0]


def test_allin_showdown_pays_stack():
    g = _game()
    hole, board = _fixed_deal()                 # AA vs KK, AA wins
    s = g.new_initial_state((hole, board)).apply_action(ALL_IN).apply_action(CALL)
    assert s.returns() == [100.0, -100.0]


def test_big_blind_option():
    g = _game()
    hole, board = _fixed_deal()
    s = g.new_initial_state((hole, board)).apply_action(CALL)   # SB limps
    # Action passes to the big blind, who is not yet forced to fold/showdown.
    assert s.current_player() == 1
    assert not s.is_terminal()
    assert s.owe == 0.0                          # BB may check for free


def test_push_fold_legal_actions():
    g = NLHEGame(NLHEConfig(stack=10.0, bet_sizes=(), push_fold=True),
                 NullAbstraction())
    s = g.new_initial_state(_fixed_deal())
    assert sorted(s.legal_actions()) == sorted([FOLD, ALL_IN])  # jam or fold


def test_preflop_index_canonical():
    # 169 distinct hands, indices in range.
    seen = set()
    for c0 in range(52):
        for c1 in range(c0 + 1, 52):
            seen.add(preflop_index((c0, c1)))
    assert seen == set(range(169))


def test_tight_aggressive_beats_random_significantly():
    g = _game(max_raises_per_street=3)
    g = NLHEGame(NLHEConfig(stack=20.0, bet_sizes=(1.0,), max_raises_per_street=3),
                 NullAbstraction())
    res = play_match(g, TightAggressiveAgent(), RandomAgent(),
                     num_pairs=2000, seed=3)
    assert res.bb_per_100 > 0
    assert res.significant
