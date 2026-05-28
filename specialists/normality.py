"""Test de normalité — verdict Python (Shapiro ou Anderson-Darling)."""

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
from systems.stats_format import format_p_value

MIN_N = 8
LARGE_N = 5000
ALPHA = 0.05
KS_NOTE = (
    "KS avec moyenne et écart-type estimés sur les données — indicatif uniquement, "
    "non décisionnaire (pas Lilliefors)."
)


class NormalitySpecialist(BaseSpecialist):
    """Normalité : Shapiro (n < 5000) ou Anderson-Darling (n ≥ 5000)."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = MIN_N,
    ) -> dict:
        validation = super()._validate_input(df, target_column, min_rows)
        if not validation["valid"]:
            return validation
        series = pd.to_numeric(df[target_column], errors="coerce").dropna()
        if series.nunique(dropna=True) < 2:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Série constante — test de normalité impossible",
            }
        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        series = pd.to_numeric(df[target_column], errors="coerce").dropna()
        n = int(len(series))
        values = series.to_numpy(dtype=float)

        shapiro_stat = None
        shapiro_p = None
        ad_stat = None
        ad_critical = None
        ad_significatif = None
        ks_stat = None
        ks_p = None

        mu = float(np.mean(values))
        sigma = float(np.std(values, ddof=1)) if n > 1 else 0.0
        if sigma > 0:
            ks_stat, ks_p = stats.kstest(values, "norm", args=(mu, sigma))
            ks_stat = float(ks_stat)
            ks_p = float(ks_p)

        if n < LARGE_N:
            shapiro_stat, shapiro_p = stats.shapiro(values)
            shapiro_stat = float(shapiro_stat)
            shapiro_p = float(shapiro_p)
            verdict = "normale" if shapiro_p >= ALPHA else "non_normale"
            test_utilise = "Shapiro-Wilk"
            statistique = shapiro_stat
            p_value = shapiro_p
            test_verdict_source = "shapiro"
            regle_verdict = (
                f"Shapiro p >= {ALPHA}" if verdict == "normale" else f"Shapiro p < {ALPHA}"
            )
        else:
            ad_res = stats.anderson(values, dist="norm")
            ad_stat = float(ad_res.statistic)
            ad_critical = float(ad_res.critical_values[2])
            ad_significatif = ad_stat > ad_critical
            verdict = "non_normale" if ad_significatif else "normale"
            test_utilise = "Anderson-Darling"
            statistique = ad_stat
            p_value = None
            test_verdict_source = "anderson_darling"
            regle_verdict = (
                "Anderson-Darling au-delà du seuil critique 5 %"
                if ad_significatif
                else "Anderson-Darling sous le seuil critique 5 %"
            )

        p_value_display = (
            format_p_value(p_value)
            if p_value is not None
            else (
                "rejet de la normalité (seuil 5 % AD)"
                if verdict == "non_normale" and n >= LARGE_N
                else "compatible avec la normalité (seuil 5 % AD)"
            )
        )

        if verdict == "normale":
            normalite_phrase = (
                f"compatible avec une loi normale ({test_utilise}, {p_value_display})"
            )
        else:
            normalite_phrase = (
                f"écart significatif à la normale ({test_utilise}, {p_value_display})"
            )

        return {
            "colonne": target_column,
            "n": n,
            "verdict_normalite": verdict,
            "alpha": ALPHA,
            "regle_verdict": regle_verdict,
            "test_verdict_source": test_verdict_source,
            "test_utilise": test_utilise,
            "statistique": round(statistique, 4) if statistique is not None else None,
            "p_value": round(p_value, 4) if p_value is not None else None,
            "p_value_display": p_value_display,
            "normalite_phrase": normalite_phrase,
            "shapiro_stat": round(shapiro_stat, 4) if shapiro_stat is not None else None,
            "shapiro_p": round(shapiro_p, 4) if shapiro_p is not None else None,
            "ad_stat": round(ad_stat, 4) if ad_stat is not None else None,
            "ad_critical": round(ad_critical, 4) if ad_critical is not None else None,
            "ad_significatif": ad_significatif,
            "ks_stat": round(ks_stat, 4) if ks_stat is not None else None,
            "ks_p": round(ks_p, 4) if ks_p is not None else None,
            "ks_note": KS_NOTE if ks_stat is not None else None,
            "loi_candidate_aic": None,
        }
