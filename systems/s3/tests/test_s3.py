"""
Tests S3 — métriques sur données LISI réelles + pre-gates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3 import executor
from systems.s3.pipeline import S3Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


@pytest.fixture(scope="module")
def s3_pipeline() -> S3Pipeline:
    return S3Pipeline(YAML_PATH)


def _run_s1_s2(question: str) -> tuple[dict, pd.DataFrame]:
    s1 = S1Pipeline(YAML_PATH)
    intent = s1.run(question)["intent"]
    assert intent is not None
    s2 = S2Pipeline(YAML_PATH)
    s2_res = s2.run(intent)
    assert s2_res.get("error") is None, s2_res
    df = s2_res["df_propre"]
    assert df is not None and not df.empty
    return intent, df


class TestS3PipelineLisi:
    def test_conformite_cp_cpk(self, s3_pipeline: S3Pipeline) -> None:
        intent, df = _run_s1_s2(
            "Les pieces M2L1A1C sont-elles conformes au filage ?"
        )
        result = s3_pipeline.run(intent, df)
        assert result.get("error") is None
        cp_rows = [
            r
            for r in result["specialist_results"]
            if r.get("agent") == "cp_cpk" and r.get("status") == "success"
        ]
        assert cp_rows, "Aucun Cp/Cpk calculé"
        assert any(r.get("result", {}).get("Cpk") is not None for r in cp_rows)

    def test_comparaison_anova(self, s3_pipeline: S3Pipeline) -> None:
        intent, df = _run_s1_s2(
            "Compare la forme intrados de M2L1A1C entre les matrices"
        )
        assert intent.get("intention") == "comparaison_groupes"
        assert intent.get("operation") == "EQUATOR"
        result = s3_pipeline.run(intent, df)
        assert result.get("error") is None
        anova = next(
            (
                r
                for r in result["specialist_results"]
                if r.get("agent") == "anova_kruskal"
            ),
            None,
        )
        assert anova is not None
        assert anova["status"] in ("success", "error")
        if anova["status"] == "success":
            assert anova["result"].get("p_value") is not None
            assert anova["result"].get("methode_choisie")

    def test_tendance_mann_kendall(self, s3_pipeline: S3Pipeline) -> None:
        intent, df = _run_s1_s2("Tendance du vrillage de RD4L1A1C")
        assert intent.get("intention") == "tendance"
        result = s3_pipeline.run(intent, df)
        assert result.get("error") is None
        mk_rows = [
            r
            for r in result["specialist_results"]
            if r.get("agent") == "mann_kendall" and r.get("status") == "success"
        ]
        assert mk_rows, "Mann-Kendall non calculé"
        assert any(r.get("result", {}).get("p_value") is not None for r in mk_rows)


class TestS3PreGates:
    def test_pre_gate_n_under_10_skips_cp_cpk(self, ctx: ClientContext) -> None:
        df = pd.DataFrame({"CR1": np.linspace(57.0, 58.0, 8)})
        intent = {
            "intention": "conformite",
            "piece": "M2L1A1C",
            "operation": "FILAGE",
            "variables": ["CR1"],
            "group_by": None,
            "filtres": {"piece": "M2L1A1C", "operation": "FILAGE"},
        }
        res = executor.run_all(df, intent, ctx, ["cp_cpk"])
        cp = res["specialist_results"][0]
        assert cp["status"] == "skipped"
        assert "10" in cp["result"].get("reason", "")

    def test_pre_gate_no_lti_lts_skips_cp_cpk(self, ctx: ClientContext) -> None:
        df = pd.DataFrame({"PAS_E": np.linspace(1.0, 2.0, 50)})
        intent = {
            "intention": "conformite",
            "piece": "M2L1A1C",
            "operation": "FILAGE",
            "variables": ["PAS_E"],
            "group_by": None,
            "filtres": {"piece": "M2L1A1C", "operation": "FILAGE"},
        }
        res = executor.run_all(df, intent, ctx, ["cp_cpk"])
        cp = res["specialist_results"][0]
        assert cp["status"] == "skipped"
        assert "LTI" in cp["result"].get("reason", "")
