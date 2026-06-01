"""
Tests P6 Phase 2a — group_descriptive (niveau mesure).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s3 import group_descriptive

YAML_PATH = str(
    Path(__file__).resolve().parents[3] / "configs/lisi_aerospace/client_config.yaml"
)


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def _df_three_groups() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CR70_INTRADOS_FORME": [
                0.08,
                0.09,
                0.10,
                0.11,
                0.28,
                0.30,
                0.05,
                0.06,
            ],
            "Ref_Matrice": [
                "BONNE",
                "BONNE",
                "BONNE",
                "BONNE",
                "MAUVAISE",
                "MAUVAISE",
                "MOYENNE",
                "MOYENNE",
            ],
        }
    )


def test_descriptive_stats_per_group(ctx: ClientContext) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    block = group_descriptive.compute_for_variable(
        _df_three_groups(), intent, ctx, "CR70_INTRADOS_FORME"
    )
    assert block is not None
    assert block["level"] == "measure"
    assert block["group_by"] == "Ref_Matrice"
    bonne = next(r for r in block["rows"] if r["group_value"] == "BONNE")
    assert bonne["n"] == 4
    assert bonne["mean"] is not None
    assert bonne["median"] is not None
    assert bonne["q1"] is not None
    assert bonne["q3"] is not None
    assert bonne["iqr"] == pytest.approx(bonne["q3"] - bonne["q1"])


def test_out_of_tolerance_rate(ctx: ClientContext) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    block = group_descriptive.compute_for_variable(
        _df_three_groups(), intent, ctx, "CR70_INTRADOS_FORME"
    )
    assert block is not None
    mauvaise = next(r for r in block["rows"] if r["group_value"] == "MAUVAISE")
    bonne = next(r for r in block["rows"] if r["group_value"] == "BONNE")
    assert mauvaise["out_of_tolerance_count"] == 2
    assert mauvaise["out_of_tolerance_rate"] == 100.0
    assert bonne["out_of_tolerance_count"] == 0
    assert bonne["out_of_tolerance_rate"] == 0.0


def test_ranking_by_out_of_tolerance(ctx: ClientContext) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    block = group_descriptive.compute_for_variable(
        _df_three_groups(), intent, ctx, "CR70_INTRADOS_FORME"
    )
    assert block is not None
    assert block["worst_group"] == "MAUVAISE"
    # Égalité 0 % hors tol : MOYENNE plus éloignée de LTS → moins critique (worse_direction upper).
    assert block["best_group"] == "MOYENNE"
    assert block["ranking_method"] == group_descriptive.RANKING_METHOD_ID


def test_tie_break_by_cpk() -> None:
    rows = [
        {
            "group_value": "A",
            "out_of_tolerance_rate": 10.0,
            "cpk": 1.5,
            "risk_to_limit_score": 0.01,
        },
        {
            "group_value": "B",
            "out_of_tolerance_rate": 10.0,
            "cpk": 0.4,
            "risk_to_limit_score": 0.01,
        },
    ]
    ranked = group_descriptive.assign_ranks_and_labels(rows)
    assert ranked[0]["group_value"] == "B"
    assert ranked[0]["rank"] == 1


def test_risk_to_limit_score_upper_three_tiers() -> None:
    """upper : au-dessus LTS > proche LTS (conforme) > éloigné de LTS."""
    lti, lts = 0.0, 0.2
    mean_proche = 0.19  # conforme, proche de LTS
    mean_loin = 0.05
    mean_au_dessus = 0.25

    score_proche = group_descriptive.risk_to_limit_score(
        mean_proche, lti, lts, "upper"
    )
    score_loin = group_descriptive.risk_to_limit_score(mean_loin, lti, lts, "upper")
    score_au_dessus = group_descriptive.risk_to_limit_score(
        mean_au_dessus, lti, lts, "upper"
    )

    assert score_au_dessus > score_proche > score_loin

    rows = [
        {
            "group_value": "LOIN",
            "out_of_tolerance_rate": 0.0,
            "cpk": None,
            "risk_to_limit_score": score_loin,
        },
        {
            "group_value": "PROCHE_LTS",
            "out_of_tolerance_rate": 0.0,
            "cpk": None,
            "risk_to_limit_score": score_proche,
        },
        {
            "group_value": "AU_DESSUS_LTS",
            "out_of_tolerance_rate": 0.0,
            "cpk": None,
            "risk_to_limit_score": score_au_dessus,
        },
    ]
    ranked = group_descriptive.assign_ranks_and_labels(rows)
    assert [r["group_value"] for r in ranked] == [
        "AU_DESSUS_LTS",
        "PROCHE_LTS",
        "LOIN",
    ]


def test_tie_break_risk_lower() -> None:
    lti, lts = 0.0, 0.2
    near = group_descriptive.risk_to_limit_score(0.01, lti, lts, "lower")
    far = group_descriptive.risk_to_limit_score(0.15, lti, lts, "lower")
    below = group_descriptive.risk_to_limit_score(-0.02, lti, lts, "lower")
    assert near > far
    assert below > near


def test_warning_if_n_below_6(ctx: ClientContext) -> None:
    df = pd.DataFrame(
        {
            "CR70_INTRADOS_FORME": [0.08, 0.09, 0.28],
            "Ref_Matrice": ["A", "A", "B"],
        }
    )
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    block = group_descriptive.compute_for_variable(
        df, intent, ctx, "CR70_INTRADOS_FORME"
    )
    assert block is not None
    for row in block["rows"]:
        if row["n"] < 6:
            assert any("effectif_faible" in w for w in row["warnings"])


def test_cpk_skipped_if_n_below_30(ctx: ClientContext) -> None:
    df = pd.DataFrame(
        {
            "CR70_INTRADOS_FORME": [0.08] * 10 + [0.28] * 10,
            "Ref_Matrice": ["A"] * 10 + ["B"] * 10,
        }
    )
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    block = group_descriptive.compute_for_variable(
        df, intent, ctx, "CR70_INTRADOS_FORME"
    )
    assert block is not None
    for row in block["rows"]:
        assert row["cpk"] is None
        assert any("n<30" in w for w in row["warnings"])


def test_ci95_mean_bounds_ordered(ctx: ClientContext) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    block = group_descriptive.compute_for_variable(
        _df_three_groups(), intent, ctx, "CR70_INTRADOS_FORME"
    )
    assert block is not None
    for row in block["rows"]:
        ci = row.get("ci95_mean")
        if ci:
            assert ci["low"] <= ci["high"]


def test_no_run_without_group_by(ctx: ClientContext) -> None:
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    assert not group_descriptive.should_run(intent)
    assert group_descriptive.compute_all(_df_three_groups(), intent, ctx) == []


def test_should_run_with_f2_family() -> None:
    intent = {"group_by": "Ref_Matrice", "intention": "autre"}
    families = [{"family_id": "bivariate_quali_quanti"}]
    assert group_descriptive.should_run(intent, families)


def test_infer_worse_direction_upper() -> None:
    assert group_descriptive.infer_worse_direction(0.0, 0.2, 0.0) == "upper"
    assert group_descriptive.infer_worse_direction(0.0, 0.2, 0.18) == "upper"


def test_pipeline_exposes_group_descriptive(ctx: ClientContext) -> None:
    from systems.s3.pipeline import S3Pipeline

    df = _df_three_groups()
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
        "variables": ["CR70_INTRADOS_FORME"],
        "intention": "comparaison_groupes",
    }
    pipe = S3Pipeline(YAML_PATH)
    out = pipe.run(intent, df)
    assert out.get("error") is None
    gd = out.get("group_descriptive") or []
    assert gd
    assert gd[0]["level"] == "measure"
