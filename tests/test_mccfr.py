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


class _NaiveDCFR(FastNLHECFR):
    """Reference DCFR that discounts **every** node after **every** iteration.

    The shipped trainer instead defers each node's discount until the node is
    next visited (see ``_DNode``).  This reference exists to pin that the two
    are numerically identical, not to be fast.
    """

    def run(self, iterations, rng=None):
        rng = rng or random.Random()
        ab = self.game.abstraction
        for _ in range(iterations):
            self.iterations += 1
            t = self.iterations
            w = float(t) ** self.gamma
            hole, board = self.game.deal(rng)
            self._cfr(self.tree.root, 1.0, 1.0, t, w, hole, board, ab, {}, [None])
            ta, tb = float(t) ** self.alpha, float(t) ** self.beta
            fpos, fneg = ta / (ta + 1.0), tb / (tb + 1.0)
            for node in self.nodes.values():
                rs = node.regret_sum
                for i in range(len(rs)):
                    rs[i] *= fpos if rs[i] > 0.0 else fneg
                # Discounts through iteration t are now applied, so the lazy
                # catch-up in ``_cfr`` must be a no-op on the next visit.
                node.last = t + 1


def test_lazy_discounting_matches_naive_dcfr():
    """Deferred per-node discounting == discounting the whole table each pass."""
    g = _game()
    lazy = FastNLHECFR(g, variant="dcfr")
    lazy.run(400, random.Random(3))
    naive = _NaiveDCFR(g, variant="dcfr")
    naive.run(400, random.Random(3))

    a, b = lazy.average_strategy().table, naive.average_strategy().table
    assert set(a) == set(b) and a
    for key, probs in a.items():
        for action, p in probs.items():
            assert abs(p - b[key][action]) < 1e-9, (key, action)


def test_cfrplus_variant_floors_negative_regrets():
    """``variant="cfr+"`` keeps regret-matching-plus (the pre-DCFR rule)."""
    g = _game()
    s = FastNLHECFR(g, variant="cfr+")
    s.run(300, random.Random(0))
    assert all(r >= 0.0 for node in s.nodes.values() for r in node.regret_sum)
    # DCFR, by contrast, keeps (discounted) negative regrets around.
    d = FastNLHECFR(g, variant="dcfr")
    d.run(300, random.Random(0))
    assert any(r < 0.0 for node in d.nodes.values() for r in node.regret_sum)


def test_dcfr_trained_bot_beats_baselines():
    g = _game()
    s = FastNLHECFR(g, variant="dcfr")
    s.run(20000, random.Random(1))
    bot = StrategyAgent(s.average_strategy(), "bot")
    for opp in (RandomAgent(), CallStationAgent()):
        res = play_match(g, bot, opp, num_pairs=1500, seed=7)
        assert res.bb_per_100 > 0, opp.name
