"""
P0 — corrélation branchée sous analyse_complete, données LISI réelles.
"""

from __future__ import annotations

import pytest

from systems.s1.client_context import ClientContext
from systems.s2.pipeline import S2Pipeline
from systems.s3 import dispatcher
from systems.s3.pipeline import S3Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"

FORME_VARS = [
    "CR90_INTRADOS_FORME",
    "CR70_INTRADOS_FORME",
    "CR90_INTRADOS_VRILLAGE",
]


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


@pytest.fixture(scope="module")
def s3_pipeline() -> S3Pipeline:
    return S3Pipeline(YAML_PATH)


def test_dispatch_analyse_complete_portrait_then_correlation() -> None:
    disp = dispatcher.dispatch({"intention": "analyse_complete"})
    assert disp.get("error") is None
    assert disp["specialists"] == [
        "descriptive",
        "normality",
        "distribution_fit",
        "correlation",
        "cp_cpk",
    ]


class TestS3CorrelationLisi:
    def test_analyse_complete_correlation_on_real_lisi(
        self, s3_pipeline: S3Pipeline
    ) -> None:
        intent = {
            "intention": "analyse_complete",
            "piece": "M2L1A1C",
            "operation": "EQUATOR",
            "variables": FORME_VARS,
            "group_by": None,
            "filtres": {"piece": "M2L1A1C", "operation": "EQUATOR"},
        }
        s2 = S2Pipeline(YAML_PATH).run(intent)
        assert s2.get("error") is None, s2
        df = s2["df_propre"]
        assert df is not None and not df.empty

        result = s3_pipeline.run(intent, df)
        assert result.get("error") is None, result

        corr_rows = [
            r
            for r in result["specialist_results"]
            if r.get("agent") == "correlation" and r.get("status") == "success"
        ]
        assert len(corr_rows) == len(FORME_VARS), (
            f"attendu {len(FORME_VARS)} corrélations, obtenu {len(corr_rows)}"
        )

        first = corr_rows[0]["result"]
        assert first.get("colonne_cible") in FORME_VARS
        assert first.get("correlations"), "liste correlations vide"
        assert first["correlations"][0].get("pearson_r") is not None
