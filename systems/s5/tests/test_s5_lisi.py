"""
Tests S5 — interprétation métier (LISI + unitaires).
"""

from __future__ import annotations

import pytest

from systems.s1.client_context import ClientContext
from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s4.pipeline import S4Pipeline
from systems.s5 import llm_client, prep
from systems.s5.agents import r1_interpreter, r2_verifier, r7_checker
from systems.s5.pipeline import S5Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def _chain_s3_s4(question: str) -> tuple[dict, dict, dict]:
    s1 = S1Pipeline(YAML_PATH)
    intent = s1.run(question)["intent"]
    s2 = S2Pipeline(YAML_PATH).run(intent)
    df = s2["df_propre"]
    s3 = S3Pipeline(YAML_PATH).run(intent, df)
    s4 = S4Pipeline(YAML_PATH).run(intent, df, s3)
    return intent, s3, s4


class TestS5Fidelity:
    def test_r2_reject_faux_chiffre(self) -> None:
        result = {
            "agent": "cp_cpk",
            "status": "success",
            "result": {"Cpk": 1.2, "Cp": 1.1, "colonne": "CR1", "conforme_EN9100": False},
        }
        interpretations = [
            {
                "specialist": "cp_cpk",
                "texte": "Le Cpk est de 9.99, donc non conforme.",
                "statut": "pending",
                "source_result": result,
            }
        ]
        out = r2_verifier.run(interpretations)
        assert out.get("error") is None
        assert out["interpretations"][0]["statut"] == "reject"
        assert "motif_reject" in out["interpretations"][0]
        if out["interpretations"][0]["statut"] == "fallback":
            assert "1.2" in out["interpretations"][0]["texte"] or "non conforme" in out[
                "interpretations"
            ][0]["texte"].lower()


class TestS5Profile:
    def test_profil_operateur_forbidden_and_tokens(self, ctx: ClientContext) -> None:
        long_text = (
            "La qualité est stable avec un z-score élevé et une ANOVA significative. "
            * 30
        )
        out = r7_checker.run(long_text, ctx, "operateur")
        assert out.get("error") is None
        synth = out["synthese"].lower()
        assert "z-score" not in synth
        assert "anova" not in synth
        assert len(synth.split()) <= int(ctx.profils["operateur"]["tokens_max"] * 1.5)


class TestS5Fallback:
    def test_fallback_llm_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_client, "chat", lambda *a, **k: None)
        result = {
            "agent": "cp_cpk",
            "status": "success",
            "result": {
                "Cpk": 0.9,
                "Cp": 1.0,
                "colonne": "CR1",
                "conforme_EN9100": False,
                "interpretation_Cpk": "Non capable",
            },
        }
        out = r1_interpreter.run([result])
        assert out.get("error") is None
        assert out["interpretations"][0]["statut"] == "fallback"
        assert "non conforme" in out["interpretations"][0]["texte"].lower()


class TestS5PipelineLisi:
    def test_conformite_cpk_non_conforme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_chat(prompt: str, **kwargs: object) -> str:
            if "Synthèse" in prompt or "Synthèse :" in prompt:
                return (
                    "Les mesures indiquent un Cpk de 1.12, sous le seuil EN9100 : "
                    "situation non conforme pour cette pièce."
                )
            return (
                "Pour la variable analysée, le Cpk est de 1.12, ce qui est non conforme "
                "au seuil EN9100 de 1,33."
            )

        monkeypatch.setattr(llm_client, "chat", mock_chat)

        intent, s3, s4 = _chain_s3_s4(
            "Les pieces M2L1A1C sont-elles conformes au filage ?"
        )
        s5 = S5Pipeline(YAML_PATH).run(intent, s3, s4, profile="technicien")
        assert s5.get("error") is None
        full_text = s5["synthese"].lower() + " ".join(
            i["texte"].lower() for i in s5["interpretations"]
        )
        assert "non conforme" in full_text or "1.12" in full_text or "1,12" in full_text

    def test_comparaison_anova_significatif(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_chat(prompt: str, **kwargs: object) -> str:
            if "Synthèse" in prompt:
                return (
                    "La comparaison entre matrices montre une différence significative "
                    "(p = 0.02) sur la forme intrados."
                )
            if "anova" in prompt.lower() or "Méthode" in prompt:
                return (
                    "La comparaison de groupes révèle une différence significative "
                    "entre les matrices (p = 0.02)."
                )
            return "Analyse conforme aux données fournies."

        monkeypatch.setattr(llm_client, "chat", mock_chat)

        intent, s3, s4 = _chain_s3_s4(
            "Compare la forme intrados de M2L1A1C entre les matrices"
        )
        s5 = S5Pipeline(YAML_PATH).run(intent, s3, s4, profile="ingenieur")
        assert s5.get("error") is None
        assert s5.get("synthese")
        combined = (s5["synthese"] + " " + " ".join(i["texte"] for i in s5["interpretations"])).lower()
        assert "significatif" in combined or "différence" in combined or "0.02" in combined
