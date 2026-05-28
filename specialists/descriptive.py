"""Portrait descriptif d'une variable numérique (Python pur)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist

MIN_N = 5


class DescriptiveSpecialist(BaseSpecialist):
    """Statistiques descriptives + tolérances LTI/LTS si disponibles."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = MIN_N,
    ) -> dict:
        return super()._validate_input(df, target_column, min_rows)

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        series = pd.to_numeric(df[target_column], errors="coerce").dropna()
        n = int(len(series))
        if n < MIN_N:
            raise ValueError(f"Effectif insuffisant : n={n} < {MIN_N}")

        lti = params.get("lti")
        lts = params.get("lts")
        nominal = params.get("nominal")
        if lti is None and params.get("LSL") is not None:
            lti = params.get("LSL")
        if lts is None and params.get("USL") is not None:
            lts = params.get("USL")

        try:
            lti_f = float(lti) if lti is not None else None
        except (TypeError, ValueError):
            lti_f = None
        try:
            lts_f = float(lts) if lts is not None else None
        except (TypeError, ValueError):
            lts_f = None
        try:
            nominal_f = float(nominal) if nominal is not None else None
        except (TypeError, ValueError):
            nominal_f = None

        moyenne = float(series.mean())
        ecart_type = float(series.std(ddof=1)) if n > 1 else 0.0
        q1 = float(series.quantile(0.25))
        q3 = float(series.quantile(0.75))

        pct_hors: float | None = None
        if lti_f is not None and lts_f is not None and lts_f > lti_f:
            hors = (series < lti_f) | (series > lts_f)
            pct_hors = round(float(hors.sum()) / n * 100, 3)

        centrage: float | None = None
        if (
            nominal_f is not None
            and lti_f is not None
            and lts_f is not None
            and lts_f > lti_f
        ):
            centrage = round((moyenne - nominal_f) / (lts_f - lti_f), 3)

        skew = float(stats.skew(series, bias=False)) if n >= 3 else None
        kurt = float(stats.kurtosis(series, fisher=True, bias=False)) if n >= 4 else None

        dispersion = ecart_type
        if pct_hors is not None and pct_hors > 10:
            interp_disp = (
                f"Dispersion σ={dispersion:.3f} ; {pct_hors:.1f} % des mesures hors tolérances."
            )
        else:
            interp_disp = f"Dispersion σ={dispersion:.3f} sur {n} mesures."

        return {
            "colonne": target_column,
            "n": n,
            "moyenne": round(moyenne, 3),
            "mediane": round(float(series.median()), 3),
            "ecart_type": round(ecart_type, 3),
            "variance": round(ecart_type**2, 3),
            "skewness": round(skew, 3) if skew is not None else None,
            "kurtosis": round(kurt, 3) if kurt is not None else None,
            "min": round(float(series.min()), 3),
            "max": round(float(series.max()), 3),
            "q1": round(q1, 3),
            "q3": round(q3, 3),
            "iqr": round(q3 - q1, 3),
            "pct_hors_lti_lts": pct_hors,
            "centrage": centrage,
            "lti": lti_f,
            "lts": lts_f,
            "nominal": nominal_f,
            "interpretation_dispersion": interp_disp,
        }
