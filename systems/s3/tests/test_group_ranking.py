"""
Tests S3 — classement pire matrice (point B).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s3 import group_ranking

YAML_PATH = str(Path(__file__).resolve().parents[3] / "configs/lisi_aerospace/client_config.yaml")


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


def test_pire_groupe_plus_hors_tolerance(ctx: ClientContext) -> None:
    # LTI/LTS M2L1A1C EQUATOR CR70 typiques ~ 0 / 0.2 mm : valeurs hors tol pour MAUVAISE seulement
    df = pd.DataFrame(
        {
            "CR70_INTRADOS_FORME": [0.08, 0.09, 0.28, 0.30, 0.10, 0.11],
            "Ref_Matrice": ["BONNE", "BONNE", "MAUVAISE", "MAUVAISE", "MOYENNE", "MOYENNE"],
        }
    )
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
    }
    specialist_results = [
        {
            "agent": "cp_cpk",
            "status": "success",
            "result": {
                "colonne": "CR70_INTRADOS_FORME",
                "Cpk": 0.75,
                "conforme_EN9100": False,
            },
        },
        {
            "agent": "cp_cpk",
            "status": "success",
            "result": {
                "colonne": "CR10_INTRADOS_FORME",
                "Cpk": 1.1,
                "conforme_EN9100": False,
            },
        },
    ]
    out = group_ranking.compute_worst_group(df, intent, ctx, specialist_results)
    assert out.get("variable_pivot") == "CR70_INTRADOS_FORME"
    assert out.get("pire_groupe") == "MAUVAISE"
    assert out["pire_groupe_pct_hors_tolerance"] >= out["classement_groupes"][1][
        "pct_hors_tolerance"
    ]


def test_s6_a1_nomme_pire_matiere(ctx: ClientContext) -> None:
    from systems.s6.agents import a1_dispatcher

    ranking = {
        "pire_groupe": "O5220911B2-0",
        "variable_pivot": "CR70_INTRADOS_FORME",
        "cpk_pivot": 0.75,
        "pire_groupe_pct_hors_tolerance": 35.0,
    }
    intent = {"piece": "M2L1A1C", "operation": "EQUATOR", "group_by": "Ref_Matrice"}
    out = a1_dispatcher.run([], intent, ctx, "technicien", group_ranking=ranking)
    assert out.get("error") is None
    p1 = [i for i in out["items"] if i["priorite"] == "P1"]
    assert p1
    assert "O5220911B2-0" in p1[0]["justification"]
