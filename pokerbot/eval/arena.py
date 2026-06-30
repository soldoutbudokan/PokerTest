"""Head-to-head match engine with mirrored (duplicate) variance reduction.

To measure skill rather than card luck we play every dealt scenario *twice*:
once with agent A on the button holding the first hand, and once with the cards
held fixed but the agents swapped.  Summed over the pair, the dealer/card
advantage cancels (an antithetic-variates / duplicate-poker design), which
shrinks the variance of the win-rate estimate by a large factor.

A match returns A's profit per mirrored pair (in big blinds), from which we
report win rate in **bb/100** and **mbb/100** with a 95% confidence interval
and a significance flag.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

from ..agents.base import Agent
from ..games.nlhe import NLHEGame


def _play_hand(game: NLHEGame, deal, agent0: Agent, agent1: Agent,
               rng: random.Random) -> float:
    """Play one hand; return player 0's profit in big blinds."""
    state = game.new_initial_state(deal)
    agents = (agent0, agent1)
    while not state.is_terminal():
        p = state.current_player()
        action = agents[p].act(state, rng)
        legal = state.legal_actions()
        if action not in legal:                 # safety net
            action = legal[0]
        state = state.apply_action(action)
    return state.returns()[0] / game.config.bb


class MatchResult:
    def __init__(self, samples: List[float], hands: int):
        self.samples = samples              # A's profit (bb) per mirrored pair
        self.hands = hands
        n = len(samples)
        self.n_pairs = n
        mean_pair = sum(samples) / n if n else 0.0
        # Per-hand profit = pair profit / 2 (two hands per pair).
        self.bb_per_hand = mean_pair / 2.0
        self.bb_per_100 = self.bb_per_hand * 100.0
        self.mbb_per_100 = self.bb_per_100 * 1000.0
        if n > 1:
            var = sum((x - mean_pair) ** 2 for x in samples) / (n - 1)
            se_pair = math.sqrt(var / n)
            self.se_bb_per_100 = se_pair / 2.0 * 100.0
        else:
            self.se_bb_per_100 = float("inf")
        self.ci95_bb_per_100 = 1.96 * self.se_bb_per_100

    @property
    def significant(self) -> bool:
        return abs(self.bb_per_100) > self.ci95_bb_per_100

    def summary(self, a_name: str, b_name: str) -> str:
        lo = self.bb_per_100 - self.ci95_bb_per_100
        hi = self.bb_per_100 + self.ci95_bb_per_100
        sig = "significant" if self.significant else "not significant"
        return (f"{a_name} vs {b_name}: {self.bb_per_100:+.2f} bb/100 "
                f"({self.mbb_per_100:+.0f} mbb/100), "
                f"95% CI [{lo:+.2f}, {hi:+.2f}], {self.hands} hands, {sig}")


def play_match(game: NLHEGame, agent_a: Agent, agent_b: Agent,
               num_pairs: int, seed: int = 0) -> MatchResult:
    """Play ``num_pairs`` mirrored deals; return A's win rate vs B."""
    rng = random.Random(seed)
    samples: List[float] = []
    for _ in range(num_pairs):
        deal = game.deal(rng)
        # Game 1: A is player 0, B is player 1.
        r1 = _play_hand(game, deal, agent_a, agent_b, rng)
        # Game 2: same cards, swap seats. B is player 0, A is player 1.
        r2 = _play_hand(game, deal, agent_b, agent_a, rng)
        # A's total profit over the mirrored pair.
        a_profit = r1 + (-r2)                # in game 2 A is player 1
        samples.append(a_profit)
    return MatchResult(samples, hands=num_pairs * 2)


class DirectionalResult:
    def __init__(self, profits: List[float]):
        n = len(profits)
        mean = sum(profits) / n if n else 0.0
        self.bb_per_100 = mean * 100.0
        if n > 1:
            var = sum((x - mean) ** 2 for x in profits) / (n - 1)
            self.se_bb_per_100 = math.sqrt(var / n) * 100.0
        else:
            self.se_bb_per_100 = float("inf")
        self.ci95_bb_per_100 = 1.96 * self.se_bb_per_100
        self.hands = n


def play_directional(game: NLHEGame, agent0: Agent, agent1: Agent,
                     num_hands: int, seed: int = 0) -> DirectionalResult:
    """Play ``num_hands`` with agent0 fixed as player 0; return its bb/100.

    Used for exploitability, where the best responder is trained for one seat
    and must be measured in that seat (no mirroring).
    """
    rng = random.Random(seed)
    profits = [_play_hand(game, game.deal(rng), agent0, agent1, rng)
               for _ in range(num_hands)]
    return DirectionalResult(profits)


def round_robin(game: NLHEGame, agents: List[Agent], num_pairs: int,
                seed: int = 0) -> List[Tuple[str, str, MatchResult]]:
    """Play every ordered pair A-vs-B once; return their match results."""
    results = []
    s = seed
    for i in range(len(agents)):
        for j in range(len(agents)):
            if i == j:
                continue
            s += 1
            res = play_match(game, agents[i], agents[j], num_pairs, seed=s)
            results.append((agents[i].name, agents[j].name, res))
    return results
