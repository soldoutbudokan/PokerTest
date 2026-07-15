"""A blueprint agent augmented with real-time **river subgame search**.

:class:`SearchAgent` plays the trained blueprint everywhere except the river,
where it re-solves the current subgame at (near-)unabstracted granularity using
the opponent's blueprint-implied range (see
:mod:`pokerbot.solve.subgame`).  It is a drop-in :class:`Agent`:

* with ``enabled=False`` it is byte-for-byte a :class:`StrategyAgent` (pure
  blueprint) — the additive/gated requirement;
* the re-solve is fully deterministic, so play is reproducible under a seeded
  ``rng`` exactly like the blueprint.

This also **replaces the blueprint's off-strategy fallback on the river**: where
a plain :class:`StrategyAgent` would play uniformly at random on an unseen
river info-set key, the search agent instead plays the re-solved strategy for
its exact hand.
"""
from __future__ import annotations

import random
from typing import Optional

from ..games.nlhe import RIVER
from ..solve.cfr import TabularStrategy
from ..solve.nlhe_tree import CompiledBettingTree
from ..solve.subgame import RiverSubgameSolver
from .base import Agent, StrategyAgent, sample_from


class SearchAgent(Agent):
    def __init__(self, blueprint: TabularStrategy, game,
                 tree: Optional[CompiledBettingTree] = None,
                 iterations: int = 200, enabled: bool = True,
                 solver: Optional[RiverSubgameSolver] = None,
                 name: str = "cfr-bot+search"):
        self.blueprint = blueprint
        self.game = game
        self.tree = tree or CompiledBettingTree.build(game)
        self.enabled = enabled
        self.name = name
        if solver is not None:
            self.solver = solver
        elif enabled:
            self.solver = RiverSubgameSolver(game, blueprint, tree=self.tree,
                                             iterations=iterations)
        else:
            self.solver = None

    def act(self, state, rng: random.Random) -> int:
        legal = state.legal_actions()
        if self.enabled and self.solver is not None and state.street == RIVER:
            me = state.current_player()
            probs = self.solver.river_action_probs(
                state.board, state.hist, state.hole[me], me, legal)
            if probs is not None:
                return sample_from(probs, legal, rng)
        # Blueprint elsewhere (and as a safety fallback if the re-solve declines).
        probs = self.blueprint.action_probs(state.information_set_key(), legal)
        return sample_from(probs, legal, rng)
