"""Rapport PDF mode client — zéro jargon interne."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7.agents import a1_assembler, a2_renderer
from systems.s7.document import ReportDocument
from systems.s7.quality_gate import run as quality_gate_run
from systems.s7.renderer_stub import render_pdf

REPO = Path(__file__).resolve().parents[3]
YAML_PATH = str(REPO / "configs/lisi_aerospace/client_config.yaml")


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io := __import__("io").BytesIO(pdf_bytes))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


@pytest.fixture
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def test_client_mode_config_active(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    assert prep.is_client_mode(cfg)


def test_quality_gate_blocks_internal_jargon(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    doc = ReportDocument(
        meta={"client_mode": True},
        blocks=[],
    )
    out = quality_gate_run(
        "Question test",
        {"piece": "X"},
        {"specialist_results": [{"agent": "cp_cpk", "status": "success", "result": {"Cpk": 0.5}}]},
        {"synthese": "Rapport avec LLM corrigé et fallback."},
        {"recommandations": [{"priorite": "P1", "action": "Agir"}]},
        doc,
        "technicien",
        cfg,
    )
    assert not out["publishable"]
    assert out["blocking"]


def test_client_pdf_fixture_no_jargon(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    ts = "2026-05-27T12:00:00.000+00:00"
    s3 = {
        "specialist_results": [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.64, "colonne": "CR90_INTRADOS_FORME", "conforme_EN9100": False},
            },
            {
                "agent": "anova_kruskal",
                "status": "success",
                "result": {
                    "methode_choisie": "Kruskal-Wallis",
                    "test_stat_name": "H",
                    "test_stat": 108.56,
                    "p_value": 0.0001,
                    "significatif": True,
                    "p_value_display": "p < 0,001",
                    "significance_phrase": "différence hautement significative (p < 0,001)",
                },
            },
        ],
        "group_ranking": {"pire_groupe": "O5220911B2-0", "variable_pivot": "CR90_INTRADOS_FORME"},
    }
    s4 = {
        "tables": [
            {
                "title": "Capabilité processus (Cp/Cpk)",
                "columns": ["Variable", "Cpk", "Cp", "Conforme EN9100", "Interprétation"],
                "rows": [
                    ["CR90_INTRADOS_FORME", "0.643", "0.746", "Non", "Non capable"],
                ],
            }
        ],
        "graphs": [
            {
                "title": "boxplot CR70_INTRADOS_FORME",
                "description": "CR70 mm",
                "png_bytes": _minimal_png(),
            },
            {
                "title": "boxplot CR90_INTRADOS_FORME",
                "description": "CR90 mm",
                "png_bytes": _minimal_png(),
            },
            {
                "title": "boxplot CR10_INTRADOS_FORME",
                "description": "CR10 mm",
                "png_bytes": _minimal_png(),
            },
            {
                "title": "boxplot CR30_INTRADOS_FORME",
                "description": "extra",
                "png_bytes": _minimal_png(),
            },
        ],
    }
    s5 = {
        "synthese": "Différences significatives entre matrices. Cpk critique sur CR90.",
        "interpretations": [
            {
                "specialist": "anova_kruskal",
                "texte": "Kruskal-Wallis H=108.56, différence hautement significative (p < 0,001) entre les matrices.",
                "statut": "reject",
            },
            {
                "specialist": "cp_cpk",
                "texte": "Sur CR90, capabilité critique (Cpk = 0.643).",
                "statut": "reject",
            },
            {
                "specialist": "dunn_posthoc",
                "texte": "O5220911B2-0 vs O5220911B3-0 : p < 0,001",
                "statut": "reject",
            },
        ],
        "fidelite_score": 0.72,
        "warnings": [],
    }
    s6 = {
        "recommandations": [
            {
                "priorite": "P1",
                "action": "Corriger matrice O5220911B2-0 sur CR90",
                "responsable": "qualité",
                "delai": "immédiat",
            },
            {"priorite": "P2", "action": "Surveiller CR10", "responsable": "qualité", "delai": "48h"},
        ],
        "synthese_action": "Action immédiate sur la matrice prioritaire.",
        "warnings": [],
    }
    a1 = a1_assembler.run(
        "La matrice a-t-elle un impact ?",
        {"piece": "M2L1A1C", "operation": "EQUATOR", "variables": ["CR90_INTRADOS_FORME"]},
        s3,
        s4,
        s5,
        s6,
        ctx,
        "technicien",
        timestamp=ts,
    )
    assert a1.get("error") is None
    doc: ReportDocument = a1["document"]
    qg = quality_gate_run(
        "La matrice a-t-elle un impact ?",
        {"piece": "M2L1A1C"},
        s3,
        s5,
        s6,
        doc,
        "technicien",
        cfg,
    )
    assert qg["publishable"], qg.get("blocking")

    pdf = render_pdf(doc)
    text = _pdf_text(pdf).lower()
    assert "rpt-" in text
    assert "no-go" in text
    assert "cpk minimum" in text
    assert "llm" not in text
    assert "fallback" not in text
    assert "fidélité" not in text and "fidelite" not in text
    assert "anova_kruskal" not in text
    assert "ref_matrice" not in text
    assert text.count("boxplot") <= 6


def _minimal_png() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
