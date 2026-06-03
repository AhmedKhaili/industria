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


def _portrait_s3() -> dict:
    return {
        "specialist_results": [
            {
                "agent": "descriptive",
                "status": "success",
                "result": {
                    "colonne": "CR90_INTRADOS_FORME",
                    "n": 100,
                    "moyenne": 0.12,
                    "mediane": 0.11,
                    "ecart_type": 0.04,
                    "skewness": 0.5,
                    "kurtosis": 0.2,
                    "min": 0.05,
                    "max": 0.25,
                    "q1": 0.09,
                    "q3": 0.14,
                    "iqr": 0.05,
                    "ic95_label": "[0,10 ; 0,14]",
                    "cv_pct": 33.3,
                    "nb_outliers": 3,
                    "p5": 0.06,
                    "p95": 0.22,
                    "pct_hors_lti_lts": 2.5,
                    "pct_sous_lti": 0.0,
                    "pct_au_dessus_lts": 2.5,
                    "lti": 0.0,
                    "lts": 0.2,
                },
            },
            {
                "agent": "normality",
                "status": "success",
                "result": {
                    "colonne": "CR90_INTRADOS_FORME",
                    "verdict_normalite": "non_normale",
                },
            },
            {
                "agent": "distribution_fit",
                "status": "success",
                "result": {
                    "colonne": "CR90_INTRADOS_FORME",
                    "loi_retenue": "log_normale",
                    "parametres": {"p0": 0.5, "p1": 0.0, "p2": 0.05},
                    "aic_min": -234.5,
                },
            },
        ],
    }


def test_portrait_intent_triggers_complet_layout(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    ts = "2026-05-27T14:00:00.000+00:00"
    s3 = _portrait_s3()
    s4 = {
        "graphs": [
            {
                "title": "histogram CR90_INTRADOS_FORME",
                "type": "histogram",
                "png_bytes": _minimal_png(),
            }
        ]
    }
    s5 = {"synthese": "Portrait certifié.", "interpretations": [], "fidelite_score": 0.9}
    s6 = {
        "recommandations": [
            {"priorite": "P3", "action": "Surveiller la dispersion", "responsable": "qualité", "delai": "7j"}
        ],
        "synthese_action": "Suivi renforcé.",
    }
    intent = {
        "intention": "portrait_statistique",
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": ["CR90_INTRADOS_FORME"],
    }
    a1 = a1_assembler.run(
        "Analyse CR90",
        intent,
        s3,
        s4,
        s5,
        s6,
        ctx,
        "technicien",
        timestamp=ts,
    )
    doc = a1["document"]
    assert doc.meta["rapport_type"] == "complet"
    assert "portrait_statistique" in doc.block_types()
    assert "executive" not in doc.block_types()
    assert "interpretations" not in doc.block_types()

    qg = quality_gate_run("Analyse CR90", intent, s3, s5, s6, doc, "technicien", cfg)
    assert qg["publishable"], qg.get("blocking")

    pdf = render_pdf(doc)
    text = _pdf_text(pdf).lower()
    assert "portrait statistique" in text
    assert "moyenne" in text
    assert "non normale" in text
    assert "meilleur ajustement" in text
    assert "descriptive" not in text
    assert "normality" not in text
    assert "distribution_fit" not in text
    assert "aic" not in text
    assert "bic" not in text
    assert len(PdfReader(__import__("io").BytesIO(pdf)).pages) <= prep.max_pages_complet(cfg)


def test_simple_layout_charts_no_na_interpretation(ctx: ClientContext) -> None:
    ts = "2026-05-27T12:00:00.000+00:00"
    s4 = {
        "graphs": [
            {
                "id": "boxplot_CR90_INTRADOS_FORME",
                "title": "boxplot CR90",
                "type": "boxplot",
                "png_bytes": _minimal_png(),
            }
        ]
    }
    s5 = {
        "synthese": "Synthèse avec M2L1A1C et CR90.",
        "interpretations": [
            {"specialist": "graphique", "texte": "N/A", "statut": "fallback"}
        ],
        "fidelite_score": 0.8,
    }
    s6 = {
        "recommandations": [
            {"priorite": "P1", "action": "Agir", "responsable": "q", "delai": "immédiat"}
        ],
        "synthese_action": "",
    }
    intent = {
        "intention": "comparaison_groupes",
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": ["CR90_INTRADOS_FORME"],
    }
    a1 = a1_assembler.run("Q", intent, {"specialist_results": []}, s4, s5, s6, ctx, "technicien", timestamp=ts)
    pdf = render_pdf(a1["document"])
    text = _pdf_text(pdf)
    if "PREUVES VISUELLES" in text:
        charts_part = text.split("PREUVES VISUELLES", 1)[1]
        charts_part = charts_part.split("MÉTRIQUES", 1)[0]
        assert "N/A" not in charts_part


def test_comparaison_groupes_keeps_simple_layout(ctx: ClientContext) -> None:
    ts = "2026-05-27T12:00:00.000+00:00"
    intent = {
        "intention": "comparaison_groupes",
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": ["CR90_INTRADOS_FORME"],
        "group_by": "Ref_Matrice",
    }
    s3 = {
        "specialist_results": [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.64, "colonne": "CR90_INTRADOS_FORME", "conforme_EN9100": False},
            }
        ],
    }
    s4 = {"tables": [], "graphs": [{"title": "boxplot X", "png_bytes": _minimal_png()}]}
    s5 = {"synthese": "Écart entre groupes.", "interpretations": [], "fidelite_score": 0.8}
    s6 = {
        "recommandations": [
            {"priorite": "P1", "action": "Agir", "responsable": "qualité", "delai": "immédiat"}
        ],
        "synthese_action": "Action.",
    }
    a1 = a1_assembler.run("Impact matrice ?", intent, s3, s4, s5, s6, ctx, "technicien", timestamp=ts)
    doc = a1["document"]
    assert doc.meta["rapport_type"] == "simple"
    assert doc.block_types() == [
        "cover",
        "verdict",
        "executive",
        "recommendations",
        "charts",
        "metrics_table",
        "interpretations",
        "traceability",
    ]


def test_resolve_rapport_type_diagnostic_causal() -> None:
    assert prep.resolve_rapport_type({"intention": "diagnostic_causal"}) == "complet"
    assert prep.resolve_rapport_type({"intention": "comparaison_groupes"}) == "simple"


def test_portrait_verdict_no_go_when_pct_hors_tol_positive() -> None:
    s3 = _portrait_s3()
    s3["specialist_results"][0]["result"]["pct_hors_lti_lts"] = 4.8
    s3["specialist_results"][0]["result"]["pct_sous_lti"] = 4.8
    key, _, _, _ = prep.portrait_verdict_from_metrics(
        s3["specialist_results"],
        prep.rapport_pdf_config(ClientContext.load(YAML_PATH)),
    )
    assert key == "NO_GO"


def test_portrait_table_has_enriched_indicators(ctx: ClientContext) -> None:
    cards = prep.build_portrait_variables(_portrait_s3()["specialist_results"])
    assert len(cards) == 1
    labels = [r[0] for r in cards[0]["rows"]]
    assert len(labels) >= 15
    assert "Effectif (n)" in labels
    assert "Aplatissement" in labels
    assert "% sous LTI" in labels
    assert "kurtosis" not in " ".join(labels).lower()


def test_chart_interpretation_skips_na_placeholder() -> None:
    assert prep.chart_interpretation_for_pdf("") == ""
    assert prep.chart_interpretation_for_pdf("N/A") == ""
    assert prep.chart_interpretation_for_pdf("  ") == ""
    from systems.s7.renderer_stub import _show_chart_interpretation

    assert not _show_chart_interpretation("N/A")
    assert _show_chart_interpretation("Distribution asymétrique à droite.")


def test_finalize_chart_interpretation_complete_sentence() -> None:
    from systems.s5.prep import finalize_chart_interpretation

    out = finalize_chart_interpretation("La distribution est asymétrique avec un pic")
    assert out.endswith(".")


def test_portrait_chart_llm_budget_at_least_300() -> None:
    import inspect

    from systems.s5.agents import r3_portrait_charts

    src = inspect.getsource(r3_portrait_charts.run)
    assert "num_predict=300" in src


def test_portrait_chart_fallback_rendered_without_s5_llm(ctx: ClientContext) -> None:
    """S7 doit afficher une interprétation Python même sans texte S5."""
    s3 = _portrait_s3()
    s4 = {
        "graphs": [
            {
                "id": "histogram_CR90_INTRADOS_FORME",
                "type": "histogram",
                "variable": "CR90_INTRADOS_FORME",
                "title": "histogram",
                "description": "desc",
                "png_bytes": _minimal_png(),
            }
        ]
    }
    s5 = {"synthese": "", "interpretations": [], "fidelite_score": 0.9}
    s6 = {
        "recommandations": [
            {"priorite": "P1", "action": "x", "responsable": "q", "delai": "immédiat"}
        ],
        "synthese_action": "",
    }
    intent = {
        "intention": "portrait_statistique",
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": ["CR90_INTRADOS_FORME"],
    }
    a1 = a1_assembler.run("Q", intent, s3, s4, s5, s6, ctx, "technicien")
    charts = a1["document"].find("charts")
    interp = charts.data["items"][0].get("interpretation", "")
    assert len(interp) > 40
    assert "N/A" not in interp
    pdf = render_pdf(a1["document"])
    txt = _pdf_text(pdf)
    assert "GRAPHIQUES" in txt
    assert "moyenne" in txt.lower() or "0,12" in txt or "0.12" in txt


def test_portrait_pdf_no_go_with_hors_tol(ctx: ClientContext) -> None:
    cfg = prep.rapport_pdf_config(ctx)
    ts = "2026-05-27T15:00:00.000+00:00"
    s3 = _portrait_s3()
    s3["specialist_results"][0]["result"]["pct_hors_lti_lts"] = 4.8
    s4 = {
        "graphs": [
            {
                "id": "histogram_CR90_INTRADOS_FORME",
                "title": "histogram CR90",
                "type": "histogram",
                "variable": "CR90_INTRADOS_FORME",
                "png_bytes": _minimal_png(),
            }
        ]
    }
    s5 = {
        "synthese": "",
        "interpretations": [
            {
                "specialist": "chart_histogram",
                "chart_id": "histogram_CR90_INTRADOS_FORME",
                "texte": (
                    "Distribution asymétrique à droite (asymétrie 0,92). "
                    "La majorité des mesures se concentre entre 0,05 et 0,15 mm. "
                    "4,8 % des valeurs dépassent le LTS à 0,2 mm."
                ),
                "statut": "Accept",
            }
        ],
        "fidelite_score": 0.9,
    }
    s6 = {
        "recommandations": [
            {"priorite": "P4", "action": "Surveiller", "responsable": "q", "delai": "7j"}
        ],
        "synthese_action": "",
    }
    intent = {
        "intention": "portrait_statistique",
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": ["CR90_INTRADOS_FORME"],
    }
    a1 = a1_assembler.run("Q", intent, s3, s4, s5, s6, ctx, "technicien", timestamp=ts)
    doc = a1["document"]
    assert doc.meta["verdict_key"] == "NO_GO"
    pdf = render_pdf(doc)
    assert "no-go" in _pdf_text(pdf).lower()


def _minimal_png() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
