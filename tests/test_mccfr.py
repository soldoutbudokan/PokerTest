"""MCCFR / compiled-tree NLHE solver tests."""
import random

from pokerbot.agents.base import StrategyAgent
from pokerbot.agents.baselines import CallStationAgent, RandomAgent
from pokerbot.eval.arena import play_match
from pokerbot.games.nlhe import NLHEConfig, NLHEGame
from pokerbot.games.nlhe_abstraction import NullAbstraction
from pokerbot.games.nlhe import CALL
from pokerbot.solve.mccfr import ChanceSampledCFR
from pokerbot.solve.nlhe_tree import (CompiledBettingTree, FastExploiterCFR,
                                      FastNLHECFR)


def _game():
    return NLHEGame(NLHEConfig(stack=20.0, bet_sizes=(1.0,),
                               max_raises_per_street=3), NullAbstraction())


def test_compiled_tree_structure_matches_object_walk():
    g = _game()
    tree = CompiledBettingTree.build(g)
    # Count nodes by walking the object game for one fixed deal.
    s = g.new_initial_state((((0, 4), (8, 12)), (16, 20, 24, 28, 32)))
    count = [0]

    def walk(st):
        count[0] += 1
        if st.is_terminal():
            return
        for a in st.legal_actions():
            walk(st.apply_action(a))

    walk(s)
    assert tree.num_nodes == count[0]


def test_fast_and_object_mccfr_agree_on_keys():
    """Both trainers must produce strategies a StrategyAgent can query."""
    g = _game()
    rng = random.Random(0)
    fast = FastNLHECFR(g)
    fast.run(2000, rng)
    fkeys = set(fast.average_strategy().table)
    slow = ChanceSampledCFR(g)
    slow.run(2000, random.Random(0))
    skeys = set(slow.average_strategy().table)
    # The two key spaces should overlap heavily (same key format).
    assert len(fkeys & skeys) > 0.5 * min(len(fkeys), len(skeys))


def test_trained_bot_beats_random_and_callstation():
    g = _game()
    s = FastNLHECFR(g)
    s.run(20000, random.Random(1))
    bot = StrategyAgent(s.average_strategy(), "bot")
    for opp in (RandomAgent(), CallStationAgent()):
        res = play_match(g, bot, opp, num_pairs=1500, seed=7)
        assert res.bb_per_100 > 0, opp.name


def test_lazy_regret_weight_matches_dcfr_discount():
    """The lazy weight must be the exact inverse of DCFR's positive-regret
    discount, i.e. w_T * prod_{t<=T} t^a/(t^a+1) == 1."""
    g = _game()
    for alpha in (1.0, 1.5, 3.0):
        s = FastNLHECFR(g, alpha=alpha, gamma=2.0)
        s.run(200, random.Random(0))
        prod = 1.0
        for t in range(1, s.iterations + 1):
            ta = float(t) ** alpha
            prod *= ta / (ta + 1.0)
        assert abs(s._regret_weight * prod - 1.0) < 1e-9, alpha


def test_undiscounted_trainer_is_plain_cfr_plus():
    """alpha=None/gamma=1 must leave the CFR+ updates numerically untouched."""
    g = _game()
    s = FastNLHECFR(g, alpha=None, gamma=1.0)
    s.run(500, random.Random(0))
    assert s._regret_weight == 1.0
    # Same seed, same trainer settings -> identical strategy (determinism).
    s2 = FastNLHECFR(g, alpha=None, gamma=1.0)
    s2.run(500, random.Random(0))
    assert s.average_strategy().table == s2.average_strategy().table


def test_alpha_below_one_is_rejected():
    """w_t would grow like exp(t^(1-alpha)) and overflow."""
    import pytest
    with pytest.raises(ValueError):
        FastNLHECFR(_game(), alpha=0.5)


def test_discounted_trainer_beats_baselines():
    g = _game()
    s = FastNLHECFR(g, alpha=1.5, gamma=2.0)
    s.run(20000, random.Random(1))
    bot = StrategyAgent(s.average_strategy(), "bot")
    for opp in (RandomAgent(), CallStationAgent()):
        res = play_match(g, bot, opp, num_pairs=1500, seed=7)
        assert res.bb_per_100 > 0, opp.name


def test_exploiter_crushes_always_call():
    """A best response must strongly beat a trivially exploitable strategy."""
    from pokerbot.eval.arena import play_directional

    class AlwaysCall:
        def action_probs(self, key, legal):
            return {CALL: 1.0}

    g = _game()
    ex = FastExploiterCFR(g, AlwaysCall(), exploiter=0)
    ex.run(20000, random.Random(1))
    br = StrategyAgent(ex.average_strategy(), "BR")
    r = play_directional(g, br, CallStationAgent(), 8000, seed=3)
    assert r.bb_per_100 > 100.0       # value-betting relentlessly wins big
