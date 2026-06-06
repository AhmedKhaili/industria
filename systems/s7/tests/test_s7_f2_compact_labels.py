"""
Tests P7-F2 compact — libellés métier pastille et grammaire des titres.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7.f2_compact_blocks import build_f2_compact_document
from systems.s7.f2_compact_display import compact_report_title
from systems.s7.f2_compact_labels import resolve_factor_label
from systems.s7.f2_compact_selection import build_f2_compact_selection
from systems.s7.f2_compact_templates import business_reading_sections_compact

TRACEABILITY_YAML = str(
    Path(__file__).resolve().parents[3]
    / "configs/lisi_aerospace/client_config_traceability.yaml"
)
FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "group_descriptive_f2_compact_filter.json"
)


@pytest.fixture(scope="module")
def trace_ctx() -> ClientContext:
    return ClientContext.load(TRACEABILITY_YAML)


def _block_text(data: dict) -> str:
    parts: list[str] = []
    for key in ("title", "lines", "paragraphs", "sections", "label", "banner"):
        val = data.get(key)
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(_block_text(item))
    rows = data.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                parts.extend(str(v) for v in row.values() if v is not None)
    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                parts.append(str(item.get("title") or ""))
    return "\n".join(parts)


def _document_text(doc) -> str:
    chunks: list[str] = []
    if doc.meta.get("report_title"):
        chunks.append(str(doc.meta["report_title"]))
    for block in doc.blocks:
        chunks.append(_block_text(block.data))
    return "\n".join(chunks).lower()


def _passage_rows() -> list[dict]:
    return [
        {
            "group_value": "P2",
            "n": 21844,
            "mean": 41.727,
            "std": 0.107,
            "out_of_tolerance_rate": 0.71,
            "cp": 1.2,
            "cpk": 0.552,
            "rank": 1,
            "severity_label": "critique",
            "warnings": [],
        },
        {
            "group_value": "P1",
            "n": 21781,
            "mean": 41.634,
            "std": 0.107,
            "out_of_tolerance_rate": 0.0,
            "cp": 1.5,
            "cpk": 0.738,
            "rank": 2,
            "severity_label": "favorable",
            "warnings": [],
        },
    ]


class TestPastilleFactorLabels:
    def test_passage_ext_label(self, trace_ctx: ClientContext) -> None:
        intent = {"operation": "FILAGE", "piece": "RD4L1A1C"}
        label = resolve_factor_label(trace_ctx, intent, "PAS_E_Numero_Passage")
        assert label == "numéro de passage de la pastille extérieure"
        assert "pas e" not in label.lower()
        assert "pas_e" not in label.lower()

    def test_passage_int_label(self, trace_ctx: ClientContext) -> None:
        intent = {"operation": "FILAGE", "piece": "RD4L1A1C"}
        label = resolve_factor_label(trace_ctx, intent, "PAS_I_Numero_Passage")
        assert label == "numéro de passage de la pastille intérieure"

    def test_retaille_ext_label(self, trace_ctx: ClientContext) -> None:
        intent = {"operation": "FILAGE"}
        label = resolve_factor_label(trace_ctx, intent, "PAS_E_Niveau_Retaille")
        assert label == "niveau de retaille de la pastille extérieure"

    def test_retaille_int_label(self, trace_ctx: ClientContext) -> None:
        intent = {"operation": "FILAGE"}
        label = resolve_factor_label(trace_ctx, intent, "PAS_I_Niveau_Retaille")
        assert label == "niveau de retaille de la pastille intérieure"


class TestCompactTitleGrammar:
    def test_no_du_longueur(self) -> None:
        var = (
            "longueur de corde de l'aube mesurée aux sections CR1 CR2 CR3 "
            "lors du filage"
        )
        fac = "numéro de passage de la pastille extérieure"
        title = compact_report_title(var, fac)
        assert "du longueur" not in title.lower()
        assert "de la longueur" in title.lower()
        assert fac in title


class TestPassageDocumentLabels:
    def test_compact_document_uses_business_labels(self, trace_ctx: ClientContext) -> None:
        rows = _passage_rows()
        block = {
            "variable": "CR1",
            "group_by": "PAS_E_Numero_Passage",
            "level": "measure",
            "rows": rows,
            "worse_direction": "upper",
            "worst_group": "P2",
            "best_group": "P1",
        }
        intent = {
            "variables": ["CR1"],
            "group_by": "PAS_E_Numero_Passage",
            "piece": "RD4L1A1C",
            "operation": "FILAGE",
        }
        cfg = prep.rapport_pdf_config(trace_ctx)
        cfg["f2_compact_enabled"] = True
        selection = build_f2_compact_selection(
            {"group_descriptive": [block]}, intent, trace_ctx, cfg
        )
        assert selection.worst_reliable["group_value"] == "P2"
        assert selection.rows_reliable[0]["n"] == 21844

        doc = build_f2_compact_document(
            {"group_descriptive": [block]},
            intent,
            context=trace_ctx,
            cfg=cfg,
        )
        text = _document_text(doc)
        assert "pas e numero passage" not in text
        assert "pas_e_numero_passage" not in text
        assert "du longueur" not in text
        assert "numéro de passage de la pastille extérieure" in text
        table = doc.find("group_comparison_table")
        assert table is not None
        assert table.data["rows"][0]["group_value"] == "P2"
        assert table.data["rows"][0]["n"] == 21844


class TestRetailleBusinessReadingPlural:
    def test_exterior_plural_wording(self) -> None:
        factor = "niveau de retaille de la pastille extérieure"
        rows = [
            {
                "group_value": "-16",
                "rank": 1,
                "out_of_tolerance_rate": 7.0,
                "cpk": 0.5,
                "n": 100,
            },
            {
                "group_value": "-6,5",
                "rank": 2,
                "out_of_tolerance_rate": 2.0,
                "cpk": 0.8,
                "n": 50,
                "severity_label": "surveillance",
            },
            {
                "group_value": "-1",
                "rank": 6,
                "out_of_tolerance_rate": 0.0,
                "cpk": 1.5,
                "n": 300,
                "severity_label": "favorable",
            },
        ]
        sections = business_reading_sections_compact(
            rows,
            worst_row=rows[0],
            favorable_row=rows[2],
            favorable_strength="robust",
            worse_direction="upper",
            analysis_level="measure",
            factor_label=factor,
        )
        mid = next(s for s in sections if s["tier"] == "intermediaire")
        body = mid["heading"] + " " + " ".join(mid["paragraphs"])
        assert "Les niveau de retaille" not in body
        assert "pastille extérieures" not in body
        assert (
            mid["heading"]
            == "Niveaux de retaille de la pastille extérieure intermédiaires à surveiller"
        )
        assert "Les niveaux de retaille de la pastille extérieure" in body

    def test_interior_plural_wording(self) -> None:
        factor = "niveau de retaille de la pastille intérieure"
        rows = [
            {"group_value": "-5", "rank": 1, "out_of_tolerance_rate": 6.0, "cpk": 0.5, "n": 80},
            {"group_value": "-3", "rank": 2, "out_of_tolerance_rate": 1.0, "cpk": 0.9, "n": 40},
            {"group_value": "-0,5", "rank": 5, "out_of_tolerance_rate": 0.0, "cpk": 1.4, "n": 200},
        ]
        sections = business_reading_sections_compact(
            rows,
            worst_row=rows[0],
            favorable_row=rows[2],
            favorable_strength="robust",
            worse_direction="upper",
            analysis_level="measure",
            factor_label=factor,
        )
        mid = next(s for s in sections if s["tier"] == "intermediaire")
        body = mid["heading"] + " " + " ".join(mid["paragraphs"])
        assert "pastille intérieures" not in body
        assert (
            mid["heading"]
            == "Niveaux de retaille de la pastille intérieure intermédiaires à surveiller"
        )
        assert "Les niveaux de retaille de la pastille intérieure" in body
