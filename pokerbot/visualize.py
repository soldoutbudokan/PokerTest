"""Generate the visualizations that show solver progress and bot quality.

Figures (written to ``figures/`` by default):

* ``convergence.png``    – Kuhn & Leduc exploitability vs iterations (proof the
  solver reaches Nash).
* ``evaluator.png``      – the exhaustive 5-card category counts (correctness).
* ``nlhe_winrate.png``   – bot win rate vs each baseline, bb/100 with 95% CIs.
* ``exploitability.png`` – best-response win rate vs how long it trains (the
  in-abstraction exploitability lower bound).
* ``pushfold_grid.png``  – 13x13 hand grid of the 10 BB SB jam range vs Nash.
* ``preflop_grid.png``   – 13x13 grid of the bot's pre-flop aggression.
* ``progress.png``       – metrics over time from ``metrics_history.csv``.
* ``dashboard.png``      – a single combined panel for the README.

Usage::

    python -m pokerbot.visualize --level quick      # fast
    python -m pokerbot.visualize --level standard   # default

Requires matplotlib (an optional dependency; the core package does not need it).
"""
from __future__ import annotations

import argparse
import os
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .cards import RANKS  # noqa: E402
from .metrics import compute_metrics  # noqa: E402

RANK_ORDER = list(reversed(RANKS))   # A, K, Q ... 2  (grid axis order)
BLUE, GREEN, RED, GREY = "#1f77b4", "#2ca02c", "#d62728", "#888888"


def _grid_matrix(value_by_hand: Dict[str, float]) -> np.ndarray:
    """13x13 matrix (rows/cols A..2): diag=pairs, upper=suited, lower=offsuit."""
    m = np.full((13, 13), np.nan)
    for r in range(13):
        for c in range(13):
            hi_rank = RANK_ORDER[min(r, c)]
            lo_rank = RANK_ORDER[max(r, c)]
            if r == c:
                name = RANK_ORDER[r] + RANK_ORDER[r]
            elif r < c:
                name = hi_rank + lo_rank + "s"
            else:
                name = hi_rank + lo_rank + "o"
            m[r, c] = value_by_hand.get(name, np.nan)
    return m


def _draw_grid(ax, matrix: np.ndarray, title: str, cmap="viridis") -> None:
    im = ax.imshow(matrix, cmap=cmap, vmin=0.0, vmax=1.0, aspect="equal")
    ax.set_xticks(range(13))
    ax.set_yticks(range(13))
    ax.set_xticklabels(RANK_ORDER, fontsize=7)
    ax.set_yticklabels(RANK_ORDER, fontsize=7)
    ax.set_title(title, fontsize=11)
    for r in range(13):
        for c in range(13):
            v = matrix[r, c]
            if not np.isnan(v):
                ax.text(c, r, f"{v:.0%}", ha="center", va="center",
                        fontsize=5, color="white" if v < 0.6 else "black")
    return im


# --- individual figures ---------------------------------------------------

def fig_convergence(ax, metrics: Dict) -> None:
    k = np.array(metrics["kuhn"]["curve"])
    l = np.array(metrics["leduc"]["curve"])
    ax.loglog(k[:, 0], k[:, 1], "o-", color=BLUE, label="Kuhn", markersize=4)
    ax.loglog(l[:, 0], l[:, 1], "s-", color=GREEN, label="Leduc", markersize=4)
    ax.set_xlabel("CFR iterations")
    ax.set_ylabel("exploitability (→ 0 = Nash)")
    ax.set_title("Solver convergence to Nash")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()


def fig_evaluator(ax, metrics: Dict) -> None:
    ev = metrics["evaluator"]
    names = list(ev["counts"].keys())
    got = [ev["counts"][n] for n in names]
    ax.barh(range(len(names)), got, color=BLUE)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("number of 5-card hands (log)")
    ax.set_title(f"Hand evaluator: all categories exact = {ev['ok']}")
    ax.invert_yaxis()


def fig_winrate(ax, metrics: Dict) -> None:
    b = metrics["nlhe"]["baselines"]
    names = list(b.keys())
    vals = [b[n]["bb100"] for n in names]
    errs = [b[n]["ci95"] for n in names]
    colors = [GREEN if v > 0 else RED for v in vals]
    ax.barh(range(len(names)), vals, xerr=errs, color=colors,
            error_kw={"ecolor": "black", "capsize": 3})
    ax.axvline(0, color="black", lw=0.8)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("bot win rate (bb/100, 95% CI)")
    ax.set_title("Bot vs baselines (mirrored deals)")
    ax.invert_yaxis()


def fig_exploitability(ax, metrics: Dict) -> None:
    c = np.array(metrics["nlhe"]["exploit_curve"])
    ax.plot(c[:, 0], c[:, 1], "o-", color=RED)
    ax.axhline(0, color="black", lw=0.8, alpha=0.5)
    ax.set_xlabel("best-response training iterations")
    ax.set_ylabel("BR win rate vs bot (bb/100)")
    ax.set_title("In-abstraction exploitability (lower bound)")
    ax.grid(True, alpha=0.3)


def fig_pushfold(ax, metrics: Dict) -> None:
    jam = metrics["nlhe"]["pushfold"]["jam"]
    _draw_grid(ax, _grid_matrix(jam),
               f"10 BB SB jam range ({metrics['nlhe']['pushfold']['jam_pct']:.0f}% "
               f"of hands; Nash ~60-70%)", cmap="RdYlGn")


def fig_preflop(ax, metrics: Dict) -> None:
    pf = metrics["nlhe"]["preflop"]
    aggro = {h: (d.get("allin", 0.0) + sum(v for k, v in d.items()
                                           if k.startswith("raise")))
             for h, d in pf.items()}
    _draw_grid(ax, _grid_matrix(aggro),
               "Bot 20 BB SB aggression: P(raise or all-in)", cmap="magma")


def fig_progress(ax, history_path: str) -> bool:
    import csv
    if not os.path.exists(history_path):
        ax.text(0.5, 0.5, "no metrics_history.csv yet\n(populated by the daily routine)",
                ha="center", va="center", fontsize=10)
        ax.set_axis_off()
        return False
    rows = list(csv.DictReader(open(history_path)))
    if not rows:
        ax.set_axis_off()
        return False
    x = list(range(len(rows)))
    expl = [float(r["nlhe_exploitability_bb100"] or 0) for r in rows]
    tag = [float(r["win_vs_tight_aggressive"] or 0) for r in rows]
    ax.plot(x, expl, "o-", color=RED, label="exploitability (bb/100)")
    ax.plot(x, tag, "s-", color=GREEN, label="win vs TAG (bb/100)")
    ax.set_xticks(x)
    ax.set_xticklabels([r["date"] for r in rows], rotation=45, fontsize=7, ha="right")
    ax.axhline(0, color="black", lw=0.6, alpha=0.4)
    ax.set_title("Progress over time")
    ax.set_ylabel("bb/100")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    return True


# --- drivers --------------------------------------------------------------

def generate(metrics: Dict, outdir: str = "figures",
             history_path: str = "metrics_history.csv") -> List[str]:
    os.makedirs(outdir, exist_ok=True)
    written = []

    def save(name, fn, figsize=(7, 5)):
        fig, ax = plt.subplots(figsize=figsize)
        fn(ax)
        fig.tight_layout()
        p = os.path.join(outdir, name)
        fig.savefig(p, dpi=130)
        plt.close(fig)
        written.append(p)

    save("convergence.png", lambda ax: fig_convergence(ax, metrics))
    save("evaluator.png", lambda ax: fig_evaluator(ax, metrics))
    save("nlhe_winrate.png", lambda ax: fig_winrate(ax, metrics))
    save("exploitability.png", lambda ax: fig_exploitability(ax, metrics))
    save("pushfold_grid.png", lambda ax: fig_pushfold(ax, metrics), (7, 6))
    save("preflop_grid.png", lambda ax: fig_preflop(ax, metrics), (7, 6))
    save("progress.png", lambda ax: fig_progress(ax, history_path))

    # Combined dashboard.
    fig, axes = plt.subplots(2, 3, figsize=(19, 11))
    fig_convergence(axes[0, 0], metrics)
    fig_winrate(axes[0, 1], metrics)
    fig_exploitability(axes[0, 2], metrics)
    fig_pushfold(axes[1, 0], metrics)
    fig_preflop(axes[1, 1], metrics)
    fig_progress(axes[1, 2], history_path)
    fig.suptitle("PokerTest — bot quality dashboard", fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    p = os.path.join(outdir, "dashboard.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    written.append(p)
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="standard",
                    choices=["quick", "standard", "full"])
    ap.add_argument("--outdir", default="figures")
    ap.add_argument("--history", default="metrics_history.csv")
    args = ap.parse_args()
    print(f"computing metrics (level={args.level})...")
    metrics = compute_metrics(level=args.level)
    written = generate(metrics, args.outdir, args.history)
    print("wrote:")
    for p in written:
        print("  " + p)


if __name__ == "__main__":
    main()
