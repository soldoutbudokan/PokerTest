"""Agent interface: map a decision state to a chosen action."""
from __future__ import annotations

import random
from typing import Dict, List

from ..games.base import GameState
from ..solve.cfr import TabularStrategy


class Agent:
    name: str = "agent"

    def act(self, state: GameState, rng: random.Random) -> int:
        raise NotImplementedError

    def reset(self) -> None:
        pass


def sample_from(probs: Dict[int, float], legal: List[int],
                rng: random.Random) -> int:
    """Sample an action id from a probability dict, restricted to ``legal``."""
    items = [(a, probs.get(a, 0.0)) for a in legal]
    total = sum(p for _, p in items)
    if total <= 0.0:
        return rng.choice(legal)
    r = rng.random() * total
    cum = 0.0
    for a, p in items:
        cum += p
        if r <= cum:
            return a
    return items[-1][0]


class StrategyAgent(Agent):
    """Plays a trained average strategy (samples from the mixed action probs)."""

    def __init__(self, strategy: TabularStrategy, name: str = "cfr-bot"):
        self.strategy = strategy
        self.name = name

    def act(self, state: GameState, rng: random.Random) -> int:
        legal = state.legal_actions()
        probs = self.strategy.action_probs(state.information_set_key(), legal)
        return sample_from(probs, legal, rng)
