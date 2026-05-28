"""
Tests S5 — chemins critiques (Reject, timeout, profil, vide, chaînage LISI).
Ne remplace pas test_s5_lisi.py ; complète la couverture sans mock « tout passe ».
"""

from __future__ import annotations

import pytest

from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s4.pipeline import S4Pipeline
from systems.s5 import llm_client, prep
from systems.s5.agents import r1_interpreter, r2_verifier, r7_checker
from systems.s5.pipeline import S5Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"


class TestS5CriticalR2Reject:
    def test_r2_reject_cpk_plus_10_percent(self) -> None:
        """Chiffre LLM à +10% du Cpk réel → statut reject + motif_reject + texte Python brut."""
        cpk_real = 1.2
        cpk_faux = round(cpk_real * 1.10, 2)
        refs = prep.reference_numbers_for_result(
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {"Cpk": cpk_real, "Cp": 1.1, "colonne": "CR1"},
            }
        )
        status, rel = prep.verify_number_against_refs(cpk_faux, refs)
        assert status == "Reject"
        assert rel is not None and rel > 0.05

        result = {
            "agent": "cp_cpk",
            "status": "success",
            "result": {
                "Cpk": cpk_real,
                "Cp": 1.1,
                "colonne": "CR1",
                "conforme_EN9100": False,
                "interpretation_Cpk": "Non capable",
            },
        }
        interpretations = [
            {
                "specialist": "cp_cpk",
                "texte": f"Le processus affiche un Cpk de {cpk_faux}, donc non conforme.",
                "statut": "pending",
                "source_result": result,
            }
        ]
        out = r2_verifier.run(interpretations)
        assert out.get("error") is None
        item = out["interpretations"][0]
        assert item["statut"] == "reject"
        assert "motif_reject" in item
        motif = item["motif_reject"]
        assert motif["trouve"] == cpk_faux
        assert motif["attendu"] == cpk_real
        assert str(cpk_faux) not in item["texte"]
        assert str(cpk_real) in item["texte"]
        assert out["fidelite_score"] < 0.5


class TestS5CriticalFallbackTimeout:
    def test_fallback_apres_timeout_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_timeout(*_a: object, **_k: object) -> object:
            raise TimeoutError("ollama timeout")

        monkeypatch.setattr(llm_client.requests, "post", raise_timeout)

        result = {
            "agent": "cp_cpk",
            "status": "success",
            "result": {
                "Cpk": 0.85,
                "Cp": 1.0,
                "colonne": "CR1",
                "conforme_EN9100": False,
                "interpretation_Cpk": "Non capable",
            },
        }
        r1 = r1_interpreter.run([result])
        assert r1.get("error") is None
        assert r1["interpretations"][0]["statut"] == "fallback"
        assert "0.85" in r1["interpretations"][0]["texte"] or "non conforme" in r1[
            "interpretations"
        ][0]["texte"].lower()

        intent = {
            "intention": "conformite",
            "piece": "M2L1A1C",
            "operation": "FILAGE",
            "clarification_needed": False,
        }
        s3_out = {
            "specialist_results": [result],
            "metrics_summary": {},
            "warnings": [],
        }
        s4_out = {"descriptions_tabulaires": [], "tables": [], "graphs": [], "warnings": []}
        s5 = S5Pipeline(YAML_PATH).run(intent, s3_out, s4_out, profile="technicien")
        assert s5.get("error") is None
        assert len(s5["interpretations"]) >= 1
        assert any(
            it.get("statut") in ("fallback", "Accept")
            and (
                "conforme" in it.get("texte", "").lower()
                or "0.85" in it.get("texte", "")
                or "critique" in it.get("texte", "").lower()
            )
            for it in s5["interpretations"]
        )


class TestS5CriticalR7Forbidden:
    def test_r7_cpk_interdit_profil_operateur(self) -> None:
        from systems.s1.client_context import ClientContext

        ctx = ClientContext.load(YAML_PATH)
        synthese_avec_cpk = (
            "La production est stable. Le Cpk reste acceptable sur cette série."
        )
        out = r7_checker.run(synthese_avec_cpk, ctx, "operateur")
        assert out.get("error") is None
        assert len(out.get("warnings", [])) > 0
        assert "cpk" not in out["synthese"].lower()


class TestS5CriticalPipelineVide:
    def test_pipeline_descriptions_vides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_client, "chat", lambda *a, **k: "Synthèse indisponible.")

        intent = {
            "intention": "conformite",
            "piece": "M2L1A1C",
            "operation": "FILAGE",
            "clarification_needed": False,
            "variables": [],
        }
        s3_out = {"specialist_results": [], "metrics_summary": {}, "warnings": []}
        s4_out = {
            "descriptions_tabulaires": [],
            "tables": [],
            "graphs": [],
            "charts": [],
            "warnings": [],
        }
        s5 = S5Pipeline(YAML_PATH).run(intent, s3_out, s4_out, profile="technicien")
        assert s5.get("error") is None
        assert s5["interpretations"] == []


class TestS5CriticalChainLisi:
    def test_chain_s3_s4_s5_fidelite_sur_chiffres_lisi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s1 = S1Pipeline(YAML_PATH)
        intent = s1.run("Les pieces M2L1A1C sont-elles conformes au filage ?")["intent"]
        s2_out = S2Pipeline(YAML_PATH).run(intent)
        assert s2_out.get("error") is None
        s3_out = S3Pipeline(YAML_PATH).run(intent, s2_out["df_propre"])
        assert s3_out.get("error") is None
        s4_out = S4Pipeline(YAML_PATH).run(intent, s2_out["df_propre"], s3_out)
        assert s4_out.get("error") is None

        cpk_rows = [
            r
            for r in s3_out["specialist_results"]
            if prep.canonical_agent(r.get("agent")) == "cp_cpk"
            and r.get("status") == "success"
        ]
        assert cpk_rows, "Aucun Cp/Cpk LISI dans S3"

        def mock_chat_fidele(prompt: str, **kwargs: object) -> str:
            if "Synthèse" in prompt:
                parts = []
                for row in cpk_rows:
                    p = row.get("result") or {}
                    col = p.get("colonne", "mesure")
                    cpk = p.get("Cpk")
                    parts.append(f"{col} : Cpk = {cpk}.")
                return " ".join(parts) or "Synthèse conformité LISI."
            if "Cpk =" in prompt or "Cpk=" in prompt:
                for row in cpk_rows:
                    p = row.get("result") or {}
                    return (
                        f"Pour {p.get('colonne', 'la variable')}, le Cpk est de {p.get('Cpk')} "
                        f"(conforme EN9100 : {p.get('conforme_EN9100')})."
                    )
            return "Analyse alignée sur les données certifiées."

        monkeypatch.setattr(llm_client, "chat", mock_chat_fidele)

        s5 = S5Pipeline(YAML_PATH).run(intent, s3_out, s4_out, profile="technicien")
        assert s5.get("error") is None
        assert s5["fidelite_score"] >= 0.75
        assert s5["interpretations"]

        first_cpk = cpk_rows[0]["result"]["Cpk"]
        combined = s5["synthese"] + " ".join(i["texte"] for i in s5["interpretations"])
        assert str(first_cpk) in combined
