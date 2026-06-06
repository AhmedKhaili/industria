"""
Tests P7-F2 high-cardinality — projection présentation S7.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7.f2_compact_blocks import build_f2_compact_document
from systems.s7.f2_compact_selection import build_f2_compact_selection
from systems.s7.f2_compact_blocks import _build_group_comparison_table
from systems.s7.f2_compact_display import format_effectif_display
from systems.s7.f2_high_cardinality import (
    apply_high_cardinality_projection,
    build_high_cardinality_projection,
    chart_group_values,
    resolve_high_cardinality_config,
)

GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)


def _make_rows(n_groups: int) -> list[dict]:
    rows: list[dict] = []
    for i in range(1, n_groups + 1):
        rank = i
        # Rang 1 = pire ; rang N = meilleur (référence favorable)
        pct = max(0.0, 10.0 - (i - 1) * 0.25)
        cpk = round(0.4 + (i - 1) * 0.03, 3)
        rows.append(
            {
                "group_value": f"G{i:02d}",
                "n": 10 + i,
                "mean": round(1.0 + i * 0.01, 4),
                "out_of_tolerance_rate": pct,
                "cpk": cpk,
                "rank": rank,
                "severity_label": "critique" if i == 1 else "surveillance",
                "warnings": [],
            }
        )
    return rows


def _block(rows: list[dict]) -> dict:
    return {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "worse_direction": "upper",
        "rows": rows,
        "interpretation_limits": "Association statistique — pas causalité directe.",
        "aggregation": {"applied": False},
    }


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


def _selection_from_rows(rows: list[dict], ctx: ClientContext, cfg: dict):
    return build_f2_compact_selection(
        {"group_descriptive": [_block(rows)]},
        {"variables": ["VARIABLE_QUANTI_TEST"], "group_by": "FACTEUR_QUALI_TEST"},
        context=ctx,
        cfg=cfg,
    )


class TestHighCardinalityProjection:
    def test_inactive_when_two_groups(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        selection = _selection_from_rows(_make_rows(2), ctx, cfg)
        proj = apply_high_cardinality_projection(selection, cfg)
        assert proj.high_cardinality_active is False
        assert len(selection.rows_for_display) == 2
        assert selection.rows_for_display == selection.rows_reliable

    def test_inactive_when_one_group(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        rows = [
            {
                "group_value": "SOLO",
                "n": 20,
                "out_of_tolerance_rate": 1.0,
                "cpk": 0.9,
                "rank": 1,
                "warnings": [],
            }
        ]
        selection = _selection_from_rows(rows, ctx, cfg)
        proj = apply_high_cardinality_projection(selection, cfg)
        assert proj.high_cardinality_active is False

    def test_active_with_41_groups(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        rows = _make_rows(41)
        selection = _selection_from_rows(rows, ctx, cfg)
        proj = apply_high_cardinality_projection(selection, cfg)

        assert proj.high_cardinality_active is True
        assert len(selection.rows_for_display) <= 7
        assert len(proj.top_risk_rows) == 5

        top_values = {str(r["group_value"]) for r in proj.top_risk_rows}
        assert top_values == {"G01", "G02", "G03", "G04", "G05"}

        display_values = [str(r["group_value"]) for r in selection.rows_for_display]
        assert "G01" in display_values
        assert proj.remainder_row is not None
        assert display_values[-1] == "Autres modalités"

        fav = proj.favorable_reference_row
        assert fav is not None
        assert str(fav["group_value"]) == "G41"
        assert "G41" in display_values

        meta = selection.selection_meta.get("high_cardinality") or {}
        assert meta.get("total_reliable_groups") == 41
        assert len(meta.get("all_reliable_group_values") or []) == 41

    def test_metadata_preserves_all_reliable_groups(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        selection = _selection_from_rows(_make_rows(41), ctx, cfg)
        apply_high_cardinality_projection(selection, cfg)
        all_values = set(
            selection.selection_meta["high_cardinality"]["all_reliable_group_values"]
        )
        assert len(all_values) == 41
        assert all_values == {f"G{i:02d}" for i in range(1, 42)}

    def test_config_threshold_and_top_k(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        cfg["f2_compact"] = {
            "high_cardinality_threshold": 3,
            "max_groups_displayed": 2,
            "aggregate_remainder": True,
        }
        rows = _make_rows(5)
        selection = _selection_from_rows(rows, ctx, cfg)
        proj = apply_high_cardinality_projection(selection, cfg)

        assert proj.high_cardinality_active is True
        assert len(proj.top_risk_rows) == 2
        assert proj.top_risk_rows[0]["group_value"] == "G01"
        assert proj.remainder_row is not None

    def test_aggregate_remainder_disabled(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        cfg["f2_compact"] = {
            "high_cardinality_threshold": 3,
            "max_groups_displayed": 2,
            "aggregate_remainder": False,
        }
        selection = _selection_from_rows(_make_rows(5), ctx, cfg)
        proj = apply_high_cardinality_projection(selection, cfg)
        assert proj.remainder_row is None
        assert "Autres modalités" not in [
            str(r["group_value"]) for r in selection.rows_for_display
        ]

    def test_chart_groups_exclude_remainder_aggregate(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        selection = _selection_from_rows(_make_rows(41), ctx, cfg)
        apply_high_cardinality_projection(selection, cfg)
        chart_vals = chart_group_values(selection)
        assert "Autres modalités" not in chart_vals
        assert len(chart_vals) <= 6
        assert "G01" in chart_vals

    def test_resolve_defaults_without_yaml(self) -> None:
        cfg = resolve_high_cardinality_config({})
        assert cfg["high_cardinality_threshold"] == 8
        assert cfg["max_groups_displayed"] == 5
        assert cfg["display_strategy"] == "top_risk_plus_best"


class TestHighCardinalityDocumentIntegration:
    def test_document_table_uses_projection(self, ctx: ClientContext) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        cfg["f2_compact_enabled"] = True
        rows = _make_rows(41)
        doc = build_f2_compact_document(
            {"group_descriptive": [_block(rows)]},
            {
                "intention": "comparaison_groupes",
                "variables": ["VARIABLE_QUANTI_TEST"],
                "group_by": "FACTEUR_QUALI_TEST",
            },
            context=ctx,
            cfg=cfg,
        )
        assert doc.meta["f2_compact_selection"]["high_cardinality_active"] is True
        table = doc.find("group_comparison_table")
        assert table is not None
        assert len(table.data["rows"]) <= 7
        group_values = [r["group_value"] for r in table.data["rows"]]
        assert "G01" in group_values
        assert "Autres modalités" in group_values

        limits = doc.find("interpretation_limits")
        assert limits is not None
        joined = " ".join(limits.data.get("paragraphs") or [])
        assert "Analyse exploratoire" in joined
        assert "causalité" in joined.lower()

    def test_standard_compact_unchanged_with_few_groups(
        self, ctx: ClientContext
    ) -> None:
        cfg = prep.rapport_pdf_config(ctx)
        cfg["f2_compact_enabled"] = True
        rows = _make_rows(2)
        doc = build_f2_compact_document(
            {"group_descriptive": [_block(rows)]},
            {
                "intention": "comparaison_groupes",
                "variables": ["VARIABLE_QUANTI_TEST"],
                "group_by": "FACTEUR_QUALI_TEST",
            },
            context=ctx,
            cfg=cfg,
        )
        assert doc.meta["f2_compact_selection"].get("high_cardinality_active") is False
        table = doc.find("group_comparison_table")
        assert table is not None
        assert len(table.data["rows"]) == 2


def test_format_effectif_display_large_n() -> None:
    assert format_effectif_display(37301) == "37\u202f301"
    assert format_effectif_display(655) == "655"


def test_remainder_row_n_not_truncated_in_comparison_table() -> None:
    remainder = {
        "group_value": "Autres modalités",
        "n": 37301,
        "mean": 41.68,
        "std": 0.107,
        "out_of_tolerance_rate": 0.0,
        "cpk": 0.594,
        "rank": None,
        "severity_label": "surveillance",
        "is_remainder_aggregate": True,
    }
    table = _build_group_comparison_table(
        [remainder],
        "upper",
        "facteur test",
        verdict_key="NO_GO",
    )
    row = table["rows"][0]
    assert row["n"] == 37301
    assert row["n_display"] == "37\u202f301"
    assert "3730" != row["n_display"]


def test_build_projection_pure_function_ranking_preserved() -> None:
    rows = _make_rows(10)
    proj = build_high_cardinality_projection(
        rows,
        compact_cfg={"high_cardinality_threshold": 3, "max_groups_displayed": 3},
        best_reliable=rows[-1],
        favorable_strength="robust",
    )
    assert proj.high_cardinality_active is True
    assert [r["rank"] for r in proj.top_risk_rows] == [1, 2, 3]
