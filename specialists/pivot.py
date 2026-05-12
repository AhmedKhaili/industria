import logging
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist

logger = logging.getLogger(__name__)


class PivotSpecialist(BaseSpecialist):
    """Descriptive pivot and aggregation specialist."""

    def _normalize_freq(self, freq: str | None) -> str | None:
        """
        Normalize common pandas frequency aliases for compatibility.

        Args:
            freq: Raw frequency string from params.

        Returns:
            str | None: Normalized frequency string.
        """
        if freq is None:
            return None

        normalized = str(freq).strip()
        normalized = re.sub(r"(?<=\d)H\b", "h", normalized)
        normalized = re.sub(r"^H$", "h", normalized)
        return normalized

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs for descriptive pivot analysis.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            min_rows: Base minimum row count.

        Returns:
            dict: Validation payload with valid flag, warnings, and optional error.
        """
        return super()._validate_input(df, target_column, min_rows)

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute global, grouped, and time-based descriptive aggregations.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters containing `group_col`, `agg_funcs`, and `freq`.

        Returns:
            dict: Descriptive aggregation payload.
        """
        group_col = params.get("group_col", None)
        agg_funcs = params.get(
            "agg_funcs",
            ["mean", "std", "min", "max", "count"],
        )
        freq = params.get("freq", None)
        freq_normalized = self._normalize_freq(freq)

        if not isinstance(agg_funcs, list) or not agg_funcs:
            raise ValueError("agg_funcs doit etre une liste non vide")

        allowed_agg_funcs = {"mean", "std", "min", "max", "count", "median"}
        agg_funcs = [func for func in agg_funcs if func in allowed_agg_funcs]
        if not agg_funcs:
            raise ValueError("Aucune fonction d'agregation valide")

        series = pd.to_numeric(df[target_column], errors="coerce")
        series = series.replace([np.inf, -np.inf], np.nan).dropna()

        resultats: dict[str, dict] = {}

        resultats["global"] = {
            "mean": round(float(series.mean()), 3),
            "std": round(float(series.std()), 3),
            "min": round(float(series.min()), 3),
            "max": round(float(series.max()), 3),
            "median": round(float(series.median()), 3),
            "count": int(series.count()),
            "q25": round(float(series.quantile(0.25)), 3),
            "q75": round(float(series.quantile(0.75)), 3),
        }

        pivot_groupes = None
        if group_col and group_col in df.columns:
            pivot = df.groupby(group_col)[target_column].agg(agg_funcs)
            if isinstance(pivot, pd.Series):
                pivot = pivot.to_frame(name=agg_funcs[0])

            pivot_groupes = {}
            for groupe in pivot.index:
                valeurs_groupe = {}
                for func in agg_funcs:
                    if func not in pivot.columns:
                        continue
                    valeur = pivot.loc[groupe, func]
                    if pd.isna(valeur):
                        valeurs_groupe[func] = None
                    elif func == "count":
                        valeurs_groupe[func] = int(valeur)
                    else:
                        valeurs_groupe[func] = round(float(valeur), 3)
                pivot_groupes[str(groupe)] = valeurs_groupe

        pivot_temporel = None
        if freq_normalized and "timestamp" in df.columns:
            df_temp = df.copy()
            df_temp["timestamp"] = pd.to_datetime(
                df_temp["timestamp"], errors="coerce"
            )
            df_temp = df_temp.dropna(subset=["timestamp"])
            df_temp = df_temp.sort_values("timestamp")
            df_temp = df_temp.set_index("timestamp")

            resampled = df_temp[target_column].resample(freq_normalized).agg(
                ["mean", "std", "count"]
            )
            pivot_temporel = []
            for ts, row in resampled.iterrows():
                pivot_temporel.append({
                    "periode": str(ts),
                    "mean": round(float(row["mean"]), 3)
                    if not pd.isna(row["mean"]) else None,
                    "std": round(float(row["std"]), 3)
                    if not pd.isna(row["std"]) else None,
                    "count": int(row["count"]),
                })

        logger.info(
            "Pivot calcule pour %s avec group_col=%s freq=%s",
            target_column,
            group_col,
            freq_normalized,
        )

        return {
            "colonne": target_column,
            "n": int(series.count()),
            "global": resultats["global"],
            "par_groupe": pivot_groupes,
            "par_periode": pivot_temporel,
            "group_col": group_col,
            "freq": freq,
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 120

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1h"
        ),
        "temperature": np.concatenate([
            np.random.normal(100, 5, 40),
            np.random.normal(110, 5, 40),
            np.random.normal(105, 5, 40),
        ]),
        "equipe": ["A"] * 40 + ["B"] * 40 + ["C"] * 40,
    })

    state = {"target_column": "temperature"}
    params = {
        "group_col": "equipe",
        "freq": "1D",
    }

    specialist = PivotSpecialist()
    result = specialist.run(df_test, state, params)

    print(f"Agent    : {result['agent']}")
    print(f"Status   : {result['status']}")
    print(f"Global   : mean={result['result']['global']['mean']}")
    print("\nPar equipe :")
    for group_name, stats_group in result["result"]["par_groupe"].items():
        print(f"  {group_name} -> mean={stats_group['mean']} std={stats_group['std']}")
    print("\nPar jour (5 premiers) :")
    for period in result["result"]["par_periode"][:5]:
        print(
            f"  {period['periode'][:10]} -> "
            f"mean={period['mean']} n={period['count']}"
        )
    print(f"\nTemps    : {result['execution_time_ms']}ms")
    print(f"Erreur   : {result['error']}")
