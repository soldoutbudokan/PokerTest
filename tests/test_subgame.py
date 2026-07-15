"""River subgame re-solving: solver correctness, determinism, and the
additive/non-regression properties of the search hooks."""
import random

import numpy as np

from pokerbot.agents.base import StrategyAgent
from pokerbot.agents.baselines import CallStationAgent
from pokerbot.agents.search import SearchAgent
from pokerbot.eval.arena import play_match
from pokerbot.games.nlhe import (CALL, FOLD, RIVER, NLHEConfig, NLHEGame)
from pokerbot.games.nlhe_abstraction import StrengthAbstraction
from pokerbot.solve.nlhe_tree import (CompiledBettingTree, FastExploiterCFR,
                                      FastNLHECFR, matchup_value, DECISION)
from pokerbot.solve.subgame import (RiverSubgameSolver, river_root_hist,
                                    subgame_exploitability)


def _setup(train=6000, seed=0):
    cfg = NLHEConfig(stack=20.0, bet_sizes=(1.0,), max_raises_per_street=3)
    ab = StrengthAbstraction(postflop_buckets=8)
    g = NLHEGame(cfg, ab)
    tree = CompiledBettingTree.build(g)
    tr = FastNLHECFR(g, tree)
    tr.run(train, random.Random(seed))
    return g, tree, tr.average_strategy()


def _river_roots(tree):
    return [nid for nid in range(tree.num_nodes)
            if tree.kind[nid] == DECISION and tree.dec_street[nid] == RIVER
            and river_root_hist(tree.dec_hist[nid]) == tree.dec_hist[nid]]


def test_river_root_hist():
    assert river_root_hist("cc/cc/cc/") == "cc/cc/cc/"
    assert river_root_hist("cc/cc/rc/rr") == "cc/cc/rc/"
    assert river_root_hist("rc/cc/crc/crr") == "rc/cc/crc/"
    assert river_root_hist("cc/cc/") is None          # only two streets closed
    assert river_root_hist("") is None


def test_solver_converges_on_river_subgame():
    """More CFR iterations must drive the subgame's own exploitability down."""
    g, tree, bp = _setup()
    board = tuple(random.Random(7).sample(range(52), 5))
    root = _river_roots(tree)[0]
    expls = []
    for it in (20, 120):
        s = RiverSubgameSolver(g, bp, tree=tree, iterations=it)
        sol = s.solve(board, root)
        expls.append(subgame_exploitability(sol, s, board, root))
    assert expls[1] < expls[0]                        # converging
    assert expls[1] < 0.5                             # and reasonably tight (chips)


def test_nut_hand_never_folds():
    """The best possible hand in the range must not fold at a river decision."""
    g, tree, bp = _setup()
    board = tuple(random.Random(3).sample(range(52), 5))
    s = RiverSubgameSolver(g, bp, tree=tree, iterations=150)
    root = _river_roots(tree)[0]
    sol = s.solve(board, root)
    nut = int(max(sol.strengths))
    for nid, acts in sol.actions.items():
        if tree.dec_player[nid] == 0 and FOLD in acts:
            probs = sol.action_probs(nid, nut)
            # Regret-matching leaves a negligible residual from early iterations;
            # the nut hand folds essentially never.
            assert probs[FOLD] < 1e-3
            return
    raise AssertionError("no P0 decision node offering FOLD was found")


def test_solve_is_deterministic_and_cached():
    g, tree, bp = _setup()
    board = tuple(random.Random(11).sample(range(52), 5))
    root = _river_roots(tree)[0]
    a = RiverSubgameSolver(g, bp, tree=tree, iterations=80).solve(board, root)
    b = RiverSubgameSolver(g, bp, tree=tree, iterations=80).solve(board, root)
    assert set(a.avg) == set(b.avg)
    for nid in a.avg:
        assert np.allclose(a.avg[nid], b.avg[nid])
    # Cache: solving twice on one solver does no extra work.
    s = RiverSubgameSolver(g, bp, tree=tree, iterations=80)
    s.solve(board, root)
    s.solve(board, root)
    assert s.solves == 1


def test_search_disabled_matches_blueprint():
    """A SearchAgent with search off must decide exactly like a StrategyAgent."""
    g, tree, bp = _setup()
    plain = StrategyAgent(bp, "bp")
    off = SearchAgent(bp, g, tree=tree, enabled=False)
    for seed in range(20):
        deal = g.deal(random.Random(100 + seed))
        st = g.new_initial_state(deal)
        while not st.is_terminal():
            a1 = plain.act(st, random.Random(seed))
            a2 = off.act(st, random.Random(seed))
            assert a1 == a2
            legal = st.legal_actions()
            st = st.apply_action(a1 if a1 in legal else legal[0])


def test_matchup_search_none_matches_plain():
    """search=None must leave matchup_value bit-for-bit unchanged."""
    g, tree, bp = _setup()
    m0, _ = matchup_value(g, bp, bp, 400, random.Random(5), tree=tree)
    m1, _ = matchup_value(g, bp, bp, 400, random.Random(5), tree=tree,
                          search=None, search_seats=(0, 1))
    assert m0 == m1


def test_search_agent_beats_call_station():
    """Sanity: enabling river search does not break basic dominance."""
    g, tree, bp = _setup(train=15000)
    sbot = SearchAgent(bp, g, tree=tree, iterations=150)
    res = play_match(g, sbot, CallStationAgent(), num_pairs=200, seed=5)
    assert res.bb_per_100 > 0


def test_search_not_worse_than_blueprint_exploitability():
    """Enabling river search must not RAISE exploitability beyond noise.

    A small, fast in-abstraction check on a tiny board pool: the search bot's
    two-seat best-response value should not exceed the blueprint's by a wide
    margin.  (The high-fidelity measurement lives in ``pokerbot.metrics``.)
    """
    from pokerbot.metrics import _board_pool_dealer, _pool_exploitability
    g, tree, bp = _setup(train=15000)
    _, deal_fn = _board_pool_dealer(12, 999)
    bl = _pool_exploitability(g, bp, tree, deal_fn, 6000, 3000, 200, solver=None)
    solver = RiverSubgameSolver(g, bp, tree=tree, iterations=120)
    se = _pool_exploitability(g, bp, tree, deal_fn, 6000, 3000, 200, solver=solver)
    assert se <= bl + 6.0            # generous margin: catches gross regressions
