"""
Tests unitaires — lignes LTI/LTS sur graphiques S4 (sans pipeline LISI complet).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest

from systems.s1.client_context import ClientContext
from systems.s4 import chart_builder

REPO = Path(__file__).resolve().parents[3]
YAML_PATH = str(REPO / "configs/lisi_aerospace/client_config.yaml")


@pytest.fixture(scope="module")
def lisi_ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def test_add_tolerance_lines_hline() -> None:
    fig = go.Figure()
    chart_builder._add_tolerance_lines(
        fig, {"lti": 0.0, "lts": 0.2, "nominal": 0.1}, axis="y"
    )
    assert len(fig.layout.shapes) >= 2


def test_boxplot_includes_tolerance_shapes(lisi_ctx: ClientContext) -> None:
    df = pd.DataFrame(
        {
            "CR70_INTRADOS_FORME": [0.05, 0.12, 0.18, 0.08, 0.25, 0.15],
            "Ref_Matrice": ["M1", "M1", "M2", "M2", "M3", "M3"],
        }
    )
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
    }
    out = chart_builder.build_boxplot_chart(
        df, "CR70_INTRADOS_FORME", lisi_ctx, intent
    )
    assert out.get("error") is None
    assert out.get("png_bytes")
    assert len(out["png_bytes"]) > 500
    assert "LTI" in out.get("description", "")
