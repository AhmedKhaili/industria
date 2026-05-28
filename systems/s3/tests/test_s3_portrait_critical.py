"""
Tests critiques P1 — portrait (descriptive, normality, distribution_fit).

Ne modifie pas le code prod : vérifie robustesse et contrats S3-extended.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s3 import executor
from systems.s5 import prep
from specialists.descriptive import DescriptiveSpecialist
from specialists.distribution_fit import DistributionFitSpecialist
from specialists.normality import NormalitySpecialist

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"

FORBIDDEN_FALLBACK = (
    "loi probable",
    "causent",
    "ref_matrice",
    "distribution probable",
)


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def _assert_not_runnable_portrait(row: dict, *, needle: str) -> None:
    """Pas de crash ; résultat vide ; statut skipped (spec) ou error (validation BaseSpecialist)."""
    assert row.get("status") in ("skipped", "error")
    payload = row.get("result") or {}
    assert "loi_retenue" not in payload
    assert payload.get("loi_retenue") is None
    combined = f"{row.get('error') or ''} {payload.get('reason') or ''}".lower()
    assert needle in combined or row.get("status") == "skipped"


def _bimodal_series(n: int = 120, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    half = n // 2
    low = rng.normal(loc=0.0, scale=0.05, size=half)
    high = rng.normal(loc=1.5, scale=0.05, size=n - half)
    return np.concatenate([low, high])


class TestPortraitCriticalPreGates:
    def test_distribution_fit_n_under_50_skipped_no_loi_retenue(
        self, ctx: ClientContext
    ) -> None:
        df = pd.DataFrame({"mesure": np.linspace(0.0, 1.0, 30)})
        intent = {
            "intention": "portrait_statistique",
            "piece": "M2L1A1C",
            "operation": "EQUATOR",
            "variables": ["mesure"],
            "filtres": {},
        }
        out = executor.run_all(df, intent, ctx, ["distribution_fit"])
        assert out.get("error") is None
        row = out["specialist_results"][0]
        _assert_not_runnable_portrait(row, needle="50")

        direct = DistributionFitSpecialist().run(
            df, {"target_column": "mesure"}, {"target_column": "mesure"}
        )
        assert direct["status"] in ("skipped", "error")
        assert (direct.get("result") or {}).get("loi_retenue") is None

    def test_normality_n_under_8_skipped_no_crash(self, ctx: ClientContext) -> None:
        df = pd.DataFrame({"mesure": np.linspace(0.0, 1.0, 7)})
        intent = {
            "intention": "portrait_statistique",
            "variables": ["mesure"],
            "filtres": {},
        }
        out = executor.run_all(df, intent, ctx, ["normality"])
        assert out.get("error") is None
        row = out["specialist_results"][0]
        assert row.get("status") in ("skipped", "error")
        assert row.get("agent") == "normality"

        direct = NormalitySpecialist().run(
            df, {"target_column": "mesure"}, {"target_column": "mesure"}
        )
        assert direct["status"] in ("skipped", "error")
        assert (direct.get("result") or {}).get("verdict_normalite") is None


class TestPortraitCriticalTolerances:
    def test_descriptive_without_lti_lts_null_pct_and_centrage(
        self, ctx: ClientContext
    ) -> None:
        """PAS_E FILAGE : pas de tolérances YAML (cf. test_s3 pre-gate cp_cpk)."""
        n = 50
        df = pd.DataFrame({"PAS_E": np.linspace(1.0, 2.0, n)})
        intent = {
            "intention": "portrait_statistique",
            "piece": "M2L1A1C",
            "operation": "FILAGE",
            "variables": ["PAS_E"],
            "filtres": {"piece": "M2L1A1C", "operation": "FILAGE"},
        }
        out = executor.run_all(df, intent, ctx, ["descriptive"])
        assert out.get("error") is None
        row = out["specialist_results"][0]
        assert row["status"] == "success"
        p = row["result"]
        assert p["pct_hors_lti_lts"] is None
        assert p["centrage"] is None
        assert p["lti"] is None
        assert p["lts"] is None
        assert p["moyenne"] is not None

        direct = DescriptiveSpecialist().run(
            df, {"target_column": "PAS_E"}, {"target_column": "PAS_E"}
        )
        assert direct["status"] == "success"
        assert direct["result"]["pct_hors_lti_lts"] is None


class TestPortraitCriticalNonNormal:
    def test_bimodal_non_normal_verdict_and_loi_not_normale(self) -> None:
        values = _bimodal_series(120)
        df = pd.DataFrame({"mesure": values})

        norm = NormalitySpecialist().run(
            df, {"target_column": "mesure"}, {"target_column": "mesure"}
        )
        assert norm["status"] == "success"
        assert norm["result"]["verdict_normalite"] == "non_normale"

        fit = DistributionFitSpecialist().run(
            df, {"target_column": "mesure"}, {"target_column": "mesure"}
        )
        assert fit["status"] == "success"
        loi = fit["result"]["loi_retenue"]
        assert loi
        assert loi != "normale"


class TestPortraitCriticalFallbacks:
    @pytest.mark.parametrize(
        "agent,result_payload",
        [
            (
                "descriptive",
                {
                    "colonne": "CR90_INTRADOS_FORME",
                    "n": 200,
                    "moyenne": 0.05,
                    "mediane": 0.04,
                    "ecart_type": 0.02,
                    "interpretation_dispersion": "σ=0.02",
                },
            ),
            (
                "normality",
                {
                    "colonne": "CR90_INTRADOS_FORME",
                    "n": 200,
                    "verdict_normalite": "non_normale",
                    "normalite_phrase": (
                        "écart significatif à la normale (Shapiro-Wilk, p = 0,001)"
                    ),
                    "test_utilise": "Shapiro-Wilk",
                },
            ),
            (
                "distribution_fit",
                {
                    "colonne": "CR90_INTRADOS_FORME",
                    "loi_retenue": "weibull",
                    "loi_candidate_aic": "weibull",
                    "aic_min": 380.0,
                    "interpretation_loi": (
                        "Meilleur ajustement parmi les lois testées : weibull (AIC = 380.0)"
                    ),
                },
            ),
        ],
    )
    def test_fallback_python_forbidden_phrases(
        self, agent: str, result_payload: dict
    ) -> None:
        row = {"agent": agent, "status": "success", "result": result_payload}
        if agent == "descriptive":
            text = prep.enriched_descriptive_interpretation(row)
        elif agent == "normality":
            text = prep.enriched_normality_interpretation(row)
        else:
            text = prep.enriched_distribution_fit_interpretation(row)
        fb = prep.python_fallback_interpretation(row)
        combined = f"{text} {fb}".lower()
        for phrase in FORBIDDEN_FALLBACK:
            assert phrase not in combined, f"interdit trouvé : {phrase!r} dans {agent}"
