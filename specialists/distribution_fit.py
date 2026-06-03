"""Ajustement de lois — meilleur modèle selon AIC (Python pur)."""

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

MIN_N = 50
IDENTICAL_RATIO_MAX = 0.5

LOIS = (
    ("normale", "norm"),
    ("log_normale", "lognorm"),
    ("weibull", "weibull_min"),
    ("exponentielle", "expon"),
    ("uniforme", "uniform"),
)


def _aic_bic(loglik: float, k: int, n: int) -> tuple[float, float]:
    aic = 2 * k - 2 * loglik
    bic = k * np.log(n) - 2 * loglik
    return float(aic), float(bic)


class DistributionFitSpecialist(BaseSpecialist):
    """Compare 5 lois ; loi_retenue = argmin(AIC) parmi ajustements valides."""

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
        n = len(series)
        if n < MIN_N:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": f"Effectif insuffisant pour ajustement : n={n} < {MIN_N}",
            }
        mode_ratio = float(series.value_counts(normalize=True).iloc[0])
        if mode_ratio > IDENTICAL_RATIO_MAX:
            return {
                "valid": False,
                "warnings": validation["warnings"] + [
                    f">{IDENTICAL_RATIO_MAX * 100:.0f} % de valeurs identiques"
                ],
                "error": "Série quasi constante — ajustement de loi non fiable",
            }
        return validation

    def _fit_one(self, loi_id: str, dist_name: str, values: np.ndarray) -> dict:
        n = len(values)
        dist = getattr(stats, dist_name)
        try:
            if loi_id == "log_normale" and np.any(values <= 0):
                return {
                    "loi": loi_id,
                    "aic": None,
                    "bic": None,
                    "parametres": {},
                    "ajustement_ok": False,
                }
            if loi_id == "exponentielle" and np.any(values < 0):
                return {
                    "loi": loi_id,
                    "aic": None,
                    "bic": None,
                    "parametres": {},
                    "ajustement_ok": False,
                }
            params = dist.fit(values)
            logpdf = dist.logpdf(values, *params)
            if not np.all(np.isfinite(logpdf)):
                raise ValueError("logpdf non fini")
            loglik = float(np.sum(logpdf))
            k = len(params)
            aic, bic = _aic_bic(loglik, k, n)
            param_dict = {
                f"p{i}": round(float(p), 4) for i, p in enumerate(params)
            }
            return {
                "loi": loi_id,
                "aic": round(aic, 3),
                "bic": round(bic, 3),
                "parametres": param_dict,
                "ajustement_ok": True,
            }
        except Exception:  # noqa: BLE001
            return {
                "loi": loi_id,
                "aic": None,
                "bic": None,
                "parametres": {},
                "ajustement_ok": False,
            }

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        series = pd.to_numeric(df[target_column], errors="coerce").dropna()
        values = series.to_numpy(dtype=float)
        n = int(len(values))

        candidats = [self._fit_one(loi_id, dist_name, values) for loi_id, dist_name in LOIS]
        valides = [c for c in candidats if c.get("ajustement_ok") and c.get("aic") is not None]
        if not valides:
            raise ValueError("Aucune loi ajustée avec succès")

        valides.sort(key=lambda x: float(x["aic"]))
        best = valides[0]
        loi_retenue = str(best["loi"])
        aic_min = float(best["aic"])
        bic_min = float(best["bic"])

        interpretation_loi = (
            f"Meilleur ajustement parmi les lois testées : {loi_retenue} (AIC = {aic_min:.3f})"
        )

        ranking = [
            {
                "loi": c["loi"],
                "aic": c["aic"],
                "bic": c["bic"],
                "ajustement_ok": c["ajustement_ok"],
            }
            for c in sorted(
                candidats,
                key=lambda x: (x["aic"] is None, float(x["aic"]) if x["aic"] is not None else 0),
            )
        ]

        return {
            "colonne": target_column,
            "n": n,
            "loi_retenue": loi_retenue,
            "loi_candidate_aic": loi_retenue,
            "parametres": dict(best.get("parametres") or {}),
            "aic_min": round(aic_min, 3),
            "bic_min": round(bic_min, 3),
            "ranking": ranking,
            "classement": ranking,
            "interpretation_loi": interpretation_loi,
            "libelle_client": "meilleur ajustement selon AIC/BIC",
        }
