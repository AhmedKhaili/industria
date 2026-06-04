"""
Tests S2 Phase I2 — pivot_index_keys (LONG → wide) et rétrocompatibilité legacy.
"""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s2 import pivotter

LISI_YAML = "configs/lisi_aerospace/client_config.yaml"
TRACEABILITY_YAML = "configs/lisi_aerospace/client_config_traceability.yaml"


def _ctx_without_pivot_keys() -> ClientContext:
    ctx = ClientContext.load(LISI_YAML)
    raw = copy.deepcopy(ctx.raw)
    raw["dataset"].pop("pivot_index_keys", None)
    return ClientContext(**{**ctx.__dict__, "raw": raw})


def _ctx_with_extra_missing_key() -> ClientContext:
    ctx = ClientContext.load(LISI_YAML)
    raw = copy.deepcopy(ctx.raw)
    raw["dataset"]["pivot_index_keys"] = list(raw["dataset"]["pivot_index_keys"]) + [
        "colonne_inexistante"
    ]
    return ClientContext(**{**ctx.__dict__, "raw": raw})


def _long_traceability_rows() -> pd.DataFrame:
    """Deux mesures FILAGE (CR1, CR2) — même pièce / OF / pastilles."""
    shared = {
        "Date": "2026-01-15 10:00:00",
        "Designation Reference": "RD4L1A1C",
        "Operation": "FILAGE",
        "Numero Machine": "M01",
        "Numero OF MAR": "OF-100",
        "Numero Piece Contrôlée": "PC-42",
        "PAS_E_Numero_Passage": "P1",
        "PAS_E_Niveau_Retaille": "0",
        "PAS_E_Fournisseur": "F-A",
        "PAS_I_Numero_Passage": "P2",
        "PAS_I_Niveau_Retaille": "-1",
        "PAS_I_Fournisseur": "F-B",
        "Ref_Matrice": pd.NA,
        "LTI": 1.0,
        "LTS": 2.0,
        "Nominal": 1.5,
    }
    rows = [
        {**shared, "Tag": "CR1", "Value": 10.1},
        {**shared, "Tag": "CR2", "Value": 20.2},
    ]
    return pd.DataFrame(rows)


def _legacy_nine_col_rows() -> pd.DataFrame:
    """Format 9 colonnes sans traçabilité ni PAS."""
    return pd.DataFrame(
        {
            "Date": ["2026-01-10", "2026-01-10"],
            "Designation Reference": ["M2L1A1C", "M2L1A1C"],
            "Operation": ["FILAGE", "FILAGE"],
            "Numero Machine": ["P1", "P1"],
            "Tag": ["CR1", "CR2"],
            "Value": [1.0, 2.0],
            "LTI": [0.0, 0.0],
            "LTS": [1.0, 1.0],
        }
    )


@pytest.fixture(scope="module")
def ctx_lisi() -> ClientContext:
    return ClientContext.load(LISI_YAML)


class TestPivotIndexKeysUnit:
    def test_legacy_without_yaml_keys_matches_old_meta_set(
        self, ctx_lisi: ClientContext
    ) -> None:
        ctx = _ctx_without_pivot_keys()
        df = _legacy_nine_col_rows()
        intent = {"variables": ["CR1", "CR2"]}
        res = pivotter.run(df, ctx, intent)
        assert res.get("error") is None
        wide = res["df"]
        assert wide is not None
        assert len(wide) == 1
        assert "CR1" in wide.columns and "CR2" in wide.columns
        for col in ("Date", "Designation Reference", "Operation", "Numero Machine"):
            assert col in wide.columns

    def test_with_pivot_keys_traceability_columns_preserved(
        self, ctx_lisi: ClientContext
    ) -> None:
        df = _long_traceability_rows()
        intent = {"variables": ["CR1", "CR2"]}
        res = pivotter.run(df, ctx_lisi, intent)
        assert res.get("error") is None
        wide = res["df"]
        assert wide is not None
        assert len(wide) == 1
        assert wide.loc[0, "CR1"] == pytest.approx(10.1)
        assert wide.loc[0, "CR2"] == pytest.approx(20.2)
        for col in (
            "Numero Piece Contrôlée",
            "Numero OF MAR",
            "PAS_E_Numero_Passage",
            "PAS_E_Niveau_Retaille",
            "PAS_E_Fournisseur",
            "PAS_I_Numero_Passage",
            "PAS_I_Niveau_Retaille",
            "PAS_I_Fournisseur",
        ):
            assert col in wide.columns
        assert wide.loc[0, "Numero Piece Contrôlée"] == "PC-42"
        assert wide.loc[0, "Numero OF MAR"] == "OF-100"
        assert wide.loc[0, "PAS_E_Numero_Passage"] == "P1"

    def test_cr1_cr2_same_row_with_shared_traceability(self, ctx_lisi: ClientContext) -> None:
        df = _long_traceability_rows()
        res = pivotter.run(df, ctx_lisi, {"variables": ["CR1", "CR2"]})
        wide = res["df"]
        assert len(wide) == 1
        assert not wide[["CR1", "CR2", "Numero Piece Contrôlée"]].isna().any().any()

    def test_pas_cols_appended_even_when_not_in_pivot_index_keys(
        self, ctx_lisi: ClientContext
    ) -> None:
        id_cols = pivotter._build_pivot_id_columns(_long_traceability_rows(), ctx_lisi)
        assert "PAS_E_Numero_Passage" in id_cols
        assert "PAS_E_Niveau_Retaille" in id_cols
        assert "PAS_E_Fournisseur" in id_cols

    def test_missing_declared_key_does_not_crash(self, ctx_lisi: ClientContext) -> None:
        ctx = _ctx_with_extra_missing_key()
        df = _legacy_nine_col_rows()
        res = pivotter.run(df, ctx, {"variables": ["CR1", "CR2"]})
        assert res.get("error") is None
        assert len(res["df"]) == 1

    def test_missing_physical_column_skipped(self, ctx_lisi: ClientContext) -> None:
        df = _legacy_nine_col_rows()
        id_cols = pivotter._build_pivot_id_columns(df, ctx_lisi)
        assert "Numero OF MAR" not in id_cols
        assert "Numero Piece Contrôlée" not in id_cols
        assert "Date" in id_cols

    def test_different_pas_values_split_rows_not_merge_wrongly(
        self, ctx_lisi: ClientContext
    ) -> None:
        df = _long_traceability_rows()
        df.loc[1, "PAS_E_Numero_Passage"] = "P2"
        res = pivotter.run(df, ctx_lisi, {"variables": ["CR1", "CR2"]})
        assert len(res["df"]) == 2


@pytest.mark.skipif(
    not __import__("pathlib").Path(TRACEABILITY_YAML).is_file(),
    reason="config traceability absente",
)
class TestPivotTraceabilityIntegration:
    @pytest.fixture(scope="class")
    def trace_sample(self) -> pd.DataFrame | None:
        path = __import__("pathlib").Path(
            "data/lisi_capteurs_export_complet_tracabilite.csv"
        )
        if not path.is_file():
            return None
        usecols = [
            "Date",
            "Tag",
            "Value",
            "Designation Reference",
            "Operation",
            "Numero Machine",
            "Numero OF MAR",
            "Numero Piece Contrôlée",
            "PAS_E_Numero_Passage",
            "PAS_E_Niveau_Retaille",
            "PAS_E_Fournisseur",
            "Ref_Matrice",
        ]
        df = pd.read_csv(path, sep=";", nrows=5000, usecols=usecols, encoding="utf-8")
        mask = (
            (df["Designation Reference"].astype(str) == "RD4L1A1C")
            & (df["Operation"] == "FILAGE")
            & (df["Tag"].isin(["CR1", "CR2"]))
        )
        return df.loc[mask].head(200)

    def test_real_export_pivot_columns(self, trace_sample: pd.DataFrame | None) -> None:
        if trace_sample is None or trace_sample.empty:
            pytest.skip("échantillon FILAGE RD4 vide dans les 5000 premières lignes")
        ctx = ClientContext.load(TRACEABILITY_YAML)
        res = pivotter.run(trace_sample, ctx, {"variables": ["CR1", "CR2"]})
        assert res.get("error") is None
        wide = res["df"]
        assert "Numero Piece Contrôlée" in wide.columns
        assert "Numero OF MAR" in wide.columns
        if "PAS_E_Numero_Passage" in trace_sample.columns:
            assert "PAS_E_Numero_Passage" in wide.columns
        assert "CR1" in wide.columns and "CR2" in wide.columns
