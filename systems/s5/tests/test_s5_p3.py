"""
P3 — R2 étendu portrait, phrases certifiées, mode agregee_python.
"""

from __future__ import annotations

import pytest

from systems.s1.client_context import ClientContext
from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s5 import llm_client, prep
from systems.s5.agents import r1_interpreter, r2_verifier, r6_synthesizer
from systems.s5.pipeline import S5Pipeline
from systems.stats_format import certified_normalite_phrase

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def _descriptive_result(moyenne: float = 0.098) -> dict:
    return {
        "agent": "descriptive",
        "status": "success",
        "result": {
            "colonne": "CR90_INTRADOS_FORME",
            "n": 200,
            "moyenne": moyenne,
            "mediane": 0.094,
            "ecart_type": 0.032,
            "variance": 0.001,
            "skewness": 1.24,
            "kurtosis": 0.5,
            "min": 0.01,
            "max": 0.2,
            "q1": 0.08,
            "q3": 0.11,
            "iqr": 0.03,
            "pct_hors_lti_lts": 2.0,
            "centrage": 0.1,
        },
    }


def _normality_result(verdict: str = "non_normale") -> dict:
    return {
        "agent": "normality",
        "status": "success",
        "result": {
            "colonne": "CR90_INTRADOS_FORME",
            "n": 200,
            "verdict_normalite": verdict,
            "test_utilise": "Shapiro-Wilk",
            "statistique": 0.98,
            "p_value": 0.001,
            "p_value_display": "p < 0,001",
            "normalite_phrase": certified_normalite_phrase(
                verdict, "Shapiro-Wilk", 0.98, 0.001
            ),
        },
    }


def _distribution_result(loi: str = "log_normale") -> dict:
    return {
        "agent": "distribution_fit",
        "status": "success",
        "result": {
            "colonne": "CR90_INTRADOS_FORME",
            "loi_retenue": loi,
            "loi_candidate_aic": loi,
            "aic_min": -234.5,
            "bic_min": -228.0,
        },
    }


class TestS5P3R2:
    def test_r2_reject_invented_mean_plus_10_percent(self) -> None:
        refs = prep.reference_numbers_for_result(_descriptive_result(0.098))
        faux = 0.15
        status, rel = prep.verify_number_against_refs(faux, refs)
        assert status == "Reject"
        assert rel is not None and rel > 0.05

        interpretations = [
            {
                "specialist": "descriptive",
                "texte": f"La moyenne observée est {faux} mm sur la cote.",
                "statut": "pending",
                "source_result": _descriptive_result(0.098),
            }
        ]
        out = r2_verifier.run(interpretations)
        assert out["interpretations"][0]["statut"] == "reject"
        assert "0,098" in out["interpretations"][0]["texte"] or "0.098" in out[
            "interpretations"
        ][0]["texte"]

    def test_r2_reject_wrong_loi(self) -> None:
        interpretations = [
            {
                "specialist": "distribution_fit",
                "texte": "La loi normale semble la mieux adaptée.",
                "statut": "pending",
                "source_result": _distribution_result("log_normale"),
            }
        ]
        out = r2_verifier.run(interpretations)
        assert out["interpretations"][0]["statut"] == "reject"

    def test_r2_reject_contradicts_normality_verdict(self) -> None:
        interpretations = [
            {
                "specialist": "normality",
                "texte": "La distribution est compatible avec une loi normale.",
                "statut": "pending",
                "source_result": _normality_result("non_normale"),
            }
        ]
        out = r2_verifier.run(interpretations)
        assert out["interpretations"][0]["statut"] == "reject"


class TestS5P3CertifiedPhrases:
    def test_fallback_normalite_zero_loi_probable(self) -> None:
        text = prep.enriched_normality_interpretation(_normality_result())
        assert "loi probable" not in text.lower()
        assert "non normale" in text.lower()


class TestS5P3MultiVariableWarning:
    def test_warning_when_more_than_three_variables(self, ctx: ClientContext) -> None:
        intent = {"variables": ["A", "B", "C", "D"]}
        msg = prep.multi_variable_duration_warning(intent, ctx)
        assert msg is not None
        assert "4 variables" in msg
        assert "plus de temps" in msg

    def test_no_warning_at_three_variables(self, ctx: ClientContext) -> None:
        intent = {"variables": ["A", "B", "C"]}
        assert prep.multi_variable_duration_warning(intent, ctx) is None

    def test_r1_still_calls_llm_with_many_variables(self, ctx: ClientContext) -> None:
        """Pas de bascule automatique — R1 tente le LLM (ici mocké)."""
        results = [_descriptive_result()] * 4
        intent = {"intention": "analyse_complete", "variables": ["A", "B", "C", "D"]}
        n_calls = 0

        def track_chat(prompt: str, **_k: object) -> str | None:
            nonlocal n_calls
            n_calls += 1
            return "Interprétation certifiée pour la mesure."

        original = llm_client.chat
        llm_client.chat = track_chat  # type: ignore[method-assign]
        try:
            out = r1_interpreter.run(results, intent, ctx)
        finally:
            llm_client.chat = original  # type: ignore[method-assign]

        assert n_calls == len(results)
        assert all(it.get("statut") == "pending" for it in out["interpretations"])

    def test_zero_llm_synthese_opt_in_only(self) -> None:
        ctx = ClientContext.load(YAML_PATH)
        ae = ctx.raw.setdefault("analyse_etendue", {})
        ss = dict(ae.get("synthese_s5", {}))
        ss["zero_llm_synthese"] = True
        ae["synthese_s5"] = ss
        results = [_descriptive_result()]
        out = r1_interpreter.run(results, {"variables": []}, ctx)
        assert out["interpretations"][0]["statut"] == "fallback"
        interp = [
            {
                "specialist": "descriptive",
                "texte": prep.enriched_descriptive_interpretation(_descriptive_result()),
                "statut": "fallback",
            }
        ]
        r6 = r6_synthesizer.run(interp, ctx, "technicien", {"piece": "M2L1A1C"}, [])
        assert r6.get("llm_used") is False
        assert "M2L1A1C" in r6["synthese"] or "Synthèse" in r6["synthese"]


class TestS5P3LisiChain:
    def test_portrait_chain_r2_on_lisi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Chaîne S1→S5 courte — R1 fallback + R2 accepte chiffres certifiés."""
        monkeypatch.setattr(llm_client, "chat", lambda *_a, **_k: None)

        question = "Analyse-moi CR90_INTRADOS_FORME sur M2L1A1C"
        intent = S1Pipeline(YAML_PATH).run(question)["intent"]
        assert intent["intention"] == "portrait_statistique"
        df = S2Pipeline(YAML_PATH).run(intent)["df_propre"]
        s3 = S3Pipeline(YAML_PATH).run(intent, df)
        s5 = S5Pipeline(YAML_PATH).run(intent, s3, {"descriptions": []})
        assert s5.get("error") is None
        assert s5["interpretations"]
        assert all(
            it.get("statut") in ("Accept", "fallback", "reject")
            for it in s5["interpretations"]
        )
        blob = " ".join(it.get("texte", "") for it in s5["interpretations"]).lower()
        assert "loi probable" not in blob
