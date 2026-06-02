"""
Tests P7-F2b — rendu PDF smoke pour blocs narratif F2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7.agents import a1_assembler
from systems.s7.quality_gate import run as quality_gate_run
from systems.s7.renderer_stub import render_pdf
from systems.s7.tests.test_s7_f2_assembler import _minimal_png, _minimal_s4, _minimal_s5_s6

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "group_descriptive_f2_sample.json"
GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


@pytest.fixture(scope="module")
def _enable_f2_narratif_module():
    """Patch module-scoped — narratif F2 expérimental pour tests renderer."""
    original = prep.rapport_pdf_config

    def _wrap(context):
        cfg = original(context)
        merged = dict(cfg)
        merged["f2_narratif_enabled"] = True
        return merged

    prep.rapport_pdf_config = _wrap
    yield
    prep.rapport_pdf_config = original


@pytest.fixture(scope="module")
def narratif_document(ctx: ClientContext, _enable_f2_narratif_module):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    s3 = {"group_descriptive": payload["group_descriptive"]}
    intent = {**payload["intent"], "rapport_mode": "narratif_metier"}
    s5, s6 = _minimal_s5_s6()
    out = a1_assembler.run(
        "Comparaison ?",
        intent,
        s3,
        _minimal_s4(),
        s5,
        s6,
        ctx,
        "technicien",
    )
    assert out.get("error") is None
    return out["document"]


def test_renderer_smoke_pdf(narratif_document) -> None:
    pdf = render_pdf(narratif_document)
    assert len(pdf) > 500
    text = "\n".join(
        (p.extract_text() or "")
        for p in PdfReader(__import__("io").BytesIO(pdf)).pages
    ).lower()
    assert "conclusion" in text
    assert "comparaison des groupes" in text
    assert "limites" in text


def test_quality_gate_prudent_causality_passes(ctx: ClientContext, narratif_document) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    narratif_document.meta["render_mode"] = "narratif_metier"
    qg = quality_gate_run(
        "Q",
        {"rapport_mode": "narratif_metier"},
        {"specialist_results": []},
        {},
        {},
        narratif_document,
        "technicien",
        cfg,
    )
    assert qg["publishable"], qg.get("blocking")


def test_quality_gate_causality_blocked(ctx: ClientContext, narratif_document) -> None:
    from systems.s7.document import ReportBlock

    bad = narratif_document
    ck = bad.find("conclusion_key")
    if ck:
        data = dict(ck.data)
        data["paragraphs"] = list(data.get("paragraphs") or []) + [
            "La matrice cause le défaut."
        ]
        bad.blocks = [
            b if b.block_type != "conclusion_key" else ReportBlock("conclusion_key", data)
            for b in bad.blocks
        ]
    cfg = prep.rapport_pdf_config(ctx)
    bad.meta["render_mode"] = "narratif_metier"
    qg = quality_gate_run(
        "Q",
        {"rapport_mode": "narratif_metier"},
        {"specialist_results": []},
        {},
        {},
        bad,
        "technicien",
        cfg,
    )
    assert not qg["publishable"]
    assert any("causal" in b.lower() for b in qg["blocking"])
