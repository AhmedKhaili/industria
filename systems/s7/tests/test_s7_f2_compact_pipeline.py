"""
Tests P7-F2 compact — C3 pipeline assembler + renderer PDF (flag explicite).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7.agents import a1_assembler
from systems.s7.f2_compact_blocks import F2_COMPACT_BLOCK_ORDER
from systems.s7.f2_templates import text_contains_abusive_causality
from systems.s7.quality_gate import run as quality_gate_run
from systems.s7.renderer_stub import render_pdf
from systems.s7.tests.test_s7_f2_assembler import _minimal_png, _minimal_s4, _minimal_s5_s6

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "group_descriptive_f2_compact_filter.json"
)
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)

_EXCLUDED = frozenset({"GROUPE_FAIBLE", "HORS_PATTERN_X", "OPERATEUR_X"})
_SENSITIVE_BLOCKS = frozenset(
    {
        "conclusion_key",
        "verdict",
        "key_indicators",
        "business_reading",
        "final_verdict",
    }
)


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def enable_f2_compact(monkeypatch: pytest.MonkeyPatch):
    original = prep.rapport_pdf_config

    def _wrap(context):
        cfg = original(context)
        merged = dict(cfg)
        merged["f2_compact_enabled"] = True
        merged["f2_compact"] = json.loads(FIXTURE.read_text(encoding="utf-8"))[
            "filter_config"
        ]["f2_compact"]
        return merged

    monkeypatch.setattr(prep, "rapport_pdf_config", _wrap)
    yield


def _run_assembler(
    ctx: ClientContext,
    intent: dict,
    s3: dict,
    *,
    enable_compact: bool = True,
    monkeypatch: pytest.MonkeyPatch | None = None,
    df_propre=None,
):
    if enable_compact and monkeypatch is not None:
        original = prep.rapport_pdf_config

        def _wrap(context):
            cfg = original(context)
            merged = dict(cfg)
            merged["f2_compact_enabled"] = True
            merged["f2_compact"] = json.loads(FIXTURE.read_text(encoding="utf-8"))[
                "filter_config"
            ]["f2_compact"]
            return merged

        monkeypatch.setattr(prep, "rapport_pdf_config", _wrap)

    s5, s6 = _minimal_s5_s6()
    s3_full = dict(s3)
    if "specialist_results" not in s3_full:
        s3_full["specialist_results"] = [
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
        ]
    return a1_assembler.run(
        "Comparer VARIABLE_QUANTI_TEST par FACTEUR_QUALI_TEST",
        intent,
        s3_full,
        _minimal_s4(),
        s5,
        s6,
        ctx,
        "technicien",
        timestamp="2026-06-02T10:00:00.000+00:00",
        df_propre=df_propre,
    )


def test_compact_off_audit_unchanged(
    ctx: ClientContext, fixture_payload: dict
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    out = _run_assembler(
        ctx,
        fixture_payload["intent"],
        s3,
        enable_compact=False,
    )
    doc = out["document"]
    assert out.get("error") is None
    assert doc.meta.get("render_mode") == "audit_en9100"
    assert "executive" in doc.block_types()
    assert "business_synthesis" not in doc.block_types()
    assert "f2_compact_skipped" not in doc.meta


def test_compact_on_block_order(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    out = _run_assembler(ctx, fixture_payload["intent"], s3, monkeypatch=monkeypatch)
    doc = out["document"]
    assert out.get("error") is None
    assert doc.meta.get("render_mode") == "f2_compact"
    assert doc.block_types() == list(F2_COMPACT_BLOCK_ORDER)
    assert doc.meta.get("verdict_key") == "NO_GO"


def test_compact_skipped_empty_s3(
    ctx: ClientContext, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = {
        "intention": "comparaison_groupes",
        "variables": ["VARIABLE_QUANTI_TEST"],
        "group_by": "FACTEUR_QUALI_TEST",
    }
    out = _run_assembler(ctx, intent, {"specialist_results": []}, monkeypatch=monkeypatch)
    doc = out["document"]
    assert doc.meta.get("render_mode") == "audit_en9100"
    assert doc.meta.get("f2_compact_skipped") == "no_group_descriptive"
    assert "executive" in doc.block_types()


def test_compact_skipped_intention_not_f2(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    intent = {
        "piece": "P-A100",
        "operation": "USINAGE",
        "intention": "portrait_statistique",
        "variables": ["DIA_01"],
    }
    out = _run_assembler(ctx, intent, s3, monkeypatch=monkeypatch)
    doc = out["document"]
    assert doc.meta.get("render_mode") == "audit_en9100"
    assert doc.meta.get("f2_compact_skipped") == "intention_not_eligible"


def test_rapport_mode_alone_does_not_trigger_compact(
    ctx: ClientContext, fixture_payload: dict
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    intent = {
        **fixture_payload["intent"],
        "rapport_mode": "narratif_metier",
    }
    out = _run_assembler(ctx, intent, s3, enable_compact=False)
    doc = out["document"]
    assert doc.meta.get("render_mode") == "audit_en9100"
    assert "business_synthesis" not in doc.block_types()


def test_narratif_flag_does_not_trigger_compact_without_compact_flag(
    ctx: ClientContext, fixture_payload: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = prep.rapport_pdf_config

    def _wrap(context):
        cfg = original(context)
        merged = dict(cfg)
        merged["f2_narratif_enabled"] = True
        return merged

    monkeypatch.setattr(prep, "rapport_pdf_config", _wrap)
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    intent = {
        **fixture_payload["intent"],
        "rapport_mode": "narratif_metier",
    }
    s5, s6 = _minimal_s5_s6()
    out = a1_assembler.run(
        "Q", intent, s3, _minimal_s4(), s5, s6, ctx, "technicien"
    )
    doc = out["document"]
    assert doc.meta.get("render_mode") == "narratif_metier"
    assert "business_synthesis" not in doc.block_types()


def test_excluded_names_not_in_sensitive_blocks(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    out = _run_assembler(ctx, fixture_payload["intent"], s3, monkeypatch=monkeypatch)
    doc = out["document"]
    for btype in _SENSITIVE_BLOCKS:
        block = doc.find(btype)
        assert block is not None
        text = _block_text(block.data)
        for name in _EXCLUDED:
            assert name not in text, f"{name} in {btype}"


def test_statistical_reliability_rendered_as_table_in_document(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    out = _run_assembler(ctx, fixture_payload["intent"], s3, monkeypatch=monkeypatch)
    rel = out["document"].find("statistical_reliability")
    assert rel is not None
    assert rel.data.get("columns")
    assert rel.data.get("rows")
    assert "IC95 moyenne" in rel.data["columns"]


def test_excluded_absent_from_chart_included_groups(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pandas as pd

    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    df = pd.DataFrame(
        {
            "FACTEUR_QUALI_TEST": ["GROUPE_A"] * 8
            + ["GROUPE_B"] * 6
            + ["GROUPE_C"] * 4
            + ["OPERATEUR_X"] * 20,
            "VARIABLE_QUANTI_TEST": [0.1] * 38,
        }
    )
    out = _run_assembler(
        ctx, fixture_payload["intent"], s3, monkeypatch=monkeypatch, df_propre=df
    )
    charts = out["document"].find("charts")
    assert charts is not None
    for it in charts.data.get("items") or []:
        included = it.get("included_groups") or []
        for name in _EXCLUDED:
            assert name not in included


def test_renderer_smoke_and_page_count(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    out = _run_assembler(ctx, fixture_payload["intent"], s3, monkeypatch=monkeypatch)
    doc = out["document"]
    pdf = render_pdf(doc)
    assert len(pdf) > 500

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = OUTPUT_DIR / "f2_compact_fixture.pdf"
    pdf_path.write_bytes(pdf)

    reader = PdfReader(io.BytesIO(pdf))
    page_count = len(reader.pages)
    assert 4 <= page_count <= 6
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    assert "Comparaison" in text
    assert "Groupes non exploités" in text
    assert "GROUPE_A" in text
    for name in _EXCLUDED:
        assert name in text


def test_excluded_names_only_after_excluded_section_in_pdf(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    out = _run_assembler(ctx, fixture_payload["intent"], s3, monkeypatch=monkeypatch)
    pdf = render_pdf(out["document"])
    text = "\n".join(
        (p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages
    )
    marker = "Groupes non exploités"
    pos = text.find(marker)
    assert pos >= 0
    before = text[:pos]
    after = text[pos:]
    for name in _EXCLUDED:
        assert name not in before, f"{name} before excluded section"
        assert name in after, f"{name} missing after excluded section"


def test_quality_gate_compact_passes(
    ctx: ClientContext, fixture_payload: dict, enable_f2_compact, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    out = _run_assembler(ctx, fixture_payload["intent"], s3, monkeypatch=monkeypatch)
    doc = out["document"]
    cfg = prep.rapport_pdf_config(ctx)
    cfg["f2_compact_enabled"] = True
    gate = quality_gate_run(
        "Q",
        fixture_payload["intent"],
        s3,
        _minimal_s5_s6()[0],
        _minimal_s5_s6()[1],
        doc,
        "technicien",
        cfg,
    )
    assert not text_contains_abusive_causality(doc.all_text())
    assert gate["publishable"] or not gate["blocking"]


def test_f2_narratif_still_off_by_default(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    assert prep.is_f2_narratif_enabled(cfg) is False
    assert prep.is_f2_compact_enabled(cfg) is False


def _block_text(data: dict) -> str:
    parts: list[str] = []
    for key in ("title", "label", "summary", "rationale", "text"):
        val = data.get(key)
        if isinstance(val, str):
            parts.append(val)
    for p in data.get("paragraphs") or []:
        parts.append(str(p))
    for b in data.get("bullets") or []:
        parts.append(str(b))
    for row in data.get("rows") or []:
        if isinstance(row, dict):
            for v in row.values():
                parts.append(str(v))
    for sec in data.get("sections") or []:
        if isinstance(sec, dict):
            for p in sec.get("paragraphs") or []:
                parts.append(str(p))
    banner = data.get("banner")
    if isinstance(banner, dict):
        parts.append(str(banner.get("text", "")))
    return "\n".join(parts)
