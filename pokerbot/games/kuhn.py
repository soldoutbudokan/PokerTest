"""Kuhn poker — the classic 3-card toy game used to validate CFR.

Rules: a 3-card deck {J, Q, K}.  Each player antes 1 and is dealt one private
card.  Player 0 acts first.

* check / bet(1)
* facing a bet: call / fold

If nobody bets, or a bet is called, the higher card wins the pot at showdown.
A fold gives the pot to the bettor.

Kuhn poker has a known analytic Nash equilibrium (a one-parameter family) and a
game value of -1/18 to the first player.  Both facts are used as objective
correctness checks for the solver in ``tests/test_kuhn.py``.
"""
from __future__ import annotations

from itertools import permutations
from typing import List, Tuple

from .base import CHANCE_PLAYER, Game, GameState

# Actions
PASS = 0   # check or fold (a "no bet" action)
BET = 1    # bet or call (a "put chips in" action)
ACTION_LABELS = {PASS: "p", BET: "b"}

JACK, QUEEN, KING = 0, 1, 2
CARD_NAMES = {JACK: "J", QUEEN: "Q", KING: "K"}


class KuhnState(GameState):
    __slots__ = ("cards", "history")

    def __init__(self, cards: Tuple[int, ...], history: Tuple[int, ...]):
        self.cards = cards          # (p0_card, p1_card) once dealt; () before
        self.history = history      # sequence of PASS/BET actions

    # --- node type ---
    def is_chance(self) -> bool:
        return len(self.cards) < 2

    def is_terminal(self) -> bool:
        if len(self.cards) < 2:
            return False
        h = self.history
        # Terminal histories: pp, pbp, pbb, bp, bb
        if h in {(PASS, PASS), (PASS, BET, PASS), (PASS, BET, BET),
                 (BET, PASS), (BET, BET)}:
            return True
        return False

    def current_player(self) -> int:
        if self.is_chance():
            return CHANCE_PLAYER
        return len(self.history) % 2

    # --- chance ---
    def chance_outcomes(self) -> List[Tuple[int, float]]:
        # Deal both private cards in one chance step: 6 equally likely deals.
        deals = list(permutations(range(3), 2))
        p = 1.0 / len(deals)
        # Encode a deal as an action id = p0card * 3 + p1card.
        return [(c0 * 3 + c1, p) for (c0, c1) in deals]

    # --- transitions ---
    def apply_action(self, action: int) -> "KuhnState":
        if self.is_chance():
            c0, c1 = divmod(action, 3)
            return KuhnState((c0, c1), self.history)
        return KuhnState(self.cards, self.history + (action,))

    def legal_actions(self) -> List[int]:
        return [PASS, BET]

    def information_set_key(self) -> str:
        player = self.current_player()
        card = self.cards[player]
        hist = "".join(ACTION_LABELS[a] for a in self.history)
        return f"{CARD_NAMES[card]}:{hist}"

    def returns(self) -> List[float]:
        h = self.history
        c0, c1 = self.cards
        winner_by_card = 0 if c0 > c1 else 1
        if h == (PASS, PASS):
            return self._payoff(winner_by_card, 1)
        if h == (BET, BET) or h == (PASS, BET, BET):
            return self._payoff(winner_by_card, 2)
        if h == (BET, PASS):
            return self._payoff(0, 1)            # p1 folded
        if h == (PASS, BET, PASS):
            return self._payoff(1, 1)            # p0 folded
        raise ValueError(f"returns() on non-terminal history {h}")

    @staticmethod
    def _payoff(winner: int, amount: float) -> List[float]:
        return [amount, -amount] if winner == 0 else [-amount, amount]

    def signature(self):
        return (self.cards, self.history)

    def action_label(self, action: int) -> str:
        return ACTION_LABELS.get(action, str(action))


class KuhnPoker(Game):
    num_players = 2

    def new_initial_state(self) -> KuhnState:
        return KuhnState(cards=(), history=())

    def num_distinct_actions(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return "KuhnPoker"

    def action_label(self, action: int) -> str:
        return ACTION_LABELS.get(action, str(action))
