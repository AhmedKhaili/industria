"""
P6 Phase 2b — agrégation métier configurable (unité YAML, pas de logique OF en dur).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_AGG_FUNCS = {
    "mean": np.mean,
    "median": np.median,
    "max": np.max,
    "min": np.min,
}


def _modal_group(sub: pd.DataFrame, group_col: str) -> str:
    counts = sub[group_col].astype(str).value_counts()
    return str(counts.index[0])


def build_aggregated_units(
    df: pd.DataFrame,
    *,
    group_col: str,
    unit_col: str,
    variable: str,
    value_aggregation: str,
    min_observations_per_unit: int,
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    """
    Agrège les mesures en une valeur par (groupe quali, unité métier).

    Returns:
        df_units: colonnes group_value, unit_id, value_agg, n_observations
        trace: compteurs d'exclusion
        warnings: codes structurés (ex. unit_span_multiple_groups)
    """
    warnings: list[dict[str, Any]] = []
    trace: dict[str, Any] = {
        "units_total": 0,
        "units_kept": 0,
        "units_excluded_insufficient_obs": 0,
        "units_with_multi_group": 0,
    }

    needed = [group_col, unit_col, variable]
    work = df.dropna(subset=[unit_col, variable]).copy()
    if group_col not in work.columns:
        return pd.DataFrame(), trace, warnings

    work[unit_col] = work[unit_col].astype(str)
    work[group_col] = work[group_col].astype(str)

    agg_fn = _AGG_FUNCS.get(value_aggregation, np.mean)
    unit_to_group: dict[str, str] = {}

    for unit_id, sub in work.groupby(unit_col, dropna=True):
        trace["units_total"] += 1
        n_groups = sub[group_col].nunique()
        if n_groups > 1:
            trace["units_with_multi_group"] += 1
            warnings.append(
                {
                    "code": "unit_span_multiple_groups",
                    "unit_id": str(unit_id),
                    "groups_seen": sorted(sub[group_col].unique().tolist()),
                    "group_assigned": _modal_group(sub, group_col),
                }
            )
        unit_to_group[str(unit_id)] = _modal_group(sub, group_col)

    rows: list[dict[str, Any]] = []
    for unit_id, sub in work.groupby(unit_col, dropna=True):
        n_obs = len(sub)
        if n_obs < min_observations_per_unit:
            trace["units_excluded_insufficient_obs"] += 1
            continue
        values = sub[variable].to_numpy(dtype=float)
        rows.append(
            {
                "group_value": unit_to_group[str(unit_id)],
                "unit_id": str(unit_id),
                "value_agg": float(agg_fn(values)),
                "n_observations": int(n_obs),
            }
        )
        trace["units_kept"] += 1

    if not rows:
        return pd.DataFrame(), trace, warnings

    return pd.DataFrame(rows), trace, warnings
