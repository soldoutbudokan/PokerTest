"""Smoke tests for the metrics + visualization pipeline (no heavy training)."""
import csv
import os

from pokerbot.games.nlhe_abstraction import preflop_index
from pokerbot.metrics import (HISTORY_COLUMNS, _hand_name, _log_milestones,
                              append_history, flatten)


def test_hand_names_cover_169_and_match_index():
    names = {_hand_name(i) for i in range(169)}
    assert len(names) == 169
    # Spot-check the naming convention against a couple of known hands.
    assert _hand_name(preflop_index((48, 49))) == "AA"          # As Ah
    # AKs and AKo must both exist and be distinct.
    assert "AKs" in names and "AKo" in names


def test_grid_matrix_is_fully_covered():
    from pokerbot.visualize import _grid_matrix
    import numpy as np
    value_by_hand = {_hand_name(i): i / 168.0 for i in range(169)}
    m = _grid_matrix(value_by_hand)
    assert m.shape == (13, 13)
    assert not np.isnan(m).any()        # every cell maps to a real hand


def test_log_milestones_monotone_and_capped():
    ms = _log_milestones(3000)
    assert ms == sorted(set(ms))
    assert ms[0] == 1 and ms[-1] == 3000
    assert all(m <= 3000 for m in ms)


def test_flatten_and_append_history(tmp_path):
    fake = {
        "level": "quick",
        "kuhn": {"exploitability": 0.002, "game_value": -0.055},
        "leduc": {"exploitability": 0.01},
        "nlhe": {
            "exploitability_bb100": 3.4, "infosets": 1234,
            "pushfold": {"jam_pct": 62.0},
            "baselines": {
                "random": {"bb100": 70.0}, "call-station": {"bb100": 88.0},
                "maniac": {"bb100": 64.0}, "tight-aggressive": {"bb100": -5.0},
            },
        },
    }
    summary = flatten(fake)
    assert summary["nlhe_exploitability_bb100"] == 3.4
    path = tmp_path / "hist.csv"
    append_history(summary, "2026-06-30", str(path))
    append_history(summary, "2026-07-01", str(path))
    rows = list(csv.DictReader(open(path)))
    assert len(rows) == 2
    assert set(rows[0].keys()) == set(HISTORY_COLUMNS)
    assert rows[0]["date"] == "2026-06-30"


def test_generate_figures_smoke(tmp_path):
    """generate() must write all figures from a minimal metrics dict."""
    from pokerbot.visualize import generate
    metrics = {
        "level": "quick",
        "evaluator": {"counts": {"High Card": 1302540, "Pair": 1098240},
                      "ok": True},
        "kuhn": {"curve": [[1, 0.3, -0.05], [100, 0.01, -0.055]],
                 "exploitability": 0.01, "game_value": -0.055},
        "leduc": {"curve": [[1, 0.9], [100, 0.06]], "exploitability": 0.06},
        "nlhe": {
            "baselines": {
                "random": {"bb100": 70.0, "ci95": 10.0, "significant": True},
                "tight-aggressive": {"bb100": -5.0, "ci95": 8.0,
                                     "significant": False},
            },
            "exploit_curve": [[10000, -10.0], [50000, 2.0]],
            "pushfold": {"jam": {_hand_name(i): (i % 10) / 10.0
                                 for i in range(169)}, "jam_pct": 62.0},
            "preflop": {_hand_name(i): {"allin": 0.2, "raise1pot": 0.1,
                                        "fold": 0.4, "call": 0.3}
                        for i in range(169)},
        },
    }
    outdir = tmp_path / "figs"
    written = generate(metrics, str(outdir), str(tmp_path / "none.csv"))
    assert len(written) == 8
    for p in written:
        assert os.path.exists(p) and os.path.getsize(p) > 0
