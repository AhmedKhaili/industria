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


class SpcSpecialist(BaseSpecialist):
    """Shewhart SPC specialist with X-bar and R charts."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and add SPC-specific warnings.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            min_rows: Base interface parameter preserved for compatibility.

        Returns:
            dict: Validation payload with valid flag, warnings, and optional error.
        """
        validation = super()._validate_input(df, target_column, min_rows)
        if validation["valid"] and len(df.index) < 20:
            validation["warnings"].append("SPC moins fiable sous 20 points")
        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute X-bar and R Shewhart control charts on fixed-size subgroups.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters. Supported key: `subgroup_size`.

        Returns:
            dict: SPC summary with control limits and Nelson rule findings.
        """
        subgroup_size = int(params.get("subgroup_size", 5))

        constantes = {
            2: {"d2": 1.128, "D3": 0.0, "D4": 3.267},
            3: {"d2": 1.693, "D3": 0.0, "D4": 2.574},
            4: {"d2": 2.059, "D3": 0.0, "D4": 2.282},
            5: {"d2": 2.326, "D3": 0.0, "D4": 2.114},
            6: {"d2": 2.534, "D3": 0.0, "D4": 2.004},
            7: {"d2": 2.704, "D3": 0.076, "D4": 1.924},
            8: {"d2": 2.847, "D3": 0.136, "D4": 1.864},
            9: {"d2": 2.97, "D3": 0.184, "D4": 1.816},
            10: {"d2": 3.078, "D3": 0.223, "D4": 1.777},
        }

        n = min(max(subgroup_size, 2), 10)
        if n != subgroup_size:
            logger.warning(
                "subgroup_size=%s hors plage, ajuste a %s", subgroup_size, n
            )

        series = pd.to_numeric(df[target_column], errors="coerce").dropna()
        mean_global = float(series.mean())
        std_global = float(series.std(ddof=1))

        if std_global <= 0:
            raise ValueError("Ecart-type nul: SPC impossible a calculer")

        n_subgroups = len(series) // n
        if n_subgroups < 2:
            raise ValueError("Pas assez de sous-groupes pour calcul SPC fiable")

        c = constantes[n]

        subgroups: list[dict] = []
        for idx in range(n_subgroups):
            subgroup = series.iloc[idx * n:(idx + 1) * n]
            subgroups.append({
                "mean": float(subgroup.mean()),
                "range": float(subgroup.max() - subgroup.min()),
                "std": float(subgroup.std(ddof=1)),
            })

        means = [subgroup["mean"] for subgroup in subgroups]
        ranges = [subgroup["range"] for subgroup in subgroups]

        x_bar = float(np.mean(means))
        r_bar = float(np.mean(ranges))

        ucl_x = x_bar + 3 * r_bar / c["d2"] / np.sqrt(n)
        lcl_x = x_bar - 3 * r_bar / c["d2"] / np.sqrt(n)

        ucl_r = c["D4"] * r_bar
        lcl_r = c["D3"] * r_bar

        hors_x = [
            idx for idx, value in enumerate(means)
            if value > ucl_x or value < lcl_x
        ]
        hors_r = [
            idx for idx, value in enumerate(ranges)
            if value > ucl_r or value < lcl_r
        ]

        violations_nelson: list[str] = []
        for idx in range(len(means) - 8):
            segment = means[idx:idx + 9]
            if all(value > x_bar for value in segment):
                violations_nelson.append(
                    f"9 points consecutifs au-dessus de la moyenne (sous-groupe {idx})"
                )
            if all(value < x_bar for value in segment):
                violations_nelson.append(
                    f"9 points consecutifs en-dessous de la moyenne (sous-groupe {idx})"
                )

        z_scores = stats.zscore(series.to_numpy(dtype=float), ddof=1, nan_policy="omit")
        max_abs_zscore = float(np.nanmax(np.abs(z_scores)))

        sous_controle = (
            len(hors_x) == 0
            and len(hors_r) == 0
            and len(violations_nelson) == 0
        )

        logger.info(
            "SPC calcule pour %s avec %s sous-groupes de taille %s",
            target_column,
            n_subgroups,
            n,
        )

        return {
            "colonne": target_column,
            "n": len(series),
            "mean_global": round(mean_global, 3),
            "std_global": round(std_global, 3),
            "subgroup_size": n,
            "n_subgroups": n_subgroups,
            "x_bar": round(x_bar, 3),
            "R_bar": round(r_bar, 3),
            "UCL_x": round(ucl_x, 3),
            "LCL_x": round(lcl_x, 3),
            "UCL_r": round(ucl_r, 3),
            "LCL_r": round(lcl_r, 3),
            "hors_limites_x": hors_x,
            "hors_limites_r": hors_r,
            "violations_nelson": violations_nelson,
            "max_abs_zscore": round(max_abs_zscore, 3),
            "sous_controle": sous_controle,
            "interpretation": (
                "Processus sous controle statistique"
                if sous_controle
                else f"Processus hors controle - {len(hors_x)} points hors limites X"
            ),
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 100

    valeurs = np.random.normal(50, 2, n)
    valeurs[40:45] = 60

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "capteur_a": valeurs,
    })

    state = {"target_column": "capteur_a"}
    specialist = SpcSpecialist()
    result = specialist.run(df_test, state)

    print(f"Agent       : {result['agent']}")
    print(f"Status      : {result['status']}")
    print(f"Sous ctrl   : {result['result']['sous_controle']}")
    print(f"UCL_x       : {result['result']['UCL_x']}")
    print(f"LCL_x       : {result['result']['LCL_x']}")
    print(f"Hors lim X  : {result['result']['hors_limites_x']}")
    print(f"Nelson viol : {len(result['result']['violations_nelson'])}")
    print(f"Interpret   : {result['result']['interpretation']}")
    print(f"Temps       : {result['execution_time_ms']}ms")
    print(f"Erreur      : {result['error']}")
