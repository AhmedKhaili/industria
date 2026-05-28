"""
Tests S3 — Dunn post-hoc (point A).
"""

from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("scikit_posthocs")

from specialists.dunn_posthoc import DunnPosthocSpecialist


def test_dunn_detects_different_pair() -> None:
    df = pd.DataFrame(
        {
            "y": [1.0, 1.1, 1.2, 1.0, 5.0, 5.1, 5.2, 5.0],
            "g": ["A", "A", "A", "A", "B", "B", "B", "B"],
        }
    )
    spec = DunnPosthocSpecialist()
    out = spec.run(
        df,
        {"target_column": "y", "group_column": "g"},
        {"group_column": "g", "alpha": 0.05},
    )
    assert out.get("status") == "success"
    paires = out["result"].get("paires_significatives", [])
    assert paires
    assert any(
        {"A", "B"} == {p["groupe_a"], p["groupe_b"]} for p in paires
    )
