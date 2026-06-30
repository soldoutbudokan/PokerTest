"""Heads-up No-Limit Texas Hold'em.

A correct two-player NLHE engine (real 52-card deck, real 7-card showdowns)
with a configurable *action abstraction* (a small menu of bet sizes expressed
as pot fractions, plus all-in).  Card information is abstracted only for the
purpose of information-set keys, via a pluggable :class:`Abstraction`; the
actual cards are always tracked so showdowns are exact.

Conventions (standard heads-up):

* Player 0 is the button / small blind; player 1 is the big blind.
* Pre-flop the button acts first; post-flop the big blind acts first.
* Equal starting stacks, so every all-in is fully matchable (no side pots).

The whole deal (both hole cards + the five board cards) is sampled up front, so
the per-deal tree contains only betting decisions.  This makes one deal's tree
small and deterministic, which is exactly what chance-sampling MCCFR wants.
"""
from __future__ import annotations

import random
from typing import List, Optional, Sequence, Tuple

from .base import CHANCE_PLAYER, Game, GameState

# Action ids (fixed menu; legality is checked per state).
FOLD = 0
CALL = 1          # check when nothing owed, call otherwise
ALL_IN = 2
RAISE_BASE = 3    # RAISE_BASE + i  -> raise by bet_sizes[i] * pot

PREFLOP, FLOP, TURN, RIVER = 0, 1, 2, 3
BOARD_COUNT = {PREFLOP: 0, FLOP: 3, TURN: 4, RIVER: 5}


class NLHEConfig:
    def __init__(self, stack: float = 100.0, small_blind: float = 0.5,
                 big_blind: float = 1.0, bet_sizes: Sequence[float] = (1.0,),
                 max_raises_per_street: int = 4, push_fold: bool = False):
        self.stack = float(stack)
        self.sb = float(small_blind)
        self.bb = float(big_blind)
        self.bet_sizes = tuple(bet_sizes)   # pot fractions for raises
        self.max_raises_per_street = max_raises_per_street
        # In push/fold the small blind may only jam or fold pre-flop (used to
        # validate against the known Nash push/fold equilibrium).
        self.push_fold = push_fold

    def num_actions(self) -> int:
        return RAISE_BASE + len(self.bet_sizes)


class NLHEState(GameState):
    __slots__ = ("game", "hole", "board", "street", "contrib", "stack",
                 "to_act", "owe", "last_raise", "street_raises", "acted",
                 "folder", "allin", "hist", "_street_hist")

    def __init__(self, game: "NLHEGame", hole, board):
        cfg = game.config
        self.game = game
        self.hole = hole            # ((c,c),(c,c))
        self.board = board          # 5 cards, revealed per street
        self.street = PREFLOP
        # Post blinds.
        self.contrib = [cfg.sb, cfg.bb]
        self.stack = [cfg.stack - cfg.sb, cfg.stack - cfg.bb]
        self.to_act = 0             # button acts first pre-flop
        self.owe = cfg.bb - cfg.sb  # SB owes the difference
        self.last_raise = cfg.bb    # min legal raise increment
        self.street_raises = 0
        self.acted = [False, False]
        self.folder = -1
        self.allin = [False, False]
        self.hist = ""
        self._street_hist = ""

    # --- node type (no chance nodes: cards are pre-dealt) ---
    def is_chance(self) -> bool:
        return False

    def is_terminal(self) -> bool:
        return self.folder != -1 or self.street == -1

    def current_player(self) -> int:
        return self.to_act

    # --- helpers ---
    def _pot(self) -> float:
        return self.contrib[0] + self.contrib[1]

    def legal_actions(self) -> List[int]:
        cfg = self.game.config
        me = self.to_act
        owe = self.owe
        if cfg.push_fold and self.street == PREFLOP and me == 0 \
                and self.street_raises == 0:
            return [FOLD, ALL_IN]            # SB opening: jam or fold only
        actions: List[int] = []
        if owe > 0:
            actions.append(FOLD)
        actions.append(CALL)                 # check or call (call all-in if short)
        # Raises require chips beyond the call and an open raise count.
        can_raise = (self.stack[me] > owe and not self.allin[1 - me]
                     and self.street_raises < cfg.max_raises_per_street)
        if can_raise:
            pot_after_call = self._pot() + owe
            for i, f in enumerate(cfg.bet_sizes):
                inc = f * pot_after_call            # raise increment over the call
                total = owe + inc                   # chips put in this action
                if inc >= self.last_raise and total < self.stack[me]:
                    actions.append(RAISE_BASE + i)
            actions.append(ALL_IN)
        return actions

    def apply_action(self, action: int) -> "NLHEState":
        nxt = self._copy()
        cfg = self.game.config
        me = self.to_act
        opp = 1 - me

        if action == FOLD:
            nxt.folder = me
            nxt.hist += "f"
            return nxt

        if action == CALL:
            pay = min(self.owe, self.stack[me])
            nxt.contrib[me] += pay
            nxt.stack[me] -= pay
            if nxt.stack[me] == 0:
                nxt.allin[me] = True
            nxt.acted[me] = True
            nxt.owe = 0
            nxt.hist += "c"
            nxt._street_hist += "c"
            return nxt._advance_after(me, opp, closed=True)

        # Raise / all-in.
        if action == ALL_IN:
            put = self.stack[me]
        else:
            i = action - RAISE_BASE
            pot_after_call = self._pot() + self.owe
            inc = cfg.bet_sizes[i] * pot_after_call
            put = self.owe + inc
            put = min(put, self.stack[me])
        raise_increment = put - self.owe
        nxt.contrib[me] += put
        nxt.stack[me] -= put
        if nxt.stack[me] == 0:
            nxt.allin[me] = True
        nxt.last_raise = max(raise_increment, self.last_raise)
        nxt.owe = nxt.contrib[me] - nxt.contrib[opp]
        nxt.acted[me] = True
        nxt.acted[opp] = False           # reopen action for opponent
        nxt.street_raises += 1
        sym = "a" if action == ALL_IN else "r"
        nxt.hist += sym
        nxt._street_hist += sym
        return nxt._advance_after(me, opp, closed=False)

    def _advance_after(self, me: int, opp: int, closed: bool) -> "NLHEState":
        """Decide whether the street/hand continues, and to whom."""
        both_acted = self.acted[0] and self.acted[1]
        equal = abs(self.contrib[0] - self.contrib[1]) < 1e-9
        if closed and ((equal and both_acted) or self.allin[me] or self.allin[opp]):
            return self._close_street()
        # Raise (action reopens), a limp, or a pending big-blind option: the
        # opponent acts next.
        self.to_act = opp
        self.owe = max(0.0, self.contrib[me] - self.contrib[opp])
        return self

    def _close_street(self) -> "NLHEState":
        # If anyone is all-in (and matched), deal the rest and go to showdown.
        if self.allin[0] or self.allin[1]:
            self.street = RIVER
            return self._go_showdown()
        if self.street == RIVER:
            return self._go_showdown()
        # Advance to next street; big blind (player 1) acts first post-flop.
        self.street += 1
        self.owe = 0.0
        self.last_raise = self.game.config.bb
        self.street_raises = 0
        self.acted = [False, False]
        self.to_act = 1
        self._street_hist = ""
        self.hist += "/"
        return self

    def _go_showdown(self) -> "NLHEState":
        self.street = -1            # marks terminal showdown
        return self

    def chance_outcomes(self):
        raise RuntimeError("NLHE has no in-tree chance nodes")

    def information_set_key(self) -> str:
        me = self.to_act
        bucket = self.game.abstraction.bucket(self.hole[me], self.board, self._eff_street())
        return f"{bucket}|{self.hist}"

    def _eff_street(self) -> int:
        return self.street if self.street >= 0 else RIVER

    def returns(self) -> List[float]:
        cfg = self.game.config
        if self.folder != -1:
            w = 1 - self.folder
            amount = self.contrib[self.folder]
            return [amount, -amount] if w == 0 else [-amount, amount]
        # Showdown: compare full 7-card hands.
        from ..evaluator import evaluate
        s0 = evaluate(list(self.hole[0]) + list(self.board))
        s1 = evaluate(list(self.hole[1]) + list(self.board))
        # With equal stacks contributions are matched; payoff = opponent's stake.
        stake = min(self.contrib[0], self.contrib[1])
        if s0 > s1:
            return [stake, -stake]
        if s1 > s0:
            return [-stake, stake]
        return [0.0, 0.0]

    def _copy(self) -> "NLHEState":
        c = NLHEState.__new__(NLHEState)
        c.game = self.game
        c.hole = self.hole
        c.board = self.board
        c.street = self.street
        c.contrib = [self.contrib[0], self.contrib[1]]
        c.stack = [self.stack[0], self.stack[1]]
        c.to_act = self.to_act
        c.owe = self.owe
        c.last_raise = self.last_raise
        c.street_raises = self.street_raises
        c.acted = [self.acted[0], self.acted[1]]
        c.folder = self.folder
        c.allin = [self.allin[0], self.allin[1]]
        c.hist = self.hist
        c._street_hist = self._street_hist
        return c

    def action_label(self, action: int) -> str:
        if action == FOLD:
            return "fold"
        if action == CALL:
            return "call"
        if action == ALL_IN:
            return "allin"
        return f"raise{self.game.config.bet_sizes[action - RAISE_BASE]:g}pot"


class NLHEGame(Game):
    num_players = 2

    def __init__(self, config: Optional[NLHEConfig] = None, abstraction=None):
        self.config = config or NLHEConfig()
        if abstraction is None:
            from .nlhe_abstraction import NullAbstraction
            abstraction = NullAbstraction()
        self.abstraction = abstraction

    def deal(self, rng: random.Random) -> Tuple:
        deck = list(range(52))
        rng.shuffle(deck)
        hole = ((deck[0], deck[1]), (deck[2], deck[3]))
        board = tuple(deck[4:9])
        return hole, board

    def new_initial_state(self, deal=None, rng: Optional[random.Random] = None):
        if deal is None:
            deal = self.deal(rng or random.Random())
        hole, board = deal
        return NLHEState(self, hole, board)

    def num_distinct_actions(self) -> int:
        return self.config.num_actions()

    @property
    def name(self) -> str:
        return "HeadsUpNLHE"

    def action_label(self, action: int) -> str:
        if action == FOLD:
            return "fold"
        if action == CALL:
            return "call"
        if action == ALL_IN:
            return "allin"
        return f"raise{self.config.bet_sizes[action - RAISE_BASE]:g}pot"
