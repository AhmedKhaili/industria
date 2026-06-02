"""
Tests P7-F2b — assemblage narratif_metier et fallback audit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7.agents import a1_assembler

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "group_descriptive_f2_sample.json"
GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _minimal_s4() -> dict:
    return {
        "graphs": [
            {
                "id": "box1",
                "title": "boxplot DIA_01",
                "description": "DIA_01",
                "png_bytes": _minimal_png(),
            }
        ],
        "tables": [],
    }


def _minimal_png() -> bytes:
    import base64
    import zlib
    import struct

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return png


def _minimal_s5_s6() -> tuple[dict, dict]:
    return (
        {"synthese": "", "interpretations": [], "fidelite_score": 1.0, "warnings": []},
        {
            "recommandations": [
                {
                    "priorite": "P1",
                    "action": "Contrôler le groupe M2",
                    "responsable": "qualité",
                    "delai": "immédiat",
                }
            ],
            "synthese_action": "",
            "warnings": [],
        },
    )


def test_resolve_render_mode_default_audit(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    assert prep.resolve_render_mode({"intention": "comparaison_groupes"}, cfg) == "audit_en9100"


def test_narratif_metier_blocks_present(
    ctx: ClientContext, fixture_payload: dict
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    intent = {
        **fixture_payload["intent"],
        "rapport_mode": "narratif_metier",
    }
    s5, s6 = _minimal_s5_s6()
    out = a1_assembler.run(
        "Comparaison machines ?",
        intent,
        s3,
        _minimal_s4(),
        s5,
        s6,
        ctx,
        "technicien",
    )
    assert out.get("error") is None
    doc = out["document"]
    types = doc.block_types()
    assert "conclusion_key" in types
    assert "group_comparison_table" in types
    assert "interpretation_limits" in types
    assert "executive" not in types
    assert "facteurs_influents" not in types
    assert doc.meta.get("render_mode") == "narratif_metier"
    assert "f2_narratif_skipped" not in doc.meta


def test_fallback_no_group_descriptive(ctx: ClientContext) -> None:
    intent = {
        "piece": "P-A100",
        "operation": "USINAGE",
        "group_by": "Machine",
        "variables": ["DIA_01"],
        "intention": "comparaison_groupes",
        "rapport_mode": "narratif_metier",
    }
    s5, s6 = _minimal_s5_s6()
    out = a1_assembler.run(
        "Q",
        intent,
        {"specialist_results": []},
        _minimal_s4(),
        s5,
        s6,
        ctx,
        "technicien",
    )
    doc = out["document"]
    assert "conclusion_key" not in doc.block_types()
    assert "executive" in doc.block_types()
    assert doc.meta.get("f2_narratif_skipped") == "no_group_descriptive"
    assert doc.meta.get("render_mode") == "audit_en9100"


def test_fallback_intention_not_eligible(ctx: ClientContext, fixture_payload: dict) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    intent = {
        "piece": "P-A100",
        "operation": "USINAGE",
        "intention": "portrait_statistique",
        "rapport_mode": "narratif_metier",
    }
    s5, s6 = _minimal_s5_s6()
    out = a1_assembler.run("Q", intent, s3, _minimal_s4(), s5, s6, ctx, "technicien")
    doc = out["document"]
    assert doc.meta.get("f2_narratif_skipped") == "intention_not_eligible"
    assert "conclusion_key" not in doc.block_types()


def test_audit_default_no_f2_skip_key(
    ctx: ClientContext, fixture_payload: dict
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    intent = fixture_payload["intent"]
    s5, s6 = _minimal_s5_s6()
    out = a1_assembler.run(
        "Q",
        intent,
        s3,
        _minimal_s4(),
        s5,
        s6,
        ctx,
        "technicien",
    )
    doc = out["document"]
    assert "conclusion_key" not in doc.block_types()
    assert "executive" in doc.block_types()
    assert "f2_narratif_skipped" not in doc.meta
    assert doc.meta.get("render_mode") == "audit_en9100"


def test_audit_block_types_unchanged_vs_client_fixture(ctx: ClientContext) -> None:
    """Non-régression : intent comparaison sans rapport_mode → structure audit simple."""
    ts = "2026-05-27T12:00:00.000+00:00"
    s3 = {
        "specialist_results": [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.64, "colonne": "CR90_INTRADOS_FORME"},
            },
        ],
        "group_ranking": {"pire_groupe": "X", "variable_pivot": "CR90_INTRADOS_FORME"},
    }
    s4 = _minimal_s4()
    s5, s6 = _minimal_s5_s6()
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": ["CR90_INTRADOS_FORME"],
    }
    out = a1_assembler.run("Q", intent, s3, s4, s5, s6, ctx, "technicien", timestamp=ts)
    types = out["document"].block_types()
    assert types[:4] == ["cover", "verdict", "executive", "recommendations"]
    assert "conclusion_key" not in types
