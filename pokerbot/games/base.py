"""Abstract extensive-form game interface.

Every game (Kuhn, Leduc, abstracted No-Limit Hold'em) exposes the same small
interface so that a single CFR solver, best-response/exploitability calculator,
and match engine work across all of them.

A *state* is one node of the game tree.  Nodes come in three kinds:

* **chance** – the deck/dealer acts; ``chance_outcomes()`` lists
  ``(action, probability)`` pairs that sum to 1.
* **decision** – ``current_player()`` (0 or 1) must choose from
  ``legal_actions()``.  ``information_set_key()`` returns the string that
  identifies what that player knows — all states sharing a key are
  indistinguishable to the acting player and share one strategy.
* **terminal** – ``returns()`` gives the payoff vector ``[u0, u1]``.

Games here are two-player zero-sum, so ``u1 == -u0`` always holds, but the
interface keeps the full vector for generality.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Sequence, Tuple

CHANCE_PLAYER = -1
TERMINAL = -2


class GameState(ABC):
    @abstractmethod
    def is_terminal(self) -> bool: ...

    @abstractmethod
    def is_chance(self) -> bool: ...

    @abstractmethod
    def current_player(self) -> int:
        """0 or 1 at a decision node; ``CHANCE_PLAYER`` at a chance node."""

    @abstractmethod
    def legal_actions(self) -> List[int]:
        """Action ids available at a decision node."""

    @abstractmethod
    def chance_outcomes(self) -> List[Tuple[int, float]]:
        """``(action, probability)`` pairs at a chance node (sum to 1)."""

    @abstractmethod
    def apply_action(self, action: int) -> "GameState":
        """Return the successor state after taking ``action``."""

    @abstractmethod
    def information_set_key(self) -> str:
        """Key identifying the acting player's information set."""

    @abstractmethod
    def returns(self) -> List[float]:
        """Payoff vector ``[u0, u1]`` at a terminal state."""

    def action_label(self, action: int) -> str:
        return str(action)

    def signature(self):
        """A hashable value uniquely identifying this state.

        Used to memoize tree walks (best response).  Subclasses must override.
        """
        raise NotImplementedError


class Game(ABC):
    """Factory + metadata for a game."""

    num_players: int = 2

    @abstractmethod
    def new_initial_state(self) -> GameState:
        """Return the root state of a fresh game."""

    @abstractmethod
    def num_distinct_actions(self) -> int:
        """Upper bound on action ids, so strategies can use dense arrays."""

    @property
    def name(self) -> str:
        return type(self).__name__

    def action_label(self, action: int) -> str:
        return str(action)


def normalized_chance(outcomes: Sequence[Tuple[int, float]]) -> List[Tuple[int, float]]:
    """Defensively renormalize a list of ``(action, prob)`` chance outcomes."""
    total = sum(p for _, p in outcomes)
    if total <= 0:
        raise ValueError("chance outcomes must have positive total probability")
    return [(a, p / total) for a, p in outcomes]
