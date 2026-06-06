"""
Tests P7-F2 compact — filtrage graphique groupes fiables (D3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s7.f2_compact_charts import build_compact_chart_items
from systems.s7.f2_compact_selection import build_f2_compact_selection

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "group_descriptive_f2_compact_filter.json"
)
GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_chart_include_groups_filters_boxplot_data(ctx: ClientContext) -> None:
    df = pd.DataFrame(
        {
            "FACTEUR_QUALI_TEST": ["GROUPE_A"] * 5 + ["OPERATEUR_X"] * 5,
            "VARIABLE_QUANTI_TEST": list(range(10)),
        }
    )
    intent = {
        "variables": ["VARIABLE_QUANTI_TEST"],
        "group_by": "FACTEUR_QUALI_TEST",
        "chart_include_group_values": ["GROUPE_A"],
    }
    from systems.s4.chart_builder import build_boxplot_chart

    out = build_boxplot_chart(df, "VARIABLE_QUANTI_TEST", ctx, intent)
    assert out.get("png_bytes")
    assert out.get("error") is None


def test_compact_chart_items_metadata_excludes_parasites(
    fixture_payload: dict, ctx: ClientContext
) -> None:
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    selection = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
    )
    items = build_compact_chart_items(
        [{"id": "b1", "title": "boxplot test", "png_bytes": b"x"}],
        selection,
        fixture_payload["intent"],
        ctx,
        df_propre=None,
    )
    assert items[0]["included_groups"] == ["GROUPE_A", "GROUPE_B", "GROUPE_C"]
    assert "OPERATEUR_X" in items[0]["excluded_from_chart"]
    assert "HORS_PATTERN_X" in items[0]["excluded_from_chart"]


def test_compact_chart_regenerates_with_df(
    fixture_payload: dict, ctx: ClientContext
) -> None:
    df = pd.DataFrame(
        {
            "FACTEUR_QUALI_TEST": ["GROUPE_A"] * 8
            + ["GROUPE_B"] * 6
            + ["GROUPE_C"] * 4
            + ["OPERATEUR_X"] * 20,
            "VARIABLE_QUANTI_TEST": [0.1] * 38,
        }
    )
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    selection = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
    )
    items = build_compact_chart_items(
        [{"id": "b1", "title": "boxplot VARIABLE", "png_bytes": None}],
        selection,
        fixture_payload["intent"],
        ctx,
        df_propre=df,
    )
    assert items[0].get("filtered_from_s4") is True
    assert items[0].get("png_bytes")
    assert "OPERATEUR_X" not in items[0]["included_groups"]


def test_compact_chart_passes_factor_label_to_s4(
    fixture_payload: dict, ctx: ClientContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    df = pd.DataFrame(
        {
            "FACTEUR_QUALI_TEST": ["GROUPE_A"] * 8 + ["GROUPE_B"] * 6,
            "VARIABLE_QUANTI_TEST": [0.1] * 14,
        }
    )
    captured: dict = {}

    def _fake_build_boxplot(_df, _var, _ctx, intent, **_kw):
        captured["intent"] = dict(intent)
        return {"png_bytes": b"png", "error": None}

    monkeypatch.setattr(
        "systems.s4.chart_builder.build_boxplot_chart", _fake_build_boxplot
    )
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    selection = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
    )
    label = "numéro de passage de la pastille extérieure"
    build_compact_chart_items(
        [{"id": "b1", "title": "boxplot test", "png_bytes": None}],
        selection,
        fixture_payload["intent"],
        ctx,
        df_propre=df,
        factor_label=label,
    )
    assert captured["intent"]["chart_group_label"] == label
    assert "PAS_E_Numero_Passage" not in captured["intent"].get("chart_group_label", "")
