"""
Tests S6 — recommandations (unitaires + LISI).
"""

from __future__ import annotations

import re

import pytest

from systems.s1.client_context import ClientContext
from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s5.pipeline import S5Pipeline
from systems.s6.agents import a1_dispatcher, a2_redacteur, a4_synthesizer
from systems.s6.pipeline import S6Pipeline
from systems.s6.rag_port import StubRagPort
from systems.s5 import llm_client

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"
QUESTION_COMPARAISON = (
    "La matrice a-t-elle un impact sur la forme intrados de M2L1A1C ?"
)


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


class TestS6P1Dispatch:
    def test_p1_declenche_cpk_sous_seuil(self, ctx: ClientContext) -> None:
        intent = {"piece": "M2L1A1C", "operation": "EQUATOR", "group_by": "Ref_Matrice"}
        results = [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {
                    "Cpk": 0.75,
                    "colonne": "CR70_INTRADOS_FORME",
                    "conforme_EN9100": False,
                },
            }
        ]
        out = a1_dispatcher.run(results, intent, ctx, "technicien")
        assert out.get("error") is None
        p1 = [i for i in out["items"] if i["priorite"] == "P1"]
        assert p1, "Cpk < 1.0 doit déclencher P1"
        assert p1[0]["delai"] == "immédiat"
        assert "responsable" in p1[0]


class TestS6P3SansLLM:
    def test_p4_template_sans_appel_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []

        def count_chat(*_a, **_k):
            calls.append(1)
            return None

        monkeypatch.setattr(llm_client, "chat", count_chat)

        items = [
            {
                "priorite": "P4",
                "action_type": "surveillance",
                "responsable": "responsable qualité",
                "delai": "surveillance standard",
                "justification": "Tout conforme.",
                "cause_key": "global",
                "cause_label": "processus",
                "use_llm": False,
                "chiffres": {},
                "rag_excerpt": "",
                "rag_used": False,
            }
        ]
        out = a2_redacteur.run(items)
        assert out.get("error") is None
        assert items[0]["action"]
        assert len(calls) == 0


class TestS6ProfilDirecteur:
    def test_synthese_directeur_sans_forbidden(self, ctx: ClientContext) -> None:
        items = [
            {
                "priorite": "P1",
                "action": "Stopper la ligne et vérifier le réglage presse.",
                "responsable": "direction générale",
                "delai": "immédiat",
                "justification": "Capabilité critique.",
                "cause_label": "CR70",
            }
        ]
        intent = {"piece": "M2L1A1C", "operation": "FILAGE"}
        out = a4_synthesizer.run(items, ctx, "directeur", intent)
        assert out.get("error") is None
        text = out["synthese_action"].lower()
        for word in ("z-score", "anova", "p-value", "cpk"):
            assert word not in text


class TestS6RagAbsent:
    def test_rag_stub_non_bloquant(self, ctx: ClientContext) -> None:
        intent = {"piece": "M2L1A1C", "operation": "FILAGE"}
        results = [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": 0.9, "colonne": "CR1", "conforme_EN9100": False},
            }
        ]
        s6 = S6Pipeline(YAML_PATH)
        s3 = {"specialist_results": results}
        s5 = {"interpretations": [], "synthese": "", "fidelite_score": 0.5, "warnings": []}
        out = s6.run(intent, s3, s5, profile="technicien", rag_port=StubRagPort())
        assert out.get("error") is None
        assert out["rag_used"] is False
        assert out["recommandations"]


def _chain_s1_s5(question: str) -> tuple[dict, dict, dict]:
    intent = S1Pipeline(YAML_PATH).run(question)["intent"]
    s2 = S2Pipeline(YAML_PATH).run(intent)
    assert s2.get("error") is None and s2["df_propre"] is not None
    s3 = S3Pipeline(YAML_PATH).run(intent, s2["df_propre"])
    assert s3.get("error") is None
    s5 = S5Pipeline(YAML_PATH).run(intent, s3, {"descriptions_tabulaires": "", "tables": [], "graphs": []})
    assert s5.get("error") is None
    return intent, s3, s5


try:
    from tests.conftest import OLLAMA_REQUIRED
except ImportError:
    OLLAMA_REQUIRED = pytest.mark.skip(reason="conftest tests/ manquant")


@OLLAMA_REQUIRED
class TestS6ChainLisi:
    def test_chain_s1_s6_coherent_avec_s3(self) -> None:
        intent, s3, s5 = _chain_s1_s5(QUESTION_COMPARAISON)
        s6 = S6Pipeline(YAML_PATH).run(intent, s3, s5, profile="technicien", rag_port=StubRagPort())
        assert s6.get("error") is None
        assert s6["recommandations"]
        text = (s6["synthese_action"] + " ".join(r["action"] for r in s6["recommandations"])).lower()
        has_signal = (
            "p1" in text
            or "cpk" in text
            or "immédiat" in text
            or "significatif" in text
            or "surveillance" in text
        )
        assert has_signal
        cpk_vals = [
            r["result"]["Cpk"]
            for r in s3["specialist_results"]
            if r.get("agent") == "cp_cpk"
            and r.get("status") == "success"
            and r.get("result", {}).get("Cpk") is not None
        ]
        if cpk_vals and min(float(v) for v in cpk_vals) < 1.0:
            assert any(r["priorite"] == "P1" for r in s6["recommandations"])
