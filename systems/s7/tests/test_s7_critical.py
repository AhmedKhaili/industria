"""
Tests S7 critiques — placeholders, reject, stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systems.s7.pipeline import S7Pipeline
from systems.s7.renderer_stub import render_pdf as stub_render_pdf
from systems.s7.tests.test_s7_lisi import _pdf_text

REPO_ROOT = Path(__file__).resolve().parents[3]
YAML_PATH = str(REPO_ROOT / "configs/lisi_aerospace/client_config.yaml")
FIXED_TS = "2026-05-23T12:00:00.000+00:00"


class TestS7MetaStrip:
    def test_strip_anova_meta_llm(self) -> None:
        from systems.s5.prep import strip_llm_meta_from_interpretation

        dirty = (
            "Voici le texte corrigé : --- La méthode Kruskal-Wallis montre p < 0,001. "
            "**Explications des modifications :** 1. **Précision de la p-value :** détail interne."
        )
        clean = strip_llm_meta_from_interpretation(dirty)
        assert "explications des modifications" not in clean.lower()
        assert "kruskal" in clean.lower() or "méthode" in clean.lower()


class TestS7Critical:
    def test_s3_vide_pdf_placeholder(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        intent = {"piece": "M2L1A1C", "operation": "EQUATOR"}
        out = S7Pipeline(YAML_PATH).run(
            "Question test",
            intent,
            {"specialist_results": []},
            {"graphs": [], "tables": []},
            {"interpretations": [], "synthese": "", "fidelite_score": 0.0, "warnings": []},
            {"recommandations": [], "synthese_action": "", "warnings": []},
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        assert out.get("error") is None
        assert out["pdf_bytes"].startswith(b"%PDF")

    def test_reject_badge_donnees_certifiees(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        intent = {"piece": "M2L1A1C", "operation": "EQUATOR"}
        s5 = {
            "interpretations": [
                {
                    "specialist": "cp_cpk",
                    "texte": "Pour CR70, Cpk = 0.8 : pièce non conforme au regard du seuil EN9100.",
                    "statut": "reject",
                }
            ],
            "synthese": "",
            "fidelite_score": 0.3,
            "warnings": [],
        }
        out = S7Pipeline(YAML_PATH).run(
            "Question",
            intent,
            {"specialist_results": []},
            {"graphs": []},
            s5,
            {
                "recommandations": [
                    {
                        "priorite": "P2",
                        "action": "Vérifier réglage.",
                        "responsable": "qualité",
                        "delai": "48 heures",
                    }
                ],
                "synthese_action": "Intervention.",
                "warnings": [],
            },
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        assert out.get("error") is None
        text = _pdf_text(out["pdf_bytes"]).lower()
        assert "certifi" in text

    def test_report_port_stub_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        out = S7Pipeline(YAML_PATH).run(
            "Q",
            {"piece": "X", "operation": "Y"},
            {"specialist_results": []},
            {"graphs": []},
            {"interpretations": [], "synthese": "", "fidelite_score": 0.0, "warnings": []},
            {
                "recommandations": [
                    {
                        "priorite": "P4",
                        "action": "Surveiller.",
                        "responsable": "qualité",
                        "delai": "standard",
                    }
                ],
                "synthese_action": "OK",
                "warnings": [],
            },
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        assert out.get("error") is None
        assert len(out["pdf_bytes"]) > 1000
