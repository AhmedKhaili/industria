"""
Tests E2E S1→S5 sur données LISI réelles — LLM Ollama sans mock.
Chaque test est indépendant (nouvelle instance de pipeline par exécution).
"""

from __future__ import annotations

import copy

import pytest

from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s4.pipeline import S4Pipeline
from systems.s5 import prep
from systems.s5.agents import r1_interpreter, r2_verifier
from systems.s5.pipeline import S5Pipeline
from tests.conftest import OLLAMA_REQUIRED, assert_no_forbidden_words

QUESTION_CONFORMITE = (
    "Quelle est la conformité de la forme intrados de M2L1A1C ?"
)
QUESTION_COMPARAISON = (
    "La matrice a-t-elle un impact sur la forme intrados de M2L1A1C ?"
)
QUESTION_VAGUE = "montre moi les données"


def _agents_present(s3_out: dict, agent: str) -> bool:
    target = agent.lower()
    return any(
        prep.canonical_agent(r.get("agent")) == target
        for r in s3_out.get("specialist_results") or []
    )


def _run_s1_s4(lisi_yaml_path: str, question: str) -> tuple[dict, dict, dict, dict]:
    s1_out = S1Pipeline(lisi_yaml_path).run(question)
    assert s1_out.get("error") is None, s1_out
    intent = s1_out["intent"]
    assert intent is not None

    s2_out = S2Pipeline(lisi_yaml_path).run(intent)
    assert s2_out.get("error") is None, s2_out
    df = s2_out["df_propre"]
    assert df is not None and not df.empty

    s3_out = S3Pipeline(lisi_yaml_path).run(intent, df)
    assert s3_out.get("error") is None, s3_out

    s4_out = S4Pipeline(lisi_yaml_path).run(intent, df, s3_out)
    assert s4_out.get("error") is None, s4_out

    return intent, s2_out, s3_out, s4_out


def _descriptions_non_vides(s4_out: dict) -> bool:
    raw = s4_out.get("descriptions_tabulaires", "")
    if isinstance(raw, str) and raw.strip():
        return True
    if isinstance(raw, list) and any(str(d).strip() for d in raw):
        return True
    return bool(s4_out.get("tables"))


def _inflate_cpk_in_s3(s3_out: dict, factor: float = 1.1) -> dict:
    tampered = copy.deepcopy(s3_out)
    for row in tampered.get("specialist_results") or []:
        if prep.canonical_agent(row.get("agent")) != "cp_cpk":
            continue
        if row.get("status") != "success":
            continue
        payload = row.get("result") or {}
        cpk = payload.get("Cpk")
        if isinstance(cpk, (int, float)):
            payload["Cpk"] = round(float(cpk) * factor, 6)
    return tampered


@OLLAMA_REQUIRED
class TestE2EConformite:
    def test_conformite_bout_en_bout(self, lisi_yaml_path: str) -> None:
        intent, _s2, s3, s4 = _run_s1_s4(lisi_yaml_path, QUESTION_CONFORMITE)
        assert intent["intention"] == "conformite"
        assert _agents_present(s3, "cp_cpk")
        assert _descriptions_non_vides(s4)

        s5 = S5Pipeline(lisi_yaml_path).run(intent, s3, s4, profile="technicien")
        assert s5.get("error") is None, s5
        assert s5.get("interpretations") is not None
        assert len(s5["interpretations"]) >= 1 or bool(s5.get("synthese"))


@OLLAMA_REQUIRED
class TestE2EComparaison:
    def test_comparaison_groupes_bout_en_bout(self, lisi_yaml_path: str) -> None:
        intent, _s2, s3, s4 = _run_s1_s4(lisi_yaml_path, QUESTION_COMPARAISON)
        assert intent["intention"] == "comparaison_groupes"
        assert _agents_present(s3, "anova_kruskal")

        s5 = S5Pipeline(lisi_yaml_path).run(intent, s3, s4, profile="technicien")
        assert s5.get("error") is None, s5
        combined = (s5.get("synthese") or "") + " ".join(
            i.get("texte", "") for i in s5.get("interpretations") or []
        )
        assert combined.strip()
        assert _descriptions_non_vides(s4)


@OLLAMA_REQUIRED
class TestE2EProfilOperateur:
    def test_forbidden_words_respectes(
        self, lisi_yaml_path: str, operateur_forbidden_words: list[str]
    ) -> None:
        """
        R7 filtre forbidden_words sur la synthèse finale (S5.md).
        Les interprétations spécialistes peuvent encore contenir du jargon technique.
        """
        intent, _s2, s3, s4 = _run_s1_s4(lisi_yaml_path, QUESTION_COMPARAISON)
        s5 = S5Pipeline(lisi_yaml_path).run(intent, s3, s4, profile="operateur")
        assert s5.get("error") is None, s5
        assert_no_forbidden_words(s5.get("synthese") or "", operateur_forbidden_words)


@OLLAMA_REQUIRED
class TestE2ERejectFidelite:
    def test_reject_detecte_sans_mock_llm(self, lisi_yaml_path: str) -> None:
        """
        Cpk gonflé (+10%) dans specialist_results pour R1 ; refs R2 = valeurs S3 réelles.
        Le LLM cite le Cpk du prompt ; R2 doit rejeter (traçabilité PHILOSOPHY §25).
        """
        intent, _s2, s3_true, s4 = _run_s1_s4(lisi_yaml_path, QUESTION_CONFORMITE)
        assert _agents_present(s3_true, "cp_cpk")

        s3_tampered = _inflate_cpk_in_s3(s3_true, factor=1.1)

        r1 = r1_interpreter.run(s3_tampered["specialist_results"])
        assert r1.get("error") is None, r1
        assert r1["interpretations"], "R1 doit produire au moins une interprétation"

        cpk_true_row = next(
            r
            for r in s3_true["specialist_results"]
            if prep.canonical_agent(r.get("agent")) == "cp_cpk"
            and r.get("status") == "success"
            and r.get("result", {}).get("Cpk") is not None
        )
        cpk_true = float(cpk_true_row["result"]["Cpk"])
        cpk_inflated = round(cpk_true * 1.1, 6)
        refs_true = prep.reference_numbers_for_result(cpk_true_row)
        assert prep.verify_number_against_refs(cpk_inflated, refs_true)[0] == "Reject"

        inflated_cited_pending = False
        for item in r1["interpretations"]:
            if item.get("specialist") != "cp_cpk":
                continue
            tampered_sr = item.get("source_result") or {}
            col = (tampered_sr.get("result") or {}).get("colonne")
            true_row = next(
                (
                    r
                    for r in s3_true["specialist_results"]
                    if prep.canonical_agent(r.get("agent")) == "cp_cpk"
                    and (r.get("result") or {}).get("colonne") == col
                ),
                cpk_true_row,
            )
            item["source_result"] = copy.deepcopy(true_row)
            if item.get("statut") != "pending":
                continue
            cpk_true_v = float(true_row["result"]["Cpk"])
            cpk_infl_v = round(cpk_true_v * 1.1, 6)
            tol = max(0.02, abs(cpk_infl_v) * 0.02)
            for num in prep.extract_numbers_from_text(item.get("texte", "")):
                if abs(num - cpk_infl_v) <= tol:
                    inflated_cited_pending = True
                    break

        r2 = r2_verifier.run(r1["interpretations"])
        assert r2.get("error") is None, r2
        cpk_rejects = [
            it
            for it in r2["interpretations"]
            if it.get("specialist") == "cp_cpk" and it.get("statut") == "reject"
        ]
        if inflated_cited_pending:
            assert cpk_rejects, (
                "R2 doit rejeter si le LLM cite le Cpk gonflé (+10%) du prompt"
            )
            assert all("motif_reject" in it for it in cpk_rejects)

        s5 = S5Pipeline(lisi_yaml_path).run(intent, s3_tampered, s4, profile="technicien")
        assert s5.get("error") is None, s5
        if cpk_rejects:
            assert any(
                "données brutes affichées" in w for w in s5.get("warnings", [])
            )


class TestE2EIntentVague:
    def test_clarification_arret_s1(self, lisi_yaml_path: str) -> None:
        s1_out = S1Pipeline(lisi_yaml_path).run(QUESTION_VAGUE)
        assert s1_out.get("error") is None, s1_out
        intent = s1_out["intent"]
        assert intent is not None
        assert intent.get("clarification_needed") is True
        assert s1_out.get("clarification") is not None
