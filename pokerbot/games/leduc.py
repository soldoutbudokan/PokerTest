"""Leduc Hold'em — the standard small benchmark for CFR.

Deck: 6 cards, ranks {J, Q, K}, two of each.  Each player antes 1 and gets one
private card.  Two betting rounds; a single public card is revealed before the
second.  Fixed bet sizes (2 pre, 4 post), at most two bets/raises per round.  At
showdown a player who pairs the board wins; else the higher private rank wins;
equal ranks split.

Suits are irrelevant in Leduc (no flushes/straights), so we represent a card by
its rank only (0=J, 1=Q, 2=K) and let chance nodes emit rank outcomes with the
exact without-replacement probabilities from the two-of-each-rank deck.  This is
mathematically identical to dealing physical cards but keeps the tree small.

Action encoding:

* ``FOLD``  = 0
* ``CALL``  = 1  (check when nothing is owed, call when facing a bet)
* ``RAISE`` = 2  (bet when nothing is owed, raise when facing a bet)

Leduc has 288 information sets per traversal and CFR drives its exploitability
to ~0, which ``tests/test_leduc.py`` checks.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .base import CHANCE_PLAYER, Game, GameState

FOLD, CALL, RAISE = 0, 1, 2
ACTION_SYMBOL = {FOLD: "f", CALL: "c", RAISE: "r"}

ANTE = 1
RAISE_SIZE = (2, 4)     # round 0, round 1
MAX_BETS_PER_ROUND = 2
DECK_PER_RANK = 2
NUM_RANKS = 3
RANK_NAMES = {0: "J", 1: "Q", 2: "K"}


class LeducState(GameState):
    __slots__ = ("priv", "board", "street", "contrib", "bets",
                 "to_move", "street_hist", "folder", "history")

    def __init__(self, priv: Tuple[int, ...] = (), board: int = -1,
                 street: int = 0, contrib: Optional[List[int]] = None,
                 bets: int = 0, to_move: int = 0,
                 street_hist: Tuple[int, ...] = (), folder: int = -1,
                 history: str = ""):
        self.priv = priv
        self.board = board
        self.street = street
        self.contrib = contrib if contrib is not None else [ANTE, ANTE]
        self.bets = bets
        self.to_move = to_move
        self.street_hist = street_hist
        self.folder = folder
        self.history = history

    # --- node type ---
    def is_chance(self) -> bool:
        if len(self.priv) < 2:
            return True
        if self.folder == -1 and self.street == 0 and self.board == -1 \
                and self._street_closed():
            return True
        return False

    def is_terminal(self) -> bool:
        if self.folder != -1:
            return True
        if self.street == 1 and self._street_closed():
            return True
        return False

    def current_player(self) -> int:
        if self.is_chance():
            return CHANCE_PLAYER
        return self.to_move

    def _street_closed(self) -> bool:
        h = self.street_hist
        if not h:
            return False
        if h[-1] == CALL:
            if RAISE in h:
                return True                       # a bet was called
            return len(h) >= 2 and h[-2] == CALL  # check-check
        return False

    def _remaining_counts(self) -> List[int]:
        counts = [DECK_PER_RANK] * NUM_RANKS
        for r in self.priv:
            counts[r] -= 1
        if self.board >= 0:
            counts[self.board] -= 1
        return counts

    # --- chance ---
    def chance_outcomes(self) -> List[Tuple[int, float]]:
        if len(self.priv) < 2:
            # Deal two private ranks in order with exact probabilities.
            outcomes = []
            counts = [DECK_PER_RANK] * NUM_RANKS
            total = DECK_PER_RANK * NUM_RANKS
            for r0 in range(NUM_RANKS):
                p0 = counts[r0] / total
                counts[r0] -= 1
                for r1 in range(NUM_RANKS):
                    if counts[r1] == 0:
                        continue
                    p1 = counts[r1] / (total - 1)
                    outcomes.append((r0 * NUM_RANKS + r1, p0 * p1))
                counts[r0] += 1
            return outcomes
        # Deal the public rank from the remaining deck.
        counts = self._remaining_counts()
        total = sum(counts)
        return [(r, counts[r] / total) for r in range(NUM_RANKS) if counts[r] > 0]

    # --- transitions ---
    def apply_action(self, action: int) -> "LeducState":
        if self.is_chance():
            return self._apply_chance(action)
        return self._apply_bet(action)

    def _apply_chance(self, action: int) -> "LeducState":
        if len(self.priv) < 2:
            r0, r1 = divmod(action, NUM_RANKS)
            return LeducState(priv=(r0, r1))
        return LeducState(priv=self.priv, board=action, street=1,
                          contrib=list(self.contrib), bets=0, to_move=0,
                          street_hist=(), folder=-1,
                          history=self.history + "/")

    def _apply_bet(self, action: int) -> "LeducState":
        contrib = list(self.contrib)
        me = self.to_move
        opp = 1 - me
        bets = self.bets
        folder = -1
        deficit = contrib[opp] - contrib[me]

        if action == FOLD:
            folder = me
        elif action == CALL:
            contrib[me] += deficit          # 0 when checking
        elif action == RAISE:
            contrib[me] += deficit + RAISE_SIZE[self.street]
            bets += 1
        else:
            raise ValueError(f"illegal action {action}")

        return LeducState(priv=self.priv, board=self.board, street=self.street,
                          contrib=contrib, bets=bets, to_move=opp,
                          street_hist=self.street_hist + (action,),
                          folder=folder,
                          history=self.history + ACTION_SYMBOL[action])

    def legal_actions(self) -> List[int]:
        facing_bet = self.contrib[self.to_move] != self.contrib[1 - self.to_move]
        if facing_bet:
            actions = [FOLD, CALL]
            if self.bets < MAX_BETS_PER_ROUND:
                actions.append(RAISE)
        else:
            actions = [CALL]                # check
            if self.bets < MAX_BETS_PER_ROUND:
                actions.append(RAISE)       # bet
        return actions

    def information_set_key(self) -> str:
        me = self.to_move
        priv = RANK_NAMES[self.priv[me]]
        board = RANK_NAMES[self.board] if self.board >= 0 else "-"
        return f"{priv}|{board}|{self.history}"

    def returns(self) -> List[float]:
        if self.folder != -1:
            w = 1 - self.folder
            return self._payoff(w, self.contrib[self.folder])
        r0 = self._effective_rank(0)
        r1 = self._effective_rank(1)
        if r0 == r1:
            return [0.0, 0.0]
        w = 0 if r0 > r1 else 1
        return self._payoff(w, self.contrib[1 - w])

    def _effective_rank(self, player: int) -> int:
        priv = self.priv[player]
        if priv == self.board:
            return 100 + priv     # a pair dominates any single high card
        return priv

    @staticmethod
    def _payoff(winner: int, amount: int) -> List[float]:
        return [float(amount), -float(amount)] if winner == 0 \
            else [-float(amount), float(amount)]

    def signature(self):
        # `history` is essential: two betting lines (e.g. "rc" and "crc") can
        # reach an identical pot/position yet are different information sets,
        # so they must not share a memoization key.
        return (self.priv, self.board, self.history, tuple(self.contrib),
                self.to_move, self.folder)

    def action_label(self, action: int) -> str:
        return ACTION_SYMBOL.get(action, str(action))


class LeducPoker(Game):
    num_players = 2

    def new_initial_state(self) -> LeducState:
        return LeducState()

    def num_distinct_actions(self) -> int:
        return 3

    @property
    def name(self) -> str:
        return "LeducPoker"

    def action_label(self, action: int) -> str:
        return ACTION_SYMBOL.get(action, str(action))
