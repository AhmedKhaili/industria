import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist

logger = logging.getLogger(__name__)


class RegressionSpecialist(BaseSpecialist):
    """Simple and multiple linear regression specialist."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and regression-specific constraints.

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

        if len(df.index) < 10:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Minimum 10 points pour regression fiable",
            }

        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute simple regressions for each candidate feature and one multiple regression.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters. Supported key: `feature_cols`.

        Returns:
            dict: Regression summaries for simple and multiple models.
        """
        feature_cols = params.get("feature_cols", None)

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if feature_cols:
            x_cols = [
                column for column in feature_cols
                if column in df.columns and column != target_column
            ]
        else:
            x_cols = [column for column in numeric_cols if column != target_column]

        if not x_cols:
            raise ValueError("Aucune variable explicative disponible")

        y = pd.to_numeric(df[target_column], errors="coerce").dropna()

        regressions_simples: list[dict] = []
        for col in x_cols:
            x = pd.to_numeric(df[col], errors="coerce").dropna()
            common = y.index.intersection(x.index)
            if len(common) < 5:
                continue

            x_common = x.loc[common]
            y_common = y.loc[common]

            if x_common.nunique(dropna=True) < 2:
                continue

            slope, intercept, r_value, p_value, std_err = stats.linregress(
                x_common, y_common
            )

            regressions_simples.append({
                "variable": col,
                "slope": round(float(slope), 4),
                "intercept": round(float(intercept), 4),
                "r_squared": round(float(r_value ** 2), 4),
                "p_value": round(float(p_value), 4),
                "significative": bool(p_value < 0.05),
                "std_err": round(float(std_err), 4),
                "interpretation": (
                    f"Si {col} augmente de 1 unite, {target_column} "
                    f"{'augmente' if slope > 0 else 'diminue'} "
                    f"de {abs(round(float(slope), 3))} unites"
                ),
            })

        regressions_simples.sort(
            key=lambda item: item["r_squared"],
            reverse=True,
        )

        meilleure = regressions_simples[0] if regressions_simples else None

        dataset_multiple = df[[target_column] + x_cols].apply(
            pd.to_numeric, errors="coerce"
        ).dropna()

        regression_multiple = None
        if len(dataset_multiple) >= max(5, len(x_cols) + 2):
            y_multi = dataset_multiple[target_column].to_numpy(dtype=float)
            x_multi = dataset_multiple[x_cols].to_numpy(dtype=float)

            design_matrix = np.column_stack([
                np.ones(len(x_multi), dtype=float),
                x_multi,
            ])
            coefficients, _, _, _ = np.linalg.lstsq(
                design_matrix,
                y_multi,
                rcond=None,
            )

            y_pred = design_matrix @ coefficients
            residuals = y_multi - y_pred
            ss_res = float(np.sum(residuals ** 2))
            ss_tot = float(np.sum((y_multi - np.mean(y_multi)) ** 2))
            r_squared_multi = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

            n_obs = len(y_multi)
            n_params = design_matrix.shape[1]
            try:
                if n_obs > n_params:
                    sigma2 = ss_res / (n_obs - n_params)
                    cov_beta = sigma2 * np.linalg.inv(design_matrix.T @ design_matrix)
                    std_errors = np.sqrt(np.diag(cov_beta))
                    t_values = coefficients / std_errors
                    p_values = 2 * (
                        1 - stats.t.cdf(np.abs(t_values), df=n_obs - n_params)
                    )
                else:
                    std_errors = np.full_like(coefficients, np.nan, dtype=float)
                    p_values = np.full_like(coefficients, np.nan, dtype=float)
            except np.linalg.LinAlgError:
                logger.warning(
                    "Regression multiple ignoree: matrice singuliere pour %s",
                    target_column,
                )
            else:
                coefficients_payload = []
                for idx, column in enumerate(["intercept"] + x_cols):
                    coef_value = float(coefficients[idx])
                    p_value = float(p_values[idx]) if not np.isnan(p_values[idx]) else None
                    coefficients_payload.append({
                        "variable": column,
                        "coefficient": round(coef_value, 4),
                        "p_value": round(p_value, 4) if p_value is not None else None,
                        "significative": bool(p_value < 0.05) if p_value is not None else False,
                    })

                regression_multiple = {
                    "variables": x_cols,
                    "n": n_obs,
                    "r_squared": round(float(r_squared_multi), 4),
                    "coefficients": coefficients_payload,
                }

        logger.info(
            "Regression calculee pour %s avec %s variables explicatives",
            target_column,
            len(x_cols),
        )

        return {
            "colonne_cible": target_column,
            "n": len(y),
            "variables_testees": x_cols,
            "regressions": regressions_simples,
            "meilleure_variable": meilleure,
            "variables_significatives": [
                regression
                for regression in regressions_simples
                if regression["significative"]
            ],
            "regression_multiple": regression_multiple,
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 100

    base = np.random.normal(100, 10, n)
    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "temperature": base,
        "pression": base * 0.5 + np.random.normal(0, 5, n),
        "vitesse": np.random.normal(50, 5, n),
        "qualite": base * 1.2 + np.random.normal(0, 8, n),
    })

    state = {"target_column": "qualite"}
    specialist = RegressionSpecialist()
    result = specialist.run(df_test, state)

    print(f"Agent    : {result['agent']}")
    print(f"Status   : {result['status']}")
    print(
        "Meilleure variable : "
        f"{result['result']['meilleure_variable']['variable']}"
    )
    print(
        "R²       : "
        f"{result['result']['meilleure_variable']['r_squared']}"
    )
    print("\nToutes les regressions :")
    for regression in result["result"]["regressions"]:
        print(
            f"  {regression['variable']:12} -> "
            f"R²={regression['r_squared']:5} "
            f"sig={regression['significative']} | "
            f"{regression['interpretation']}"
        )
    print(f"\nTemps    : {result['execution_time_ms']}ms")
    print(f"Erreur   : {result['error']}")
