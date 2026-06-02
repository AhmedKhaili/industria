"""
Tests P7-F2 compact — C2 blocs JSON (sans assembler, sans PDF).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7.f2_compact_blocks import (
    F2_COMPACT_BLOCK_ORDER,
    build_f2_compact_document,
    f2_compact_document_to_dict,
)
from systems.s7.f2_compact_verdict import compute_compact_verdict
from systems.s7.f2_compact_selection import build_f2_compact_selection
from systems.s7.f2_templates import text_contains_abusive_causality

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "group_descriptive_f2_compact_filter.json"
)
GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)

_EXCLUDED_NAMES = frozenset({"GROUPE_FAIBLE", "HORS_PATTERN_X", "OPERATEUR_X"})
_SENSITIVE_BLOCKS = frozenset(
    {
        "conclusion_key",
        "verdict",
        "key_indicators",
        "business_reading",
        "final_verdict",
    }
)

_CAUSALITY_RE = re.compile(
    r"\b(cause|causent|prouve que|démontre que|demontre que)\b",
    re.I,
)


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compact_doc(fixture_payload: dict, ctx: ClientContext):
    cfg = prep.rapport_pdf_config(ctx)
    cfg["f2_compact"] = fixture_payload["filter_config"]["f2_compact"]
    return build_f2_compact_document(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
        question_originale="Comparer VARIABLE_QUANTI_TEST par FACTEUR_QUALI_TEST",
        timestamp="2026-06-02T10:00:00.000+00:00",
        specialist_results=[
            {
                "agent": "anova_kruskal",
                "status": "success",
                "result": {
                    "methode_choisie": "Kruskal-Wallis",
                    "p_value": 0.042,
                    "p_value_display": "p = 0,042",
                    "significatif": True,
                },
            }
        ],
    )


def test_block_order_matches_c2_spec(compact_doc) -> None:
    assert compact_doc.block_types() == list(F2_COMPACT_BLOCK_ORDER)


def test_render_mode_f2_compact(compact_doc) -> None:
    assert compact_doc.meta["render_mode"] == "f2_compact"


def test_synthesis_title_uses_yaml_libelle_court(compact_doc) -> None:
    syn = compact_doc.find("business_synthesis")
    assert syn is not None
    title = syn.data["title"]
    assert title == "Synthèse métier — Comparaison de Variable test selon Facteur test"
    assert "description longue" not in title.lower()
    assert "50 %" not in title
    assert "corde" not in title.lower()


def test_synthesis_framing_measure_level(
    fixture_payload: dict, ctx: ClientContext
) -> None:
    measure_block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "rows": [
            {
                "group_value": "GROUPE_A",
                "n": 10,
                "out_of_tolerance_rate": 0.4,
                "cpk": 1.47,
                "rank": 1,
                "warnings": [],
            },
        ],
        "interpretation_limits": "Association statistique — pas causalité directe.",
        "aggregation": {"applied": False},
    }
    cfg = prep.rapport_pdf_config(ctx)
    cfg["f2_compact"] = fixture_payload["filter_config"]["f2_compact"]
    doc = build_f2_compact_document(
        {"group_descriptive": [measure_block]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
    )
    syn = doc.find("business_synthesis")
    assert syn is not None
    lines = syn.data["lines"]
    assert any("mesure capteur" in line for line in lines)
    assert any("mesure individuelle" in line for line in lines)


def test_verdict_surveillance_without_critique_when_cpk_above_p1(
    ctx: ClientContext,
) -> None:
    """severity_label S3 « critique » ne doit pas contaminer le verdict compact."""
    rows = [
        {
            "group_value": "GROUPE_OK",
            "n": 20,
            "out_of_tolerance_rate": 0.4,
            "cpk": 1.47,
            "rank": 1,
            "severity_label": "critique",
            "warnings": [],
        },
    ]
    block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "rows": rows,
        "aggregation": {"applied": False},
    }
    cfg = prep.rapport_pdf_config(ctx)
    selection = build_f2_compact_selection(
        {"group_descriptive": [block]},
        {"variables": ["VARIABLE_QUANTI_TEST"], "group_by": "FACTEUR_QUALI_TEST"},
        context=ctx,
        cfg=cfg,
    )
    verdict = compute_compact_verdict(selection, ctx, cfg)
    assert verdict.verdict_key == "SURVEILLANCE"
    assert "critique" not in verdict.rationale.lower()
    assert verdict.tone == "point_attention"


def test_no_go_only_when_yaml_threshold_crossed(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    rows = [
        {
            "group_value": "GROUPE_LIMITE",
            "n": 10,
            "out_of_tolerance_rate": 0.0,
            "cpk": 1.05,
            "rank": 1,
            "severity_label": "critique",
            "warnings": [],
        },
    ]
    block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "rows": rows,
    }
    selection = build_f2_compact_selection(
        {"group_descriptive": [block]},
        {"variables": ["VARIABLE_QUANTI_TEST"], "group_by": "FACTEUR_QUALI_TEST"},
        context=ctx,
        cfg=cfg,
    )
    verdict = compute_compact_verdict(selection, ctx, cfg)
    assert verdict.verdict_key != "NO_GO"
    assert "critique" not in verdict.rationale.lower()


def test_interpretation_limits_measure_without_aggregated_phrase(
    fixture_payload: dict, ctx: ClientContext
) -> None:
    measure_block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "ranking_method": "pct_hors_tol_then_cpk_then_risk_to_limit",
        "worse_direction": "upper",
        "rows": [
            {
                "group_value": "GROUPE_A",
                "n": 10,
                "mean": 0.1,
                "out_of_tolerance_rate": 0.4,
                "cpk": 1.47,
                "rank": 1,
                "severity_label": "surveillance",
                "warnings": [],
            },
        ],
        "interpretation_limits": "Association statistique — pas causalité directe.",
        "aggregation": {"applied": False},
    }
    cfg = prep.rapport_pdf_config(ctx)
    cfg["f2_compact"] = fixture_payload["filter_config"]["f2_compact"]
    doc = build_f2_compact_document(
        {"group_descriptive": [measure_block]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
    )
    limits = doc.find("interpretation_limits")
    assert limits is not None
    text = "\n".join(limits.data.get("paragraphs") or [])
    assert "mesure capteur" in text.lower()
    assert "concernent les unités métier agrégées" not in text.lower()
    assert "l'agrégation s3 a été appliquée" not in text.lower()


def test_verdict_no_go_for_clear_critical_group(
    fixture_payload: dict, ctx: ClientContext
) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    cfg["f2_compact"] = fixture_payload["filter_config"]["f2_compact"]
    selection = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
    )
    verdict = compute_compact_verdict(selection, ctx, cfg)
    assert verdict.verdict_key == "NO_GO"
    assert selection.worst_reliable is not None
    assert selection.worst_reliable["group_value"] == "GROUPE_A"


def test_verdict_surveillance_not_no_go_for_mild_profile(ctx: ClientContext) -> None:
    """Cas type F2c raté : faible % HT et Cpk > 1,3 → pas de NO-GO."""
    mild_rows = [
        {
            "group_value": "GROUPE_OK",
            "n": 10,
            "out_of_tolerance_rate": 0.4,
            "cpk": 1.47,
            "rank": 1,
            "severity_label": "favorable",
            "warnings": [],
        },
        {
            "group_value": "GROUPE_B",
            "n": 8,
            "out_of_tolerance_rate": 0.0,
            "cpk": 1.6,
            "rank": 2,
            "severity_label": "favorable",
            "warnings": [],
        },
    ]
    block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "aggregated_unit",
        "rows": mild_rows,
        "aggregation": {"applied": True, "min_units_per_group": 3},
    }
    cfg = prep.rapport_pdf_config(ctx)
    selection = build_f2_compact_selection(
        {"group_descriptive": [block]},
        {"variables": ["VARIABLE_QUANTI_TEST"], "group_by": "FACTEUR_QUALI_TEST"},
        context=ctx,
        cfg=cfg,
    )
    verdict = compute_compact_verdict(selection, ctx, cfg)
    assert verdict.verdict_key in ("GO", "SURVEILLANCE")
    assert verdict.verdict_key != "NO_GO"
    assert "critique" not in verdict.rationale.lower()


def test_excluded_groups_only_in_excluded_block(compact_doc) -> None:
    excluded = compact_doc.find("excluded_groups")
    assert excluded is not None
    excluded_names = {r["group_value"] for r in excluded.data["rows"]}
    assert excluded_names == _EXCLUDED_NAMES

    for btype in _SENSITIVE_BLOCKS:
        block = compact_doc.find(btype)
        assert block is not None
        text = _block_text(block.data)
        for name in _EXCLUDED_NAMES:
            assert name not in text, f"{name} found in {btype}"


def test_statistical_test_requires_real_p_value(compact_doc) -> None:
    st = compact_doc.find("statistical_test")
    assert st is not None
    assert st.data["test_available"] is True
    assert "association" in st.data["paragraphs"][0].lower()
    assert "causalité" in st.data["paragraphs"][0].lower()


def test_statistical_test_unavailable_without_p_value(
    fixture_payload: dict, ctx: ClientContext
) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    cfg["f2_compact"] = fixture_payload["filter_config"]["f2_compact"]
    doc = build_f2_compact_document(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        context=ctx,
        cfg=cfg,
        specialist_results=[],
    )
    st = doc.find("statistical_test")
    assert st is not None
    assert st.data["test_available"] is False
    assert "non disponible" in st.data["paragraphs"][0].lower()


def test_no_abusive_causality_in_text(compact_doc) -> None:
    text = compact_doc.all_text()
    assert not text_contains_abusive_causality(text)
    assert not _CAUSALITY_RE.search(text)


def test_document_to_dict_export(compact_doc) -> None:
    exported = f2_compact_document_to_dict(compact_doc)
    assert exported["block_types"] == list(F2_COMPACT_BLOCK_ORDER)
    assert exported["meta"]["render_mode"] == "f2_compact"
    assert len(exported["blocks"]) == len(F2_COMPACT_BLOCK_ORDER)


def test_f2_narratif_still_disabled(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    assert prep.is_f2_narratif_enabled(cfg) is False


def test_f2_compact_still_disabled_by_default_in_prep(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    assert prep.is_f2_compact_enabled(cfg) is False


def test_conclusion_no_robust_favorable_message(compact_doc) -> None:
    """GROUPE_A pire ; GROUPE_C favorable robuste — pas de message d'absence."""
    conclusion = compact_doc.find("conclusion_key")
    assert conclusion is not None
    text = "\n".join(conclusion.data.get("paragraphs") or [])
    assert "référence favorable la plus robuste" in text.lower() or "à confirmer" in text.lower()
    assert "aucune référence favorable robuste" not in text.lower()


def test_business_reading_uses_favorable_not_last_rank(compact_doc) -> None:
    reading = compact_doc.find("business_reading")
    assert reading is not None
    text = _block_text(reading.data)
    assert "GROUPE_C" in text
    assert "Référence favorable" in text
    assert "HORS_PATTERN" not in text


def test_no_robust_favorable_when_only_missing_cpk(ctx: ClientContext) -> None:
    rows = [
        {
            "group_value": "GROUPE_A",
            "n": 10,
            "out_of_tolerance_rate": 8.0,
            "cpk": 0.6,
            "rank": 1,
            "warnings": [],
        },
        {
            "group_value": "GROUPE_SANS_CPK",
            "n": 15,
            "out_of_tolerance_rate": 0.0,
            "cpk": None,
            "rank": 2,
            "warnings": [],
        },
    ]
    block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "rows": rows,
        "interpretation_limits": "Association statistique — pas causalité directe.",
    }
    cfg = prep.rapport_pdf_config(ctx)
    doc = build_f2_compact_document(
        {"group_descriptive": [block]},
        {"variables": ["VARIABLE_QUANTI_TEST"], "group_by": "FACTEUR_QUALI_TEST"},
        context=ctx,
        cfg=cfg,
    )
    conclusion = doc.find("conclusion_key")
    text = "\n".join(conclusion.data.get("paragraphs") or [])
    assert "aucune référence favorable robuste" in text.lower()
    reading = doc.find("business_reading")
    assert "aucune référence favorable robuste" in _block_text(reading.data).lower()


def test_reliable_groups_in_table_not_excluded(compact_doc) -> None:
    table = compact_doc.find("group_comparison_table")
    assert table is not None
    groups = {r["group_value"] for r in table.data["rows"]}
    assert groups == {"GROUPE_A", "GROUPE_B", "GROUPE_C"}
    assert not groups & _EXCLUDED_NAMES


def _block_text(data: dict) -> str:
    parts: list[str] = []
    for key in ("title", "label", "summary", "rationale", "text", "case_note"):
        val = data.get(key)
        if isinstance(val, str):
            parts.append(val)
    for p in data.get("paragraphs") or []:
        parts.append(str(p))
    for line in data.get("lines") or []:
        parts.append(str(line))
    for b in data.get("bullets") or []:
        parts.append(str(b))
    for row in data.get("rows") or []:
        if isinstance(row, dict):
            for v in row.values():
                parts.append(str(v))
        elif isinstance(row, (list, tuple)):
            parts.extend(str(c) for c in row)
    for sec in data.get("sections") or []:
        if isinstance(sec, dict):
            parts.append(str(sec.get("heading", "")))
            for p in sec.get("paragraphs") or []:
                parts.append(str(p))
    banner = data.get("banner")
    if isinstance(banner, dict):
        parts.append(str(banner.get("text", "")))
    return "\n".join(parts)
