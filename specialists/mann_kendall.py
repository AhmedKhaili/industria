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


class MannKendallSpecialist(BaseSpecialist):
    """Non-parametric monotonic trend detection using the Mann-Kendall test."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and add Mann-Kendall-specific warnings.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            min_rows: Base interface parameter preserved for compatibility.

        Returns:
            dict: Validation payload with valid flag, warnings, and optional error.
        """
        validation = super()._validate_input(df, target_column, min_rows)
        if validation["valid"] and len(df.index) < 10:
            validation["warnings"].append(
                "Mann-Kendall moins fiable sous 10 points"
            )
        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute the Mann-Kendall trend test and Sen's slope.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters containing optional `alpha`.

        Returns:
            dict: Mann-Kendall statistics, Sen slope, and interpretation.
        """
        alpha = float(params.get("alpha", 0.05))
        if not 0 < alpha < 1:
            raise ValueError("alpha doit etre compris entre 0 et 1")

        series = pd.to_numeric(df[target_column], errors="coerce").dropna().to_numpy(dtype=float)
        n = len(series)

        S = 0
        for i in range(n - 1):
            for j in range(i + 1, n):
                diff = series[j] - series[i]
                if diff > 0:
                    S += 1
                elif diff < 0:
                    S -= 1

        _, counts = np.unique(series, return_counts=True)
        ties = counts[counts > 1]

        var_S = (n * (n - 1) * (2 * n + 5)) / 18
        for t in ties:
            var_S -= (t * (t - 1) * (2 * t + 5)) / 18

        if var_S <= 0:
            Z = 0.0
            p_value = 1.0
        else:
            if S > 0:
                Z = (S - 1) / np.sqrt(var_S)
            elif S < 0:
                Z = (S + 1) / np.sqrt(var_S)
            else:
                Z = 0.0

            p_value = 2 * (1 - stats.norm.cdf(abs(Z)))

        slopes: list[float] = []
        for i in range(n - 1):
            for j in range(i + 1, n):
                slopes.append((series[j] - series[i]) / (j - i))

        sen_slope = float(np.median(slopes)) if slopes else 0.0
        significatif = bool(p_value < alpha)

        if not significatif:
            tendance = "aucune tendance significative"
        elif Z > 0:
            tendance = "tendance a la hausse"
        else:
            tendance = "tendance a la baisse"

        variation_totale = sen_slope * n

        logger.info(
            "Mann-Kendall calcule pour %s avec n=%s alpha=%s",
            target_column,
            n,
            alpha,
        )

        return {
            "colonne": target_column,
            "n": n,
            "S": int(S),
            "Z": round(float(Z), 4),
            "p_value": round(float(p_value), 4),
            "alpha": alpha,
            "significatif": significatif,
            "tendance": tendance,
            "sen_slope": round(sen_slope, 6),
            "variation_totale_estimee": round(variation_totale, 3),
            "interpretation": (
                f"Tendance {tendance} detectee "
                f"(p={round(float(p_value), 4)}, "
                f"pente Sen={round(sen_slope, 4)} "
                f"unites/observation)"
                if significatif
                else f"Aucune tendance significative (p={round(float(p_value), 4)})"
            ),
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 100

    serie_hausse = np.linspace(0, 10, n) + np.random.normal(0, 1, n)
    serie_stable = np.random.normal(50, 5, n)

    for nom, valeurs in [
        ("hausse", serie_hausse),
        ("stable", serie_stable),
    ]:
        df_test = pd.DataFrame({
            "timestamp": pd.date_range(
                "2026-01-01", periods=n, freq="1min"
            ),
            "capteur": valeurs,
        })

        state = {"target_column": "capteur"}
        specialist = MannKendallSpecialist()
        result = specialist.run(df_test, state)

        print(f"\n{'=' * 40}")
        print(f"Serie     : {nom}")
        print(f"Status    : {result['status']}")
        print(f"Tendance  : {result['result']['tendance']}")
        print(f"p-value   : {result['result']['p_value']}")
        print(f"Sen slope : {result['result']['sen_slope']}")
        print(f"Interpret : {result['result']['interpretation']}")
        print(f"Temps     : {result['execution_time_ms']}ms")
        print(f"Erreur    : {result['error']}")
