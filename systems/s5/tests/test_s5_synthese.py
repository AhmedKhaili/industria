"""
Tests S5 — synthèse R6/R7 sans jargon interne (point D).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s5 import prep
from systems.s5.agents import r7_checker

YAML_PATH = str(Path(__file__).resolve().parents[3] / "configs/lisi_aerospace/client_config.yaml")


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


class TestSyntheseSanitize:
    def test_sanitize_removes_internal_table_ids(self, ctx: ClientContext) -> None:
        raw = "Voir analysis_context et cpk_summary pour le détail."
        terms = prep.synthese_forbidden_terms(ctx)
        out, warnings = prep.sanitize_synthesis_text(raw, terms, [])
        assert "analysis_context" not in out.lower()
        assert "cpk_summary" not in out.lower()
        assert warnings

    def test_build_corpus_uses_metier_labels(self) -> None:
        corpus = prep.build_synthesis_corpus(
            [{"specialist": "cp_cpk", "texte": "Cpk sous seuil sur CR70."}]
        )
        assert "cp_cpk" not in corpus
        assert "Capabilité" in corpus

    def test_r7_strips_internal_terms(self, ctx: ClientContext) -> None:
        syn = "Les tableaux analysis_context et anova_summary résument l'analyse."
        out = r7_checker.run(syn, ctx, "technicien")
        assert out.get("error") is None
        lowered = out["synthese"].lower()
        assert "analysis_context" not in lowered
        assert "anova_summary" not in lowered
