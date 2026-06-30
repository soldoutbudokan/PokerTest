"""pokerbot — a CFR-based poker bot with an objective, exploitability-first
evaluation.

Subpackages:

* ``games``   – Kuhn, Leduc and heads-up No-Limit Hold'em behind one interface.
* ``solve``   – CFR / CFR+ / Discounted CFR, exact best response / exploitability,
  and Monte-Carlo CFR for No-Limit Hold'em.
* ``agents``  – the trained bot plus baseline opponents.
* ``eval``    – mirrored-deal arena (mbb/100 + CIs) and exploitability estimates.

Run ``python -m pokerbot.evaluate`` to reproduce the objective evaluation.
"""

__version__ = "0.1.0"
