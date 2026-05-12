import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist

logger = logging.getLogger(__name__)


class EwmaCusumSpecialist(BaseSpecialist):
    """Detect gradual drifts with EWMA and abrupt shifts with CUSUM."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and add EWMA/CUSUM-specific warnings.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            min_rows: Base interface parameter preserved for compatibility.

        Returns:
            dict: Validation payload with valid flag, warnings, and optional error.
        """
        validation = super()._validate_input(df, target_column, min_rows)
        if validation["valid"] and len(df.index) < 20:
            validation["warnings"].append(
                "Serie courte - EWMA/CUSUM moins fiables"
            )
        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute EWMA and CUSUM control signals plus a simple trend summary.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters for EWMA and CUSUM.

        Returns:
            dict: Drift detection summary and trend interpretation.
        """
        lambda_ewma = float(params.get("lambda_ewma", 0.2))
        L = float(params.get("L", 3.0))
        k = float(params.get("k", 0.5))
        h = float(params.get("h", 4.0))

        if not 0.0 < lambda_ewma <= 1.0:
            raise ValueError("lambda_ewma doit etre strictement > 0 et <= 1")
        if L <= 0:
            raise ValueError("L doit etre strictement positif")
        if k < 0:
            raise ValueError("k doit etre >= 0")
        if h <= 0:
            raise ValueError("h doit etre strictement positif")

        series = pd.to_numeric(df[target_column], errors="coerce").dropna()
        mean_ref = float(series.mean())
        std_ref = float(series.std(ddof=1))

        if std_ref <= 0:
            raise ValueError("Ecart-type nul: EWMA/CUSUM impossibles a calculer")

        z = (series - mean_ref) / std_ref

        ewma = pd.Series(index=series.index, dtype=float)
        ewma.iloc[0] = z.iloc[0]

        for idx in range(1, len(z)):
            ewma.iloc[idx] = (
                lambda_ewma * z.iloc[idx]
                + (1 - lambda_ewma) * ewma.iloc[idx - 1]
            )

        sigma_ewma = std_ref * np.sqrt(
            lambda_ewma
            / (2 - lambda_ewma)
            * (1 - (1 - lambda_ewma) ** (2 * np.arange(1, len(z) + 1)))
        )

        UCL_ewma = mean_ref + L * sigma_ewma
        LCL_ewma = mean_ref - L * sigma_ewma

        ewma_original = ewma * std_ref + mean_ref
        ewma_alertes = (ewma_original > UCL_ewma) | (ewma_original < LCL_ewma)

        cusum_pos = np.zeros(len(z))
        cusum_neg = np.zeros(len(z))

        for idx in range(1, len(z)):
            cusum_pos[idx] = max(0, cusum_pos[idx - 1] + z.iloc[idx] - k)
            cusum_neg[idx] = max(0, cusum_neg[idx - 1] - z.iloc[idx] - k)

        cusum_pos = pd.Series(cusum_pos, index=series.index)
        cusum_neg = pd.Series(cusum_neg, index=series.index)
        cusum_alertes = (cusum_pos > h) | (cusum_neg > h)

        ewma_premier_alerte = None
        if ewma_alertes.any():
            ewma_premier_alerte = str(ewma_alertes[ewma_alertes].index[0])

        cusum_premier_alerte = None
        if cusum_alertes.any():
            cusum_premier_alerte = str(cusum_alertes[cusum_alertes].index[0])

        x = np.arange(len(series), dtype=float)
        scipy_stats = __import__("scipy").stats
        slope, intercept, r, p, se = scipy_stats.linregress(x, series.values)

        logger.info(
            "EWMA/CUSUM computed for %s with lambda=%s L=%s k=%s h=%s",
            target_column,
            lambda_ewma,
            L,
            k,
            h,
        )

        if abs(slope) < 0.001:
            tendance = "stable"
        elif slope > 0:
            tendance = "hausse progressive"
        else:
            tendance = "baisse progressive"

        derive_detectee = bool(ewma_alertes.any() or cusum_alertes.any())

        return {
            "colonne": target_column,
            "n": len(series),
            "mean_ref": round(mean_ref, 3),
            "std_ref": round(std_ref, 3),
            "ewma": {
                "lambda": lambda_ewma,
                "L": L,
                "alertes_count": int(ewma_alertes.sum()),
                "premier_alerte": ewma_premier_alerte,
                "pourcentage_alertes": round(
                    float(ewma_alertes.sum() / len(series) * 100), 3
                ),
            },
            "cusum": {
                "k": k,
                "h": h,
                "alertes_count": int(cusum_alertes.sum()),
                "premier_alerte": cusum_premier_alerte,
                "cusum_pos_max": round(float(cusum_pos.max()), 3),
                "cusum_neg_max": round(float(cusum_neg.max()), 3),
            },
            "tendance": {
                "direction": tendance,
                "slope": round(float(slope), 6),
                "r_squared": round(float(r ** 2), 4),
                "p_value": round(float(p), 4),
                "significative": bool(p < 0.05),
            },
            "derive_detectee": derive_detectee,
            "interpretation": (
                "Derive detectee - processus hors controle"
                if derive_detectee
                else "Processus stable - aucune derive"
            ),
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 200

    valeurs = np.concatenate([
        np.random.normal(100, 2, 100),
        np.linspace(100, 115, 50) + np.random.normal(0, 2, 50),
        np.random.normal(115, 2, 50),
    ])

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "capteur_a": valeurs,
    })

    state = {"target_column": "capteur_a"}
    specialist = EwmaCusumSpecialist()
    result = specialist.run(df_test, state)

    print(f"Agent    : {result['agent']}")
    print(f"Status   : {result['status']}")
    print(f"Derive   : {result['result']['derive_detectee']}")
    print(f"Tendance : {result['result']['tendance']['direction']}")
    print(f"Slope    : {result['result']['tendance']['slope']}")
    print(f"EWMA alertes : {result['result']['ewma']['alertes_count']}")
    print(f"CUSUM alertes: {result['result']['cusum']['alertes_count']}")
    print(f"Interpret: {result['result']['interpretation']}")
    print(f"Temps    : {result['execution_time_ms']}ms")
    print(f"Erreur   : {result['error']}")
