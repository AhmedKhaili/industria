"""
Tests S2 — données LISI réelles + unitaires nettoyage.
"""

from __future__ import annotations

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s2 import cleaner, loader, partitioner
from systems.s2.loader import is_vague_intent
from systems.s2.pipeline import S2Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"


def _intent_m2l1a1c_filage(
    *,
    variables: list[str] | None = None,
    date_debut: str | None = None,
    date_fin: str | None = None,
) -> dict:
    filtres: dict = {"piece": "M2L1A1C", "operation": "FILAGE"}
    if date_debut:
        filtres["Date_debut"] = date_debut
    if date_fin:
        filtres["Date_fin"] = date_fin
    return {
        "intention": "conformite",
        "piece": "M2L1A1C",
        "operation": "FILAGE",
        "variables": variables or ["CR1", "CR2", "CR3"],
        "group_by": None,
        "filtres": filtres,
        "clarification_needed": False,
        "clarification_manque": [],
        "contexte_session": {},
    }


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(YAML_PATH)


@pytest.fixture(scope="module")
def s2_pipeline() -> S2Pipeline:
    pipe = S2Pipeline(YAML_PATH)
    part = partitioner.ensure_partitions(YAML_PATH, pipe.ctx)
    assert part.get("error") is None, part
    return pipe


class TestS2PipelineLisi:
    def test_intent_m2l1a1c_filage_columns(self, s2_pipeline: S2Pipeline) -> None:
        result = s2_pipeline.run(_intent_m2l1a1c_filage())
        assert result.get("error") is None
        assert result["clarification_needed"] is False
        df = result["df_propre"]
        assert df is not None
        assert not df.empty
        for tag in ("CR1", "CR2", "CR3"):
            assert tag in df.columns
        assert "Tag" not in df.columns
        assert "Designation Reference" in df.columns
        assert "M2L1A1C" in df["Designation Reference"].astype(str).unique()

    def test_variables_vides_yaml_ignorees(self, s2_pipeline: S2Pipeline) -> None:
        """PAS_E / PAS_I sans tolérances YAML — pas d'erreur de validation."""
        tags = s2_pipeline.ctx.get_tags_for("M2L1A1C", "FILAGE")
        result = s2_pipeline.run(_intent_m2l1a1c_filage(variables=tags))
        assert result.get("error") is None
        assert "PAS_E" in result["cleaning_stats"].get("colonnes_vides_ignorees", [])
        assert "PAS_I" in result["cleaning_stats"].get("colonnes_vides_ignorees", [])

    def test_pivot_one_column_per_tag(self, s2_pipeline: S2Pipeline) -> None:
        result = s2_pipeline.run(_intent_m2l1a1c_filage(variables=["CR1", "EP_BA"]))
        df = result["df_propre"]
        assert "CR1" in df.columns
        assert "EP_BA" in df.columns
        assert "Tag" not in df.columns
        assert "Value" not in df.columns

    def test_date_filter_applied(self, s2_pipeline: S2Pipeline) -> None:
        full = s2_pipeline.run(_intent_m2l1a1c_filage())
        df_full = full["df_propre"]
        col_date = s2_pipeline.ctx.colonnes.get("temps", "Date")
        mid = pd.to_datetime(df_full[col_date]).median()
        debut = (mid - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        fin = (mid + pd.Timedelta(days=7)).strftime("%Y-%m-%d")

        filtered = s2_pipeline.run(
            _intent_m2l1a1c_filage(date_debut=debut, date_fin=fin)
        )
        df_f = filtered["df_propre"]
        assert len(df_f) < len(df_full)
        dates = pd.to_datetime(df_f[col_date])
        assert dates.min() >= pd.Timestamp(debut)
        assert dates.max() <= pd.Timestamp(fin) + pd.Timedelta(days=1)

    def test_vague_intent_clarification_over_limit(self, s2_pipeline: S2Pipeline) -> None:
        vague = {
            "intention": "conformite",
            "piece": None,
            "operation": None,
            "variables": [],
            "filtres": {},
            "clarification_needed": False,
            "clarification_manque": [],
            "contexte_session": {},
        }
        assert is_vague_intent(vague)
        count = partitioner.count_rows_vague_scope(YAML_PATH, s2_pipeline.ctx)
        assert count["row_count"] > loader.MAX_VAGUE_ROWS

        result = s2_pipeline.run(vague)
        assert result.get("error") is None
        assert result["clarification_needed"] is True
        assert result["df_propre"] is None


class TestS2Cleaner:
    def test_cleaning_rules_niveau_retaille_passage(self, ctx: ClientContext) -> None:
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
        result = cleaner.run(df, ctx)
        assert result.get("error") is None
        stats = result["cleaning_stats"]
        assert stats["rules_applied"] >= 2
        assert stats["rules"]["PAS_E_Niveau_Retaille"]["status"] == "applied"
        assert stats["rules"]["PAS_E_Numero_Passage"]["status"] == "applied"
        assert len(result["df"]) < len(df)
        assert len(result["df_anomalies"]) > 0
