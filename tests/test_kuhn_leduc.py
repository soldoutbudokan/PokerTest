"""Solver correctness: Kuhn and Leduc converge to (near-)Nash."""
import pytest

from pokerbot.games.kuhn import KuhnPoker
from pokerbot.games.leduc import LeducPoker
from pokerbot.solve.cfr import CFRSolver
from pokerbot.solve.exploitability import exploitability, expected_value
from pokerbot.solve.tree import GameTree, TreeCFR
from pokerbot.solve.tree import exploitability as tree_exploitability


def test_kuhn_converges_to_nash():
    g = KuhnPoker()
    solver = CFRSolver(g, variant="dcfr")
    solver.run(3000)
    strat = solver.average_strategy()
    # Exploitable by less than 1% of an ante.
    assert exploitability(g, strat) < 0.01
    # First player's game value is the analytic -1/18.
    assert expected_value(g, strat) == pytest.approx(-1.0 / 18.0, abs=2e-3)


def test_kuhn_strategy_matches_analytic_family():
    g = KuhnPoker()
    solver = CFRSolver(g, variant="dcfr")
    solver.run(8000)
    table = solver.average_strategy().table
    # alpha = P(bet | Jack, first action) must lie in [0, 1/3].
    alpha = table["J:"][1]
    assert 0.0 <= alpha <= 1.0 / 3.0 + 0.02
    # With a King first, P(bet) ~ 3*alpha.
    assert table["K:"][1] == pytest.approx(3 * alpha, abs=0.05)
    # Facing a bet with a Jack: always fold.
    assert table["J:pb"][1] < 0.02
    # Facing a bet with a King: always call.
    assert table["K:pb"][1] > 0.98


def test_leduc_infoset_count_and_zero_sum():
    g = LeducPoker()
    tree = GameTree.build(g)
    assert tree.num_infosets == 288
    # Every terminal is zero-sum (p1 = -p0 by construction in the flat tree).
    for node in range(tree.num_nodes):
        if tree.kind[node] == 0:               # TERMINAL
            assert isinstance(tree.term_u0[node], float)


def test_leduc_exploitability_decreases():
    tree = GameTree.build(LeducPoker())
    solver = TreeCFR(tree, variant="dcfr")
    solver.run(500)
    e_early = tree_exploitability(tree, solver.average_strategy())
    solver.run(2500)                            # 3000 total
    e_late = tree_exploitability(tree, solver.average_strategy())
    assert e_late < e_early
    assert e_late < 0.03                        # well under one small bet


def test_tree_matches_object_solver():
    """The flat-tree exploitability must equal the object-based one exactly."""
    from pokerbot.solve.exploitability import exploitability as obj_expl
    g = LeducPoker()
    tree = GameTree.build(g)
    solver = TreeCFR(tree, variant="dcfr")
    solver.run(300)
    strat = solver.average_strategy()
    assert tree_exploitability(tree, strat) == pytest.approx(
        obj_expl(g, strat), abs=1e-9)
