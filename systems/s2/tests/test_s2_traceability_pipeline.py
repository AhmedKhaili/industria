"""
Tests d'acceptation I4 — pipeline S2 sur export traçabilité (client démo, CSV local gitignored).

Utilise configs/lisi_aerospace/client_config_traceability.yaml uniquement.
Skip propre si data/lisi_capteurs_export_complet_tracabilite.csv absent (CI / clone sans données).

Cache : répertoire temporaire par session de tests (ne modifie pas data/cache/lisi_aerospace).
Rebuild : ensure_partitions(..., force=True) dans le tmp uniquement.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s2 import cleaner, loader, partitioner
from systems.s2.pipeline import S2Pipeline

TRACEABILITY_YAML = "configs/lisi_aerospace/client_config_traceability.yaml"
PIECE = "RD4L1A1C"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPORT_CSV = PROJECT_ROOT / "data" / "lisi_capteurs_export_complet_tracabilite.csv"

TC00_COLUMNS = [
    "Numero OF MAR",
    "Numero Piece Contrôlée",
    "Nominal",
    "PAS_E_Numero_Passage",
    "PAS_E_Niveau_Retaille",
    "PAS_E_Fournisseur",
    "Tag",
    "Value",
]


def _skip_if_export_missing() -> None:
    if not EXPORT_CSV.is_file():
        pytest.skip(
            f"Export traçabilité absent ({EXPORT_CSV}) — tests I4 ignorés en CI / clone sans données"
        )


def _intent(
    *,
    operation: str,
    variables: list[str],
    intention: str = "diagnostic_causal",
) -> dict:
    return {
        "intention": intention,
        "piece": PIECE,
        "operation": operation,
        "variables": variables,
        "group_by": None,
        "filtres": {"piece": PIECE, "operation": operation},
        "clarification_needed": False,
        "clarification_manque": [],
        "contexte_session": {},
    }


@pytest.fixture(scope="module")
def trace_ctx() -> ClientContext:
    return ClientContext.load(TRACEABILITY_YAML)


@pytest.fixture(scope="module")
def trace_s2_env(tmp_path_factory):
    """
    Cache parquet isolé + pipeline S2 traceability.
    Ne touche pas data/cache/lisi_aerospace (legacy / dev local).
    """
    _skip_if_export_missing()
    cache_root = tmp_path_factory.mktemp("s2_traceability_cache")
    ctx = ClientContext.load(TRACEABILITY_YAML)
    patch = pytest.MonkeyPatch()
    patch.setattr(
        partitioner,
        "cache_dir",
        lambda _yaml_path, _context=None: cache_root,
    )
    patch.setattr(
        loader,
        "cache_dir",
        lambda _yaml_path, _context=None: cache_root,
    )
    try:
        part = partitioner.ensure_partitions(TRACEABILITY_YAML, ctx, force=True)
        if part.get("error"):
            pytest.skip(f"Partitionnement traçabilité impossible : {part['error']}")
        pipeline = S2Pipeline(TRACEABILITY_YAML)
        yield {
            "ctx": ctx,
            "pipeline": pipeline,
            "cache_root": cache_root,
            "partition_count": part.get("partition_count", 0),
        }
    finally:
        patch.undo()


@pytest.fixture(scope="module")
def tc01_result(trace_s2_env):
    return trace_s2_env["pipeline"].run(
        _intent(operation="FILAGE", variables=["CR1", "CR2"])
    )


@pytest.fixture(scope="module")
def tc02_result(trace_s2_env):
    return trace_s2_env["pipeline"].run(
        _intent(
            operation="EQUATOR",
            variables=["CR50_INTRADOS_VRILLAGE", "CR70_INTRADOS_VRILLAGE"],
        )
    )


class TestTC00ExportAndConfig:
    def test_traceability_config_loads(self, trace_ctx: ClientContext) -> None:
        assert trace_ctx.raw["dataset"]["fichier"].endswith(
            "lisi_capteurs_export_complet_tracabilite.csv"
        )
        assert trace_ctx.raw["dataset"].get("pivot_index_keys")
        assert trace_ctx.get_agregation_metier_f2_raw().get("enabled") is False

    def test_export_csv_present_with_key_columns(self) -> None:
        _skip_if_export_missing()
        header = pd.read_csv(EXPORT_CSV, sep=";", nrows=0, encoding="utf-8")
        missing = [c for c in TC00_COLUMNS if c not in header.columns]
        assert not missing, f"Colonnes manquantes dans l'export : {missing}"


@pytest.mark.usefixtures("trace_s2_env")
class TestTC01FilageCr1Cr2:
    TC01_COLS = [
        "CR1",
        "CR2",
        "Numero Piece Contrôlée",
        "Numero OF MAR",
        "Date",
        "Numero Machine",
        "PAS_E_Numero_Passage",
        "PAS_E_Niveau_Retaille",
        "PAS_E_Fournisseur",
    ]

    def test_pipeline_ok(self, tc01_result: dict) -> None:
        assert tc01_result.get("error") is None

    def test_df_propre_columns_and_no_long_format(self, tc01_result: dict) -> None:
        df = tc01_result["df_propre"]
        assert df is not None and not df.empty
        for col in self.TC01_COLS:
            assert col in df.columns, f"colonne absente : {col}"
        assert "Tag" not in df.columns
        assert "Value" not in df.columns

    def test_cr1_cr2_both_non_null_rows(self, tc01_result: dict) -> None:
        df = tc01_result["df_propre"]
        both = df[["CR1", "CR2"]].notna().all(axis=1).sum()
        assert both > 0, "aucune ligne avec CR1 et CR2 renseignés"


@pytest.mark.usefixtures("trace_s2_env")
class TestTC02EquatorCr50Cr70:
    VARS = ["CR50_INTRADOS_VRILLAGE", "CR70_INTRADOS_VRILLAGE"]
    TC02_COLS = [
        "Numero Piece Contrôlée",
        "Numero OF MAR",
        "Ref_Matrice",
        "Numero Machine",
        "Date",
    ]

    def test_pipeline_ok(self, tc02_result: dict) -> None:
        assert tc02_result.get("error") is None

    def test_df_propre_columns(self, tc02_result: dict) -> None:
        df = tc02_result["df_propre"]
        assert df is not None and not df.empty
        for var in self.VARS:
            assert var in df.columns
        for col in self.TC02_COLS:
            assert col in df.columns
        assert "Tag" not in df.columns
        assert "Value" not in df.columns

    def test_both_variables_non_null(self, tc02_result: dict) -> None:
        df = tc02_result["df_propre"]
        both = df[self.VARS].notna().all(axis=1).sum()
        assert both > 0


@pytest.mark.usefixtures("trace_s2_env")
class TestTC03PassagePastille:
    def test_passage_rule_applied(self, tc01_result: dict) -> None:
        rules = tc01_result["cleaning_stats"]["rules"]
        assert rules["PAS_E_Numero_Passage"]["status"] == "applied"

    def test_passage_values_only_p1_p2_or_empty(self, tc01_result: dict) -> None:
        df = tc01_result["df_propre"]
        col = "PAS_E_Numero_Passage"
        assert col in df.columns
        non_empty = df[col].dropna().astype(str).str.strip()
        non_empty = non_empty[non_empty != ""]
        if len(non_empty):
            assert set(non_empty.unique()).issubset({"P1", "P2"})
        assert len(df) > 0


@pytest.mark.usefixtures("trace_s2_env")
class TestTC04RetailleNiveau:
    def test_retaille_rule_applied(self, tc01_result: dict) -> None:
        rules = tc01_result["cleaning_stats"]["rules"]
        assert rules["PAS_E_Niveau_Retaille"]["status"] == "applied"

    def test_retaille_non_empty_all_le_zero(self, tc01_result: dict) -> None:
        df = tc01_result["df_propre"]
        col = "PAS_E_Niveau_Retaille"
        s = df[col].dropna().astype(str)
        s = s[s.str.strip() != ""]
        assert len(s) > 0, "aucune retaille renseignée dans df_propre"
        num = cleaner._parse_numeric_locale(s)
        assert (num > 0).sum() == 0

    def test_positive_retaille_in_anomalies_when_removed(
        self, tc01_result: dict
    ) -> None:
        stats = tc01_result["cleaning_stats"]["rules"]["PAS_E_Niveau_Retaille"]
        anom = tc01_result["df_anomalies"]
        removed = stats.get("rows_removed", 0)
        if removed == 0:
            pytest.skip("aucune anomalie retaille dans cet échantillon partition")
        assert "PAS_E_Niveau_Retaille" in anom.columns
        pos = cleaner._parse_numeric_locale(
            anom["PAS_E_Niveau_Retaille"].dropna().astype(str)
        )
        assert (pos > 0).sum() > 0
