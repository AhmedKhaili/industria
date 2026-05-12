import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist


class CorrelationSpecialist(BaseSpecialist):
    """Correlation analysis specialist for numeric process variables."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and correlation-specific constraints.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            min_rows: Base interface parameter preserved for compatibility.

        Returns:
            dict: Validation payload with valid flag, warnings, and optional error.
        """
        validation = super()._validate_input(df, target_column, min_rows)
        if not validation["valid"]:
            return validation

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if len(numeric_cols) < 2:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Minimum 2 colonnes numériques requises pour corrélation",
            }

        if len(df.index) < 10:
            validation["warnings"].append(
                "Série courte - corrélations moins fiables"
            )

        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute pairwise correlations between the target column and other numeric columns.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters. Supported key: `method`.

        Returns:
            dict: Correlation summary sorted by strongest absolute relationship.
        """
        method = str(params.get("method", "all")).lower()
        allowed_methods = {"pearson", "spearman", "kendall", "all"}
        if method not in allowed_methods:
            raise ValueError(
                "Méthode invalide: utiliser 'pearson', 'spearman', 'kendall' ou 'all'"
            )

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        other_cols = [col for col in numeric_cols if col != target_column]

        series_target = pd.to_numeric(df[target_column], errors="coerce")
        series_target = series_target.replace([np.inf, -np.inf], np.nan).dropna()

        correlations: list[dict] = []

        for col in other_cols:
            series_other = pd.to_numeric(df[col], errors="coerce")
            series_other = series_other.replace([np.inf, -np.inf], np.nan).dropna()

            common_idx = series_target.index.intersection(series_other.index)
            if len(common_idx) < 5:
                continue

            s1 = series_target.loc[common_idx]
            s2 = series_other.loc[common_idx]

            if s1.nunique(dropna=True) < 2 or s2.nunique(dropna=True) < 2:
                continue

            result_col = {"colonne": col}

            if method in ["pearson", "all"]:
                r, p = stats.pearsonr(s1, s2)
                result_col["pearson_r"] = round(float(r), 3)
                result_col["pearson_p"] = round(float(p), 4)

            if method in ["spearman", "all"]:
                r, p = stats.spearmanr(s1, s2)
                result_col["spearman_r"] = round(float(r), 3)
                result_col["spearman_p"] = round(float(p), 4)

            if method in ["kendall", "all"]:
                r, p = stats.kendalltau(s1, s2)
                result_col["kendall_tau"] = round(float(r), 3)
                result_col["kendall_p"] = round(float(p), 4)

            primary_r = result_col.get(
                "pearson_r",
                result_col.get("spearman_r", result_col.get("kendall_tau", 0)),
            )
            abs_r = abs(primary_r)

            if abs_r >= 0.8:
                force = "très forte"
            elif abs_r >= 0.6:
                force = "forte"
            elif abs_r >= 0.4:
                force = "modérée"
            elif abs_r >= 0.2:
                force = "faible"
            else:
                force = "négligeable"

            primary_p = result_col.get(
                "pearson_p",
                result_col.get("spearman_p", result_col.get("kendall_p", 1)),
            )

            result_col["force"] = force
            result_col["significative"] = bool(primary_p < 0.05)

            correlations.append(result_col)

        correlations.sort(
            key=lambda item: abs(
                item.get(
                    "pearson_r",
                    item.get("spearman_r", item.get("kendall_tau", 0)),
                )
            ),
            reverse=True,
        )

        return {
            "colonne_cible": target_column,
            "method": method,
            "n_colonnes_comparées": len(other_cols),
            "correlations": correlations,
            "correlation_max": correlations[0] if correlations else None,
            "correlations_significatives": [
                correlation
                for correlation in correlations
                if correlation.get("significative", False)
            ],
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 100

    base = np.random.normal(100, 10, n)

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "capteur_a": base,
        "capteur_b": base * 0.8 + np.random.normal(0, 5, n),
        "capteur_c": np.random.normal(50, 5, n),
        "capteur_d": -base * 0.6 + np.random.normal(0, 8, n),
    })

    state = {"target_column": "capteur_a"}
    specialist = CorrelationSpecialist()
    result = specialist.run(df_test, state)

    print(f"Agent      : {result['agent']}")
    print(f"Status     : {result['status']}")
    print(f"Colonnes   : {result['result']['n_colonnes_comparées']}")
    print("\nCorrélations :")
    for correlation in result["result"]["correlations"]:
        print(
            f"  {correlation['colonne']:12} -> "
            f"r={correlation.get('pearson_r', 'N/A'):6} "
            f"force={correlation['force']:10} "
            f"sig={correlation['significative']}"
        )
    print(f"\nTemps      : {result['execution_time_ms']}ms")
    print(f"Erreur     : {result['error']}")
