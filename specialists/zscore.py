import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist


class ZScoreSpecialist(BaseSpecialist):
    """Univariate anomaly detection using robust rolling MAD z-scores."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate the specialist input and add z-score-specific warnings.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column.
            min_rows: Minimum required row count.

        Returns:
            dict: Validation payload with valid flag, warnings, and optional error.
        """
        validation = super()._validate_input(df, target_column, min_rows)
        if validation["valid"] and len(df.index) < 10:
            validation["warnings"].append(
                "Série courte — résultats moins fiables"
            )
        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute robust rolling MAD z-scores and classify anomalies.

        Args:
            df: Input DataFrame.
            target_column: Numeric target column.
            params: Specialist parameters.

        Returns:
            dict: Computed z-score metrics and anomaly classifications.
        """
        window = params.get("window", 20)
        seuil = params.get("seuil", 3.0)
        min_consecutive = params.get("min_consecutive", 5)

        series = pd.to_numeric(df[target_column].copy(), errors="coerce")

        rolling_median = series.rolling(
            window=window, min_periods=1
        ).median()

        mad = series.rolling(
            window=window, min_periods=1
        ).apply(
            lambda x: np.median(
                np.abs(x - np.median(x))), raw=True
        )

        positive_mad = mad[mad > 0]
        replacement = positive_mad.median() if not positive_mad.empty else 1
        mad = mad.replace(0, replacement)
        mad = mad.fillna(1)

        zscore = 0.6745 * (series - rolling_median) / mad

        above_threshold = zscore.abs() > seuil

        groups = (above_threshold != above_threshold.shift()).cumsum()
        consecutive_counts = above_threshold.groupby(
            groups).transform("sum")

        classification = pd.Series(
            "normal", index=series.index)
        classification.loc[above_threshold &
                           (consecutive_counts < min_consecutive)] = \
            "bruit_capteur"
        classification.loc[above_threshold &
                           (consecutive_counts >= min_consecutive)] = \
            "anomalie_process"

        anomalies = df[classification != "normal"]

        return {
            "colonne": target_column,
            "window": window,
            "seuil": seuil,
            "total_points": len(series),
            "anomalies_count": int(
                (classification != "normal").sum()),
            "bruit_capteur_count": int(
                (classification == "bruit_capteur").sum()),
            "anomalie_process_count": int(
                (classification == "anomalie_process").sum()),
            "max_zscore": round(
                float(zscore.abs().max()), 3),
            "mean_zscore": round(
                float(zscore.abs().mean()), 3),
            "pourcentage_anomalies": round(
                float((classification != "normal").sum()
                      / len(series) * 100), 3),
            "anomalies_timestamps": [
                str(t) for t in anomalies.index[:20]
            ] if "timestamp" in df.columns else [],
            "classification": classification.tolist(),
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 200

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "capteur_a": np.random.normal(100, 5, n),
    })

    df_test.loc[20, "capteur_a"] = 200
    df_test.loc[50, "capteur_a"] = 200
    df_test.loc[100:107, "capteur_a"] = 150

    state = {"target_column": "capteur_a", "errors": [], "agents_called": []}
    specialist = ZScoreSpecialist()
    result = specialist.run(df_test, state)

    print(f"Agent    : {result['agent']}")
    print(f"Status   : {result['status']}")
    print(f"Total    : {result['result']['total_points']}")
    print(f"Anomalies: {result['result']['anomalies_count']}")
    print(f"Bruit    : {result['result']['bruit_capteur_count']}")
    print(f"Process  : {result['result']['anomalie_process_count']}")
    print(f"Max zscore: {result['result']['max_zscore']}")
    print(f"Temps    : {result['execution_time_ms']}ms")
    print(f"Erreur   : {result['error']}")
