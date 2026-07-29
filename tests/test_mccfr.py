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


def test_training_is_deterministic_for_a_fixed_seed():
    """Same seed, same bot — the trainer must have no hidden state."""
    g = _game()
    a = FastNLHECFR(g)
    a.run(1500, random.Random(0))
    b = FastNLHECFR(g)
    b.run(1500, random.Random(0))
    ta, tb = a.average_strategy().table, b.average_strategy().table
    assert ta.keys() == tb.keys()
    assert all(ta[k] == tb[k] for k in ta)


def test_gamma_weighting_matches_dcfr_strategy_discount():
    """Accumulating ``t ** gamma`` must equal DCFR's iterative discount.

    DCFR multiplies the running strategy sum by ``(t / (t + 1)) ** gamma``
    after every iteration and adds the current strategy with weight 1.  The
    trainer instead adds it with weight ``t ** gamma`` and never sweeps the
    table; the two give the same *normalised* average.  ``gamma = 0`` makes
    the trainer add weight 1, so it doubles as the reference implementation.

    The strategy sum never feeds back into play (only regrets do, and those are
    identical here), so both runs follow the same trajectory and this holds to
    float precision rather than approximately.
    """
    g = _game()
    tree = CompiledBettingTree.build(g)
    for gamma in (1.0, 2.0, 3.0):
        closed = FastNLHECFR(g, tree, gamma=gamma)
        closed.run(300, random.Random(3))

        ref = FastNLHECFR(g, tree, gamma=0.0)      # adds weight 1 per iteration
        rng = random.Random(3)
        for _ in range(300):
            ref.run(1, rng)
            f = (ref.iterations / (ref.iterations + 1.0)) ** gamma
            for node in ref.nodes.values():
                ss = node.strategy_sum
                for i in range(len(ss)):
                    ss[i] *= f

        tc, tr = closed.average_strategy().table, ref.average_strategy().table
        assert tc.keys() == tr.keys()
        for k in tc:
            for a_, p in tc[k].items():
                assert abs(p - tr[k][a_]) < 1e-9, (gamma, k, a_, p, tr[k][a_])
