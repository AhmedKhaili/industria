"""
Tests S2 — correctifs I3 (parquet types mixtes, passage PAS vide en EQUATOR).
"""

from __future__ import annotations

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s2 import cleaner, partitioner
LISI_YAML = "configs/lisi_aerospace/client_config.yaml"


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(LISI_YAML)


class TestPartitionerCoerceForParquet:
    def test_mixed_int_str_object_writes_and_reads_parquet(
        self, ctx: ClientContext, tmp_path
    ) -> None:
        col_of = ctx.colonnes["numero_of"]
        col_piece = ctx.colonnes["numero_piece"]
        raw = pd.DataFrame(
            {
                col_of: [816997, "M002910", None],
                col_piece: ["PC-1", "PC-2", "PC-3"],
                ctx.colonnes["tag"]: ["CR1", "CR2", "CR1"],
                ctx.colonnes["valeur"]: [1.0, 2.0, 3.0],
                ctx.colonnes["operation"]: ["FILAGE"] * 3,
                ctx.colonnes["piece"]: ["M2L1A1C"] * 3,
            }
        )
        with pytest.raises(Exception):
            raw.to_parquet(tmp_path / "raw_fail.parquet", index=False)

        coerced = partitioner._coerce_for_parquet(raw, ctx)
        assert list(coerced.columns) == list(raw.columns)
        out = tmp_path / "coerced.parquet"
        coerced.to_parquet(out, index=False)
        back = pd.read_parquet(out)

        assert list(back.columns) == list(raw.columns)
        of_vals = back[col_of].tolist()
        assert of_vals[:2] == ["816997", "M002910"]
        assert pd.isna(of_vals[2])
        assert back[col_piece].tolist() == ["PC-1", "PC-2", "PC-3"]

    def test_coerce_preserves_all_columns(self, ctx: ClientContext) -> None:
        cols = [
            ctx.colonnes["numero_of"],
            ctx.colonnes["numero_piece"],
            "PAS_E_Fournisseur",
            ctx.colonnes["tag"],
            ctx.colonnes["valeur"],
        ]
        df = pd.DataFrame({c: [1, "x"] for c in cols})
        df[ctx.colonnes["numero_of"]] = [840242, "OF-STR"]
        out = partitioner._coerce_for_parquet(df, ctx)
        assert set(out.columns) == set(df.columns)


class TestCleanerPassageValeursValides:
    def test_empty_na_p1_p2_kept_p3_anomaly(self, ctx: ClientContext) -> None:
        df = pd.DataFrame(
            {
                "PAS_E_Numero_Passage": [None, "", "P1", "P2", "P3"],
                "PAS_I_Numero_Passage": ["P1"] * 5,
                "PAS_E_Niveau_Retaille": ["-1"] * 5,
                "PAS_I_Niveau_Retaille": ["-1"] * 5,
                "Tag": ["CR1"] * 5,
                "Value": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )
        res = cleaner.run(df, ctx)
        assert res.get("error") is None
        kept = res["df"]["PAS_E_Numero_Passage"].tolist()
        assert len(res["df"]) == 4
        assert res["df_anomalies"]["PAS_E_Numero_Passage"].tolist() == ["P3"]
        assert kept.count("P3") == 0
        assert "P1" in kept and "P2" in kept

    def test_equator_all_empty_passage_not_wiped(self, ctx: ClientContext) -> None:
        """Cas I3 : EQUATOR sans pastille passage — lignes conservées."""
        n = 6
        df = pd.DataFrame(
            {
                "PAS_E_Numero_Passage": [None] * n,
                "PAS_I_Numero_Passage": [None] * n,
                "PAS_E_Niveau_Retaille": [None] * n,
                "PAS_I_Niveau_Retaille": [None] * n,
                "Tag": ["CR50_INTRADOS_VRILLAGE", "CR70_INTRADOS_VRILLAGE"] * 3,
                "Value": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                ctx.colonnes["operation"]: ["EQUATOR"] * n,
                ctx.colonnes["piece"]: ["RD4L1A1C"] * n,
            }
        )
        res = cleaner.run(df, ctx)
        assert res.get("error") is None
        assert len(res["df"]) == n
        assert len(res["df_anomalies"]) == 0


class TestTraceabilityFixtureLight:
    """Fixture légère (sans CSV 500 Mo) — colonnes export traçabilité."""

    @staticmethod
    def _traceability_long_rows() -> pd.DataFrame:
        shared_filage = {
            "Date": "2026-01-15 10:00:00",
            "Designation Reference": "RD4L1A1C",
            "Operation": "FILAGE",
            "Numero Machine": "M01",
            "Numero OF MAR": 816997,
            "Numero Piece Contrôlée": "PC-42",
            "PAS_E_Numero_Passage": "P1",
            "PAS_E_Niveau_Retaille": "-18,5",
            "Nominal": 1.5,
            "LTI": 1.0,
            "LTS": 2.0,
        }
        rows = [
            {**shared_filage, "Tag": "CR1", "Value": 10.0},
            {**shared_filage, "Tag": "CR2", "Value": 20.0},
        ]
        return pd.DataFrame(rows)

    def test_coerce_then_parquet_mixed_of(self, ctx: ClientContext, tmp_path) -> None:
        df = self._traceability_long_rows()
        coerced = partitioner._coerce_for_parquet(df, ctx)
        path = tmp_path / "filage.parquet"
        coerced.to_parquet(path, index=False)
        back = pd.read_parquet(path)
        assert set(back["Numero OF MAR"].astype(str)) == {"816997"}

    def test_pipeline_wide_after_cleaner_on_fixture(self, ctx: ClientContext) -> None:
        from systems.s2 import pivotter

        clean = cleaner.run(self._traceability_long_rows(), ctx)
        assert clean.get("error") is None
        assert len(clean["df"]) == 2
        piv = pivotter.run(
            clean["df"],
            ctx,
            {"variables": ["CR1", "CR2"]},
        )
        wide = piv["df"]
        assert piv.get("error") is None
        assert len(wide) == 1
        assert "Numero OF MAR" in wide.columns
        assert "Numero Piece Contrôlée" in wide.columns
        assert wide.loc[0, "CR1"] == pytest.approx(10.0)
        assert wide.loc[0, "CR2"] == pytest.approx(20.0)
