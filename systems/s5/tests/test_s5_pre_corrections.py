"""Corrections pré-v5 : ANOVA enrichi, synthèse sans jargon, P1 dédupliquées."""

from __future__ import annotations

from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s5 import prep
from systems.s6.agents import a1_dispatcher

YAML_PATH = str(
    Path(__file__).resolve().parents[3] / "configs/lisi_aerospace/client_config.yaml"
)


def test_enriched_anova_fallback_includes_stat_and_dunn() -> None:
    anova = {
        "agent": "anova_kruskal",
        "status": "success",
        "result": {
            "methode_choisie": "Kruskal-Wallis",
            "test_stat_name": "H",
            "test_stat": 108.561,
            "p_value": 1e-20,
            "significatif": True,
            "colonne_groupe": "Ref_Matrice",
            "p_value_display": "p < 0,001",
            "significance_phrase": "différence hautement significative (p < 0,001)",
        },
    }
    dunn = {
        "agent": "dunn_posthoc",
        "status": "success",
        "result": {
            "paires_significatives": [
                {
                    "groupe_a": "O5220911B2-0",
                    "groupe_b": "O5220911B3-0",
                    "p_value_display": "p < 0,001",
                },
                {
                    "groupe_a": "O5220911B3-0",
                    "groupe_b": "O5220911C1",
                    "p_value_display": "p < 0,001",
                },
            ],
        },
    }
    intent = {
        "variables": ["CR70_INTRADOS_FORME", "CR90_INTRADOS_FORME"],
        "group_by": "Ref_Matrice",
    }
    text = prep.enriched_anova_interpretation(anova, [anova, dunn], intent)
    assert "H=108.561" in text
    assert "matrices" in text
    assert "O5220911B2-0 vs O5220911B3-0" in text
    assert len(text) > 80


def test_sanitize_removes_internal_synthesis_jargon(ctx: ClientContext) -> None:
    raw = (
        "Le tableau présente le contexte issu de l'intent S1 et du YAML client, "
        "tandis que le confirme la conformité."
    )
    terms = prep.synthese_forbidden_terms(ctx)
    out, warnings = prep.sanitize_synthesis_text(raw, terms, [])
    low = out.lower()
    assert "intent s1" not in low
    assert "yaml" not in low
    assert "tandis que le confirme" not in low
    assert warnings


def test_dedupe_p1_same_column() -> None:
    items = [
        {
            "priorite": "P1",
            "action_type": "capabilite_critique",
            "cause_key": "cpk:CR90",
            "cause_label": "CR90",
            "justification": "Cpk critique CR90",
            "chiffres": {"colonne": "CR90_INTRADOS_FORME", "Cpk": 0.64},
            "use_llm": True,
        },
        {
            "priorite": "P1",
            "action_type": "matrice_prioritaire",
            "cause_key": "matrice:O5220911B2-0",
            "cause_label": "matrice O5220911B2-0",
            "justification": "Matrice prioritaire sur CR90",
            "chiffres": {
                "colonne": "CR90_INTRADOS_FORME",
                "matrice": "O5220911B2-0",
                "Cpk": 0.64,
            },
            "use_llm": True,
        },
        {
            "priorite": "P1",
            "action_type": "capabilite_critique",
            "cause_key": "cpk:CR90",
            "cause_label": "CR90",
            "justification": "Revue processus CR90",
            "chiffres": {"colonne": "CR90_INTRADOS_FORME", "Cpk": 0.64},
            "use_llm": True,
        },
    ]
    out = a1_dispatcher._dedupe_p1_items(items)
    assert len(out) == 1
    assert out[0]["action_type"] == "matrice_prioritaire"


@pytest.fixture
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)
