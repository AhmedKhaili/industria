"""
Métriques portrait univarié — calcul Python pur (zéro LLM).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

_LOI_SCIPY = {
    "normale": "norm",
    "log_normale": "lognorm",
    "weibull": "weibull_min",
    "exponentielle": "expon",
    "uniforme": "uniform",
}

_LOI_DISPLAY = {
    "normale": "normale",
    "log_normale": "log-normale",
    "weibull": "Weibull",
    "exponentielle": "exponentielle",
    "uniforme": "uniforme",
}


def enrich_descriptive_stats(
    series: np.ndarray,
    *,
    lti: float | None,
    lts: float | None,
) -> dict[str, Any]:
    """Indicateurs tableau portrait (IC 95 %, IQR, CV %, outliers, P5/P95)."""
    n = int(len(series))
    if n < 1:
        return {}
    moyenne = float(np.mean(series))
    ecart_type = float(np.std(series, ddof=1)) if n > 1 else 0.0
    q1 = float(np.percentile(series, 25))
    q3 = float(np.percentile(series, 75))
    iqr = q3 - q1
    p5 = float(np.percentile(series, 5))
    p95 = float(np.percentile(series, 95))
    min_v = float(np.min(series))
    max_v = float(np.max(series))

    ic_half = 1.96 * (ecart_type / math.sqrt(n)) if n > 1 and ecart_type > 0 else 0.0
    ic_bas = round(moyenne - ic_half, 3)
    ic_haut = round(moyenne + ic_half, 3)
    cv_pct = round((ecart_type / moyenne) * 100, 2) if moyenne != 0 else None

    nb_outliers = 0
    if iqr > 0:
        low_fence = q1 - 1.5 * iqr
        high_fence = q3 + 1.5 * iqr
        nb_outliers = int(np.sum((series < low_fence) | (series > high_fence)))

    extras: dict[str, Any] = {
        "ic95_bas": ic_bas,
        "ic95_haut": ic_haut,
        "ic95_label": f"[{ic_bas} ; {ic_haut}]",
        "iqr": round(iqr, 3),
        "cv_pct": cv_pct,
        "nb_outliers": nb_outliers,
        "p5": round(p5, 3),
        "p95": round(p95, 3),
    }
    return extras


def _params_to_scipy_args(loi: str, parametres: dict) -> tuple[float, ...]:
    if not parametres:
        return ()
    ordered = [float(parametres[k]) for k in sorted(parametres.keys()) if k.startswith("p")]
    return tuple(ordered)


def distribution_percentiles(
    loi: str,
    parametres: dict,
    quantiles: tuple[float, ...] = (0.00135, 0.5, 0.99865),
) -> dict[str, float] | None:
    dist_name = _LOI_SCIPY.get(loi)
    if not dist_name:
        return None
    dist = getattr(stats, dist_name)
    try:
        args = _params_to_scipy_args(loi, parametres)
        keys = ("p00135", "p50", "p99865")
        return {
            keys[i]: float(dist.ppf(q, *args))
            for i, q in enumerate(quantiles)
            if i < len(keys)
        }
    except Exception:  # noqa: BLE001
        return None


def compute_adjusted_cpk(
    lti: float,
    lts: float,
    loi: str,
    parametres: dict,
) -> tuple[float | None, str]:
    """
    Cpk ajusté via percentiles de la loi fittée (P0,135 / P99,865).
    Retourne (valeur, libellé colonne).
    """
    if lts <= lti:
        return None, ""
    pct = distribution_percentiles(loi, parametres)
    if not pct:
        return None, ""
    p50 = pct.get("p50")
    p_low = pct.get("p00135")
    p_high = pct.get("p99865")
    if p50 is None or p_high == p_low:
        return None, ""
    denom_u = p_high - p50
    denom_l = p50 - p_low
    if denom_u <= 0 or denom_l <= 0:
        return None, ""
    cpk_u = (lts - p50) / denom_u
    cpk_l = (p50 - lti) / denom_l
    cpk_adj = round(float(min(cpk_u, cpk_l)), 3)
    label = _LOI_DISPLAY.get(loi, loi.replace("_", "-"))
    return cpk_adj, f"Cpk (ajusté {label})"


def fit_pdf_grid(
    loi: str,
    parametres: dict,
    x_min: float,
    x_max: float,
    n: int = 200,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Grille x + densité pour overlay histogramme."""
    dist_name = _LOI_SCIPY.get(loi)
    if not dist_name or x_max <= x_min:
        return None
    dist = getattr(stats, dist_name)
    try:
        args = _params_to_scipy_args(loi, parametres)
        xs = np.linspace(x_min, x_max, n)
        pdf = dist.pdf(xs, *args)
        if not np.all(np.isfinite(pdf)):
            return None
        return xs, pdf
    except Exception:  # noqa: BLE001
        return None
