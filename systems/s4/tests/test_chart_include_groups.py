"""
Tests S4 — filtre optionnel chart_include_group_values sur boxplot (non-régression).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s4 import chart_builder

REPO = Path(__file__).resolve().parents[3]
YAML_PATH = str(REPO / "configs/lisi_aerospace/client_config.yaml")


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


@pytest.fixture
def boxplot_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Ref_Matrice": ["GROUPE_A"] * 5 + ["GROUPE_B"] * 5 + ["GROUPE_C"] * 5,
            "CR70_INTRADOS_FORME": [0.05, 0.12, 0.18, 0.08, 0.25] * 3,
        }
    )


def test_boxplot_without_include_keeps_all_groups(
    ctx: ClientContext, boxplot_df: pd.DataFrame
) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
    }
    out = chart_builder.build_boxplot_chart(
        boxplot_df, "CR70_INTRADOS_FORME", ctx, intent
    )
    assert out.get("error") is None
    assert out.get("png_bytes")
    assert out.get("groups_plotted") == ["GROUPE_A", "GROUPE_B", "GROUPE_C"]
    assert out.get("filter_warning") is None


def test_boxplot_with_include_filters_groups(
    ctx: ClientContext, boxplot_df: pd.DataFrame
) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "chart_include_group_values": ["GROUPE_A", "GROUPE_C"],
    }
    out = chart_builder.build_boxplot_chart(
        boxplot_df, "CR70_INTRADOS_FORME", ctx, intent
    )
    assert out.get("error") is None
    assert out.get("groups_plotted") == ["GROUPE_A", "GROUPE_C"]
    assert "GROUPE_B" not in (out.get("groups_plotted") or [])


def test_boxplot_empty_include_list_fallback_with_warning(
    ctx: ClientContext, boxplot_df: pd.DataFrame
) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "chart_include_group_values": [],
    }
    out = chart_builder.build_boxplot_chart(
        boxplot_df, "CR70_INTRADOS_FORME", ctx, intent
    )
    assert out.get("error") is None
    assert out.get("groups_plotted") == ["GROUPE_A", "GROUPE_B", "GROUPE_C"]
    assert out.get("filter_warning") == "chart_include_group_values_empty"


def test_boxplot_invalid_include_type_ignored(
    ctx: ClientContext, boxplot_df: pd.DataFrame
) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "chart_include_group_values": "GROUPE_A",
    }
    out = chart_builder.build_boxplot_chart(
        boxplot_df, "CR70_INTRADOS_FORME", ctx, intent
    )
    assert out.get("error") is None
    assert out.get("groups_plotted") == ["GROUPE_A", "GROUPE_B", "GROUPE_C"]


def test_boxplot_include_no_match_returns_error(
    ctx: ClientContext, boxplot_df: pd.DataFrame
) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "chart_include_group_values": ["INEXISTANT"],
    }
    out = chart_builder.build_boxplot_chart(
        boxplot_df, "CR70_INTRADOS_FORME", ctx, intent
    )
    assert out.get("png_bytes") is None
    assert out.get("error")
    assert "filtrage" in str(out.get("error", "")).lower()


def test_boxplot_chart_group_label_overrides_axis_title(
    ctx: ClientContext, boxplot_df: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def _spy_to_png(fig, width, height, **_kw):
        captured["title"] = fig.layout.title.text
        captured["xaxis_title"] = fig.layout.xaxis.title.text
        return b"png"

    monkeypatch.setattr(chart_builder.report_charts, "_fig_to_png", _spy_to_png)
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "chart_group_label": "matrice de formage",
    }
    out = chart_builder.build_boxplot_chart(
        boxplot_df, "CR70_INTRADOS_FORME", ctx, intent
    )
    assert out.get("error") is None
    assert "matrice de formage" in captured["title"]
    assert "Ref_Matrice" not in captured["title"]
    assert captured["xaxis_title"] == "matrice de formage"
