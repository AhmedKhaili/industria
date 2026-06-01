"""
Tests P6 Phase 2b — agrégation métier configurable F2.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from systems.s1.client_context import ClientContext
from systems.s3 import business_unit_aggregate, group_descriptive

GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)


@pytest.fixture(scope="module")
def ctx_generic() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


def _minimal_yaml(tmp_path: Path, agregation_block: str) -> str:
    base = (Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml").read_text(
        encoding="utf-8"
    )
    if "agregation_metier_f2:" in base:
        start = base.index("  agregation_metier_f2:")
        end = base.index("\nentites:", start)
        base = base[:start] + agregation_block + "\n" + base[end:]
    else:
        insert_at = base.index("\nentites:")
        base = base[:insert_at] + "\n" + agregation_block + base[insert_at:]
    path = tmp_path / "client_config.yaml"
    path.write_text(base, encoding="utf-8")
    return str(path)


def _df_lots() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "DIA_01": [9.95, 10.0, 10.05, 10.02, 20.0, 20.01, 20.0, 20.05],
            "Machine": ["M1", "M1", "M1", "M1", "M2", "M2", "M2", "M2"],
            "Lot_ID": ["L1", "L1", "L2", "L2", "L3", "L3", "L4", "L4"],
        }
    )


def test_resolve_single_enabled_unit(ctx_generic: ClientContext) -> None:
    cfg = ctx_generic.resolve_agregation_metier_f2({})
    assert cfg["active"] is True
    assert cfg["unit_id"] == "lot_unitaire"
    assert cfg["unit_column"] == "Lot_ID"
    assert cfg["min_observations_per_unit"] == 2


def test_ambiguous_units_fallback(tmp_path: Path) -> None:
    block = """
  agregation_metier_f2:
    enabled: true
    preferred_output: measure
    fallback_to_measure: true
    defaults:
      min_observations_per_unit: 2
      value_aggregation: mean
      tolerance_level: aggregated_unit
    unites:
      u1:
        enabled: true
        unit_column: Lot_ID
      u2:
        enabled: true
        unit_column: Order_ID
"""
    path = _minimal_yaml(tmp_path, block)
    ctx = ClientContext.load(path)
    cfg = ctx.resolve_agregation_metier_f2({})
    assert cfg["active"] is False
    assert cfg["reason"] == "ambiguous"
    codes = [w["code"] for w in cfg["warnings"]]
    assert "aggregation_unit_ambiguous" in codes


def test_default_unit_resolves(tmp_path: Path) -> None:
    block = """
  agregation_metier_f2:
    enabled: true
    default_unit: u2
    preferred_output: measure
    defaults:
      min_observations_per_unit: 2
      value_aggregation: mean
    unites:
      u1:
        enabled: true
        unit_column: Lot_ID
      u2:
        enabled: true
        unit_column: Order_ID
"""
    path = _minimal_yaml(tmp_path, block)
    ctx = ClientContext.load(path)
    cfg = ctx.resolve_agregation_metier_f2({})
    assert cfg["active"] is True
    assert cfg["unit_id"] == "u2"
    assert cfg["unit_column"] == "Order_ID"


def test_column_missing_warning(ctx_generic: ClientContext) -> None:
    intent = {
        "piece": "P-A100",
        "operation": "USINAGE",
        "group_by": "Machine",
        "variables": ["DIA_01"],
        "intention": "comparaison_groupes",
    }
    df = _df_lots().drop(columns=["Lot_ID"])
    blocks = group_descriptive.compute_all(df, intent, ctx_generic)
    assert len(blocks) == 1
    assert blocks[0]["level"] == "measure"
    codes = [
        w.get("code") if isinstance(w, dict) else w
        for w in blocks[0]["warnings"]
    ]
    assert "aggregation_column_missing" in codes


def test_aggregation_mean_per_unit(ctx_generic: ClientContext) -> None:
    df_units, trace, _ = business_unit_aggregate.build_aggregated_units(
        _df_lots(),
        group_col="Machine",
        unit_col="Lot_ID",
        variable="DIA_01",
        value_aggregation="mean",
        min_observations_per_unit=2,
    )
    assert trace["units_kept"] == 4
    l1 = df_units.loc[df_units["unit_id"] == "L1", "value_agg"].iloc[0]
    assert l1 == pytest.approx(9.975, rel=1e-3)


def test_min_observations_excludes_unit(ctx_generic: ClientContext) -> None:
    df = pd.DataFrame(
        {
            "DIA_01": [10.0, 10.1, 10.2],
            "Machine": ["M1", "M1", "M1"],
            "Lot_ID": ["L1", "L1", "L2"],
        }
    )
    _, trace, _ = business_unit_aggregate.build_aggregated_units(
        df,
        group_col="Machine",
        unit_col="Lot_ID",
        variable="DIA_01",
        value_aggregation="mean",
        min_observations_per_unit=5,
    )
    assert trace["units_excluded_insufficient_obs"] == 2
    assert trace["units_kept"] == 0


def test_unit_span_multiple_groups_warning() -> None:
    df = pd.DataFrame(
        {
            "DIA_01": [10.0, 10.0, 10.0, 10.0],
            "Machine": ["M1", "M1", "M2", "M2"],
            "Lot_ID": ["LX", "LX", "LX", "LX"],
        }
    )
    _, _, warnings = business_unit_aggregate.build_aggregated_units(
        df,
        group_col="Machine",
        unit_col="Lot_ID",
        variable="DIA_01",
        value_aggregation="mean",
        min_observations_per_unit=2,
    )
    codes = [w["code"] for w in warnings]
    assert "unit_span_multiple_groups" in codes


def test_out_of_tolerance_on_aggregated_units(ctx_generic: ClientContext) -> None:
    intent = {
        "piece": "P-A100",
        "operation": "USINAGE",
        "group_by": "Machine",
        "variables": ["DIA_01"],
        "intention": "comparaison_groupes",
    }
    cfg = ctx_generic.resolve_agregation_metier_f2(intent)
    block = group_descriptive.compute_aggregated_for_variable(
        _df_lots(), intent, ctx_generic, "DIA_01", cfg
    )
    assert block is not None
    assert block["level"] == "aggregated_unit"
    m2 = next(r for r in block["rows"] if r["group_value"] == "M2")
    assert m2["out_of_tolerance_rate"] == 100.0


def test_preferred_output_both(ctx_generic: ClientContext) -> None:
    intent = {
        "piece": "P-A100",
        "operation": "USINAGE",
        "group_by": "Machine",
        "variables": ["DIA_01"],
        "intention": "comparaison_groupes",
    }
    blocks = group_descriptive.compute_all(_df_lots(), intent, ctx_generic)
    levels = [b["level"] for b in blocks]
    assert levels.count("measure") == 1
    assert levels.count("aggregated_unit") == 1


def test_tolerance_level_measure_warning(tmp_path: Path) -> None:
    block = """
  agregation_metier_f2:
    enabled: true
    default_unit: lot_unitaire
    preferred_output: measure
    defaults:
      min_observations_per_unit: 2
      value_aggregation: mean
      tolerance_level: measure
    unites:
      lot_unitaire:
        enabled: true
        unit_column: Lot_ID
"""
    path = _minimal_yaml(tmp_path, block)
    ctx = ClientContext.load(path)
    cfg = ctx.resolve_agregation_metier_f2({})
    codes = [w["code"] for w in cfg["warnings"]]
    assert "tolerance_level_measure_not_supported" in codes
    assert cfg["tolerance_level"] == "aggregated_unit"


def test_ranking_upper_on_aggregated_units() -> None:
    lti, lts = 0.0, 0.2
    rows = [
        {
            "group_value": "LOIN",
            "out_of_tolerance_rate": 0.0,
            "cpk": None,
            "risk_to_limit_score": group_descriptive.risk_to_limit_score(
                0.05, lti, lts, "upper"
            ),
        },
        {
            "group_value": "PROCHE",
            "out_of_tolerance_rate": 0.0,
            "cpk": None,
            "risk_to_limit_score": group_descriptive.risk_to_limit_score(
                0.19, lti, lts, "upper"
            ),
        },
        {
            "group_value": "AU_DESSUS",
            "out_of_tolerance_rate": 0.0,
            "cpk": None,
            "risk_to_limit_score": group_descriptive.risk_to_limit_score(
                0.25, lti, lts, "upper"
            ),
        },
    ]
    ranked = group_descriptive.assign_ranks_and_labels(rows)
    assert [r["group_value"] for r in ranked] == [
        "AU_DESSUS",
        "PROCHE",
        "LOIN",
    ]
