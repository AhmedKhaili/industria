"""
P1 — descriptive, normality, distribution_fit (LISI réel + unitaires).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from systems.s1.client_context import ClientContext
from systems.s2.pipeline import S2Pipeline
from systems.s3 import dispatcher
from systems.s3.pipeline import S3Pipeline
from systems.s5 import prep
from specialists.distribution_fit import DistributionFitSpecialist

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"
TARGET = "CR90_INTRADOS_FORME"

REQUIRED_DESCRIPTIVE = {
    "colonne",
    "n",
    "moyenne",
    "mediane",
    "ecart_type",
    "variance",
    "skewness",
    "kurtosis",
    "min",
    "max",
    "q1",
    "q3",
    "iqr",
    "pct_hors_lti_lts",
    "centrage",
    "lti",
    "lts",
    "nominal",
}


@pytest.fixture(scope="module")
def s3_pipeline() -> S3Pipeline:
    return S3Pipeline(YAML_PATH)


def _lisi_equator_intent(*, intention: str = "portrait_statistique") -> dict:
    return {
        "intention": intention,
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": [TARGET],
        "group_by": None,
        "filtres": {"piece": "M2L1A1C", "operation": "EQUATOR"},
    }


def _run_s2(intent: dict) -> pd.DataFrame:
    s2 = S2Pipeline(YAML_PATH).run(intent)
    assert s2.get("error") is None, s2
    df = s2["df_propre"]
    assert df is not None and not df.empty
    return df


class TestPortraitDispatch:
    def test_portrait_statistique_lists_portrait_agents(self) -> None:
        disp = dispatcher.dispatch({"intention": "portrait_statistique"})
        assert disp["specialists"] == ["descriptive", "normality", "distribution_fit"]

    def test_analyse_complete_portrait_then_correlation(self) -> None:
        disp = dispatcher.dispatch({"intention": "analyse_complete"})
        assert disp["specialists"] == [
            "descriptive",
            "normality",
            "distribution_fit",
            "correlation",
        ]


class TestPortraitLisi:
    def test_descriptive_cr90_all_fields_and_n_coherent(
        self, s3_pipeline: S3Pipeline
    ) -> None:
        intent = _lisi_equator_intent()
        df = _run_s2(intent)
        n_s2 = int(df[TARGET].dropna().shape[0])

        out = s3_pipeline.run(intent, df)
        assert out.get("error") is None, out

        desc = next(
            r
            for r in out["specialist_results"]
            if r.get("agent") == "descriptive" and r.get("status") == "success"
        )
        p = desc["result"]
        assert REQUIRED_DESCRIPTIVE <= set(p.keys())
        assert p["colonne"] == TARGET
        assert p["n"] == n_s2
        assert p["lti"] is not None and p["lts"] is not None

    def test_normality_verdict_matches_test_source(
        self, s3_pipeline: S3Pipeline
    ) -> None:
        intent = _lisi_equator_intent()
        df = _run_s2(intent)
        out = s3_pipeline.run(intent, df)
        norm = next(
            r
            for r in out["specialist_results"]
            if r.get("agent") == "normality" and r.get("status") == "success"
        )
        p = norm["result"]
        n = p["n"]
        assert p["verdict_normalite"] in ("normale", "non_normale")
        if n < 5000:
            assert p["test_verdict_source"] == "shapiro"
            assert p["shapiro_p"] is not None
            expected = "normale" if p["shapiro_p"] >= 0.05 else "non_normale"
            assert p["verdict_normalite"] == expected
        else:
            assert p["test_verdict_source"] == "anderson_darling"
            assert p["ad_stat"] is not None
            expected = "non_normale" if p["ad_significatif"] else "normale"
            assert p["verdict_normalite"] == expected

    def test_distribution_fit_loi_retenue_is_argmin_aic(
        self, s3_pipeline: S3Pipeline
    ) -> None:
        intent = _lisi_equator_intent()
        df = _run_s2(intent)
        out = s3_pipeline.run(intent, df)
        fit = next(
            r
            for r in out["specialist_results"]
            if r.get("agent") == "distribution_fit" and r.get("status") == "success"
        )
        p = fit["result"]
        assert p["loi_retenue"]
        assert p["loi_candidate_aic"] == p["loi_retenue"]
        valides = [
            row for row in p["ranking"] if row.get("ajustement_ok") and row.get("aic") is not None
        ]
        best_aic = min(float(row["aic"]) for row in valides)
        assert float(p["aic_min"]) == pytest.approx(best_aic)
        assert p["loi_retenue"] == min(valides, key=lambda x: float(x["aic"]))["loi"]


class TestDistributionFitUnit:
    def test_loi_retenue_equals_argmin_aic_synthetic(self) -> None:
        rng = np.random.default_rng(7)
        values = rng.lognormal(mean=0.0, sigma=0.35, size=120)
        df = pd.DataFrame({"x": values})
        raw = DistributionFitSpecialist().run(
            df, {"target_column": "x"}, {"target_column": "x"}
        )
        assert raw["status"] == "success"
        p = raw["result"]
        assert p["loi_retenue"]
        valides = [r for r in p["ranking"] if r.get("ajustement_ok") and r.get("aic")]
        assert p["loi_retenue"] == min(valides, key=lambda r: r["aic"])["loi"]


class TestPortraitFallbacks:
    def test_fallback_text_forbidden_phrases(self) -> None:
        desc = {
            "agent": "descriptive",
            "status": "success",
            "result": {
                "colonne": TARGET,
                "n": 200,
                "moyenne": 0.05,
                "mediane": 0.04,
                "ecart_type": 0.02,
                "pct_hors_lti_lts": 1.0,
                "centrage": 0.1,
                "interpretation_dispersion": "σ=0.02",
            },
        }
        norm = {
            "agent": "normality",
            "status": "success",
            "result": {
                "colonne": TARGET,
                "n": 200,
                "verdict_normalite": "normale",
                "normalite_phrase": "compatible avec une loi normale (Shapiro-Wilk, p = 0,120)",
                "test_utilise": "Shapiro-Wilk",
            },
        }
        fit = {
            "agent": "distribution_fit",
            "status": "success",
            "result": {
                "colonne": TARGET,
                "loi_retenue": "weibull",
                "loi_candidate_aic": "weibull",
                "aic_min": 412.5,
                "interpretation_loi": (
                    "Meilleur ajustement parmi les lois testées : weibull (AIC = 412.5)"
                ),
            },
        }
        texts = [
            prep.enriched_descriptive_interpretation(desc),
            prep.enriched_normality_interpretation(norm),
            prep.enriched_distribution_fit_interpretation(fit),
            prep.python_fallback_interpretation(desc),
            prep.python_fallback_interpretation(norm),
            prep.python_fallback_interpretation(fit),
        ]
        combined = " ".join(texts).lower()
        assert "loi probable" not in combined
        assert "causent" not in combined
        assert "ref_matrice" not in combined
        assert "meilleur ajustement" in combined
