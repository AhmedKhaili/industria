"""
Tests S6 — chemins critiques (P1 non filtré, bornes Cpk, causes, RAG, timeout).
Complète test_s6_lisi.py sans mock « tout passe ».
"""

from __future__ import annotations

import pytest

from systems.s1.client_context import ClientContext
from systems.s5 import llm_client
from systems.s6.agents import a1_dispatcher, a2_redacteur
from systems.s6.pipeline import S6Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"
RAG_EMPTY_MSG = "Aucune procédure locale trouvée"


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def _minimal_s5() -> dict:
    return {
        "interpretations": [],
        "synthese": "Synthèse test.",
        "fidelite_score": 0.9,
        "warnings": [],
    }


class TestS6CriticalP1NonFiltre:
    def test_p1_presentes_profil_directeur(self, ctx: ClientContext) -> None:
        """P1 jamais écrêtées — même profil directeur (agrège seulement P2/P3)."""
        intent = {
            "piece": "M2L1A1C",
            "operation": "EQUATOR",
            "group_by": "Ref_Matrice",
        }
        results = [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.65, "colonne": "CR70_INTRADOS_FORME", "conforme_EN9100": False},
            },
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.72, "colonne": "CR90_INTRADOS_FORME", "conforme_EN9100": False},
            },
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 1.2, "colonne": "CR10_INTRADOS_FORME", "conforme_EN9100": False},
            },
            {
                "agent": "anova_kruskal",
                "status": "success",
                "result": {"significatif": True, "p_value": 0.01, "methode_choisie": "Kruskal-Wallis"},
            },
        ]
        s3 = {"specialist_results": results}
        s6 = S6Pipeline(YAML_PATH).run(
            intent, s3, _minimal_s5(), profile="directeur", rag_port=None
        )
        assert s6.get("error") is None, s6
        p1 = [r for r in s6["recommandations"] if r["priorite"] == "P1"]
        assert len(p1) == 2, "Les deux P1 critiques doivent rester visibles pour le directeur"
        assert all("immédiat" in r["delai"].lower() or r["priorite"] == "P1" for r in p1)


class TestS6CriticalBorneCpk:
    def test_cpk_exactement_1_0_declenche_p2_pas_p1(self, ctx: ClientContext) -> None:
        intent = {"piece": "M2L1A1C", "operation": "FILAGE"}
        results = [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 1.0, "colonne": "CR10_INTRADOS_FORME", "conforme_EN9100": False},
            }
        ]
        out = a1_dispatcher.run(results, intent, ctx, "technicien")
        assert out.get("error") is None
        priorites = [i["priorite"] for i in out["items"]]
        assert "P1" not in priorites
        assert "P2" in priorites


class TestS6CriticalCausesSeparees:
    def test_deux_p1_deux_variables_distinctes(self, ctx: ClientContext) -> None:
        intent = {"piece": "M2L1A1C", "operation": "EQUATOR"}
        results = [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.8, "colonne": "CR70_INTRADOS_FORME", "conforme_EN9100": False},
            },
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.9, "colonne": "CR90_INTRADOS_FORME", "conforme_EN9100": False},
            },
        ]
        out = a1_dispatcher.run(results, intent, ctx, "technicien")
        assert out.get("error") is None
        p1 = [i for i in out["items"] if i["priorite"] == "P1"]
        assert len(p1) == 2
        keys = {i["cause_key"] for i in p1}
        assert len(keys) == 2, "Deux causes racines distinctes — pas une seule reco agrégée"


class TestS6CriticalRagAbsent:
    def test_rag_port_none_warning_et_non_bloque(self, ctx: ClientContext) -> None:
        intent = {"piece": "M2L1A1C", "operation": "FILAGE"}
        results = [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.85, "colonne": "CR1", "conforme_EN9100": False},
            }
        ]
        s6 = S6Pipeline(YAML_PATH).run(
            intent,
            {"specialist_results": results},
            _minimal_s5(),
            profile="technicien",
            rag_port=None,
        )
        assert s6.get("error") is None, s6
        assert s6["rag_used"] is False
        assert s6["recommandations"]
        assert any(RAG_EMPTY_MSG in w for w in s6.get("warnings", []))


class TestS6CriticalTimeoutA2:
    def test_a2_fallback_si_timeout_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_timeout(*_a: object, **_k: object) -> object:
            raise TimeoutError("ollama timeout")

        monkeypatch.setattr(llm_client.requests, "post", raise_timeout)

        items = [
            {
                "priorite": "P1",
                "action_type": "capabilite_critique",
                "responsable": "responsable qualité",
                "delai": "immédiat",
                "justification": "Cpk = 0.75 sur CR70 — critique.",
                "cause_key": "variable:CR70",
                "cause_label": "CR70_INTRADOS_FORME",
                "use_llm": True,
                "chiffres": {"Cpk": 0.75},
                "rag_excerpt": "",
                "rag_used": False,
            }
        ]
        out = a2_redacteur.run(items)
        assert out.get("error") is None
        assert items[0]["action"]
        assert "[P1]" in items[0]["action"] or "Responsable" in items[0]["action"]

    def test_pipeline_s6_recommandations_si_timeout_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_timeout(*_a: object, **_k: object) -> object:
            raise TimeoutError("ollama timeout")

        monkeypatch.setattr(llm_client.requests, "post", raise_timeout)

        intent = {"piece": "M2L1A1C", "operation": "FILAGE"}
        results = [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.75, "colonne": "CR70_INTRADOS_FORME", "conforme_EN9100": False},
            }
        ]
        s6 = S6Pipeline(YAML_PATH).run(
            intent,
            {"specialist_results": results},
            _minimal_s5(),
            profile="technicien",
            rag_port=None,
        )
        assert s6.get("error") is None, s6
        assert len(s6["recommandations"]) >= 1
        assert all(r.get("action") for r in s6["recommandations"])
