"""
Tests S2 Phase I2b — niveaux de retaille (virgule décimale française).
"""

from __future__ import annotations

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s2 import cleaner

LISI_YAML = "configs/lisi_aerospace/client_config.yaml"


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(LISI_YAML)


def _df_retaille(values: list) -> pd.DataFrame:
    n = len(values)
    return pd.DataFrame(
        {
            "PAS_E_Niveau_Retaille": values,
            "PAS_I_Niveau_Retaille": values,
            "PAS_E_Numero_Passage": ["P1"] * n,
            "PAS_I_Numero_Passage": ["P1"] * n,
            "Tag": ["CR1"] * n,
            "Value": [1.0] * n,
        }
    )


class TestCleanerRetailleLocale:
    def test_parse_numeric_locale_french_comma(self) -> None:
        s = pd.Series(["-18,5", "2,5", "-5"])
        parsed = cleaner._parse_numeric_locale(s)
        assert parsed.iloc[0] == pytest.approx(-18.5)
        assert parsed.iloc[1] == pytest.approx(2.5)
        assert parsed.iloc[2] == pytest.approx(-5.0)

    def test_retaille_le_zero_conserved(self, ctx: ClientContext) -> None:
        cases = ["-18,5", "-5", "0", "2,5", "1"]
        res = cleaner.run(_df_retaille(cases), ctx)
        assert res.get("error") is None
        kept = res["df"]["PAS_E_Niveau_Retaille"].astype(str).tolist()
        assert "-18,5" in kept
        assert "0" in kept or 0 in res["df"]["PAS_E_Niveau_Retaille"].tolist()
        assert "2,5" not in kept
        assert "1" not in kept
        assert len(res["df_anomalies"]) >= 2

    def test_retaille_positive_and_invalid_to_anomalies(self, ctx: ClientContext) -> None:
        res = cleaner.run(_df_retaille(["1", "abc", "2,5"]), ctx)
        assert res.get("error") is None
        assert set(res["df_anomalies"]["PAS_E_Niveau_Retaille"].astype(str)) >= {
            "1",
            "abc",
            "2,5",
        }
        assert len(res["df"]) == 0

    def test_retaille_empty_row_kept(self, ctx: ClientContext) -> None:
        res = cleaner.run(_df_retaille(["", "-18,5"]), ctx)
        assert res.get("error") is None
        assert len(res["df"]) == 2
        assert "" in res["df"]["PAS_E_Niveau_Retaille"].astype(str).tolist()

    def test_passage_p1_p2_rule_still_applied(self, ctx: ClientContext) -> None:
        df = pd.DataFrame(
            {
                "PAS_E_Niveau_Retaille": ["-18,5", "-18,5"],
                "PAS_I_Niveau_Retaille": ["-18,5", "-18,5"],
                "PAS_E_Numero_Passage": ["P1", "P3"],
                "PAS_I_Numero_Passage": ["P1", "P1"],
                "Tag": ["CR1", "CR1"],
                "Value": [1.0, 2.0],
            }
        )
        res = cleaner.run(df, ctx)
        assert res.get("error") is None
        assert len(res["df"]) == 1
        assert res["df"].iloc[0]["PAS_E_Numero_Passage"] == "P1"
        assert res["cleaning_stats"]["rules"]["PAS_E_Numero_Passage"]["status"] == "applied"

    def test_existing_float_retaille_rule(self, ctx: ClientContext) -> None:
        """Régression test_s2 — floats avec point décimal."""
        df = pd.DataFrame(
            {
                "PAS_E_Niveau_Retaille": [0.0, -1.0, 2.5, 0.0],
                "PAS_I_Niveau_Retaille": [0.0, 0.0, 0.0, 3.0],
                "PAS_E_Numero_Passage": ["P1", "P2", "P1", "P1"],
                "PAS_I_Numero_Passage": ["P1", "P2", "P3", "P1"],
                "Tag": ["CR1"] * 4,
                "Value": [1.0, 2.0, 3.0, 4.0],
            }
        )
        res = cleaner.run(df, ctx)
        assert res.get("error") is None
        assert len(res["df"]) < len(df)
        assert len(res["df_anomalies"]) > 0
