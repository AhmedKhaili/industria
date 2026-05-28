"""Tests métriques portrait."""

from __future__ import annotations

import numpy as np

from systems.stats.portrait_metrics import (
    compute_adjusted_cpk,
    enrich_descriptive_stats,
)


def test_enrich_descriptive_has_ic_and_outliers() -> None:
    s = np.linspace(0.05, 0.2, 50)
    ex = enrich_descriptive_stats(s, lti=0.0, lts=0.2)
    assert ex["ic95_label"]
    assert ex["nb_outliers"] >= 0
    assert ex["p5"] is not None


def test_adjusted_cpk_log_normale() -> None:
    # params from a typical lognorm fit shape, loc, scale
    params = {"p0": 0.5, "p1": 0.0, "p2": 0.05}
    cpk, label = compute_adjusted_cpk(0.0, 0.2, "log_normale", params)
    assert cpk is not None
    assert "log-normale" in label.lower() or "log" in label.lower()
