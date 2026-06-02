"""
Tests P7-F2 compact — C1 sélection / filtrage (sans PDF, sans assembler).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s7 import prep
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


def test_f2_compact_enabled_false_by_default(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    assert prep.is_f2_compact_enabled(cfg) is False


def test_f2_narratif_still_disabled_by_default(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    assert prep.is_f2_narratif_enabled(cfg) is False


def test_selects_aggregated_unit_block_first(fixture_payload: dict) -> None:
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    out = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        cfg=cfg,
    )
    assert out.level == "aggregated_unit"
    assert out.block_selection.get("primary_level") == "aggregated_unit"
    assert out.block_selection.get("fallback_used") is False


def test_fallback_measure_when_no_aggregated(fixture_payload: dict) -> None:
    measure_only = [
        b for b in fixture_payload["group_descriptive"] if b["level"] == "measure"
    ]
    out = build_f2_compact_selection(
        {"group_descriptive": measure_only},
        fixture_payload["intent"],
        cfg={"f2_compact": {"min_n_measure": 5}},
    )
    assert out.level == "measure"
    assert out.block_selection.get("fallback_used") is True


def test_excludes_insufficient_n_from_yaml_threshold(fixture_payload: dict) -> None:
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    out = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        cfg=cfg,
    )
    assert out.thresholds_used["min_n"] == 3
    assert out.thresholds_used["min_n_source"] == (
        "group_descriptive.aggregation.min_units_per_group"
    )
    faible = [e for e in out.rows_excluded if e.group_value == "GROUPE_FAIBLE"]
    assert len(faible) == 1
    assert faible[0].exclusion_reason == "effectif_insuffisant"


def test_excludes_pattern_non_match(fixture_payload: dict) -> None:
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    out = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        cfg=cfg,
    )
    parasite = [e for e in out.rows_excluded if e.group_value == "HORS_PATTERN_X"]
    assert len(parasite) == 1
    assert parasite[0].exclusion_reason == "pattern_yaml_non_respecte"


def test_excludes_denylist(fixture_payload: dict) -> None:
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    out = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        cfg=cfg,
    )
    denied = [e for e in out.rows_excluded if e.group_value == "OPERATEUR_X"]
    assert len(denied) == 1
    assert denied[0].exclusion_reason == "groupe_parasite"


def test_worst_group_s3_ignored_when_excluded(fixture_payload: dict) -> None:
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    out = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        cfg=cfg,
    )
    assert out.worst_group_s3 == "GROUPE_FAIBLE"
    assert out.worst_group_s3_ignored == "GROUPE_FAIBLE"
    assert out.worst_reliable is not None
    assert out.worst_reliable["group_value"] == "GROUPE_A"


def test_best_reliable_from_fiables_only(fixture_payload: dict) -> None:
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    out = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        cfg=cfg,
    )
    reliable_names = [r["group_value"] for r in out.rows_reliable]
    assert reliable_names == ["GROUPE_A", "GROUPE_B", "GROUPE_C"]
    assert out.best_reliable is not None
    assert out.best_reliable["group_value"] == "GROUPE_C"
    assert out.best_group_s3 == "GROUPE_B"
    assert out.best_group_s3_ignored is None


def test_min_n_from_yaml_not_hardcoded() -> None:
    rows = [
        {
            "group_value": "GROUPE_A",
            "n": 2,
            "rank": 1,
            "warnings": [],
        },
        {
            "group_value": "GROUPE_B",
            "n": 5,
            "rank": 2,
            "warnings": [],
        },
    ]
    block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "rows": rows,
        "worst_group": "GROUPE_A",
        "best_group": "GROUPE_B",
    }
    out = build_f2_compact_selection(
        {"group_descriptive": [block]},
        {
            "intention": "comparaison_groupes",
            "variables": ["VARIABLE_QUANTI_TEST"],
            "group_by": "FACTEUR_QUALI_TEST",
        },
        cfg={"f2_compact": {"min_n_measure": 4}},
    )
    assert out.thresholds_used["min_n"] == 4
    assert out.thresholds_used["min_n_source"] == "rapport_pdf.f2_compact.min_n_measure"
    assert len(out.rows_reliable) == 1
    assert out.rows_reliable[0]["group_value"] == "GROUPE_B"


def test_infer_min_n_from_s3_warnings_when_no_yaml() -> None:
    rows = [
        {
            "group_value": "GROUPE_A",
            "n": 2,
            "rank": 1,
            "warnings": ["effectif_faible_n_2_inferieur_7"],
        },
        {
            "group_value": "GROUPE_B",
            "n": 8,
            "rank": 2,
            "warnings": [],
        },
    ]
    block = {
        "variable": "VARIABLE_QUANTI_TEST",
        "group_by": "FACTEUR_QUALI_TEST",
        "level": "measure",
        "rows": rows,
    }
    out = build_f2_compact_selection(
        {"group_descriptive": [block]},
        {"variables": ["VARIABLE_QUANTI_TEST"]},
        cfg={},
    )
    assert out.thresholds_used["min_n"] == 7
    assert out.thresholds_used["min_n_source"] == "s3_row_warnings.effectif_faible"
    assert len(out.rows_reliable) == 1


def test_selection_json_example(fixture_payload: dict) -> None:
    """Sortie inspectable — référence pour revue avant C2."""
    cfg = {"f2_compact": fixture_payload["filter_config"]["f2_compact"]}
    out = build_f2_compact_selection(
        {"group_descriptive": fixture_payload["group_descriptive"]},
        fixture_payload["intent"],
        cfg=cfg,
    )
    payload = out.to_dict()
    assert payload["variable"] == "VARIABLE_QUANTI_TEST"
    assert payload["selection_meta"]["reliable_count"] == 3
    assert payload["selection_meta"]["excluded_count"] == 3
    assert payload["degenerate"] is False
    assert "rows_excluded" in payload
    assert payload["worst_reliable"]["group_value"] == "GROUPE_A"
