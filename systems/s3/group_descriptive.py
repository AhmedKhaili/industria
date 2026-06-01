"""
P6 Phase 2a — synthèse descriptive quali × quanti par groupe (niveau mesure).

Python pur ; prépare les données pour P7 (rapport type vrillage).
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd

from systems.s1.client_context import ClientContext

WorseDirection = Literal["upper", "lower", "both"]

MIN_N_GROUP = 6
MIN_N_CPK = 30
RANKING_METHOD_ID = "pct_hors_tol_then_cpk_then_risk_to_limit"
LEVEL_MEASURE = "measure"
INTERPRETATION_LIMITS = (
    "Les écarts entre groupes sont des associations statistiques au niveau mesure ; "
    "ils ne démontrent pas à eux seuls une causalité directe. "
    "Agrégation par OF : non incluse en phase 2a."
)

_F2_INTENTIONS = frozenset(
    {"comparaison_groupes", "diagnostic_causal", "analyse_complete"}
)
_F2_FAMILY = "bivariate_quali_quanti"


def _resolve_group_column(intent: dict) -> str | None:
    group_by = intent.get("group_by")
    if isinstance(group_by, list):
        return str(group_by[0]).strip() if group_by else None
    gb = str(group_by or "").strip()
    return gb or None


def _resolve_piece_operation(intent: dict) -> tuple[str | None, str | None]:
    filtres = intent.get("filtres") or {}
    piece = intent.get("piece") or filtres.get("piece")
    operation = intent.get("operation") or filtres.get("operation")
    if isinstance(piece, list):
        piece = piece[0] if piece else None
    return (
        str(piece).strip() if piece else None,
        str(operation).strip() if operation else None,
    )


def _variables(intent: dict) -> list[str]:
    raw = intent.get("variables") or []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    return [str(v).strip() for v in raw if str(v).strip()]


def infer_worse_direction(
    lti: float | None,
    lts: float | None,
    nominal: float | None,
) -> WorseDirection:
    """Direction métier du risque principal par rapport aux tolérances."""
    if lti is None or lts is None:
        return "both"
    if nominal is None:
        return "both"
    try:
        lti_f, lts_f, nom_f = float(lti), float(lts), float(nominal)
        span = max(lts_f - lti_f, 1e-12)
        dist_lti = abs(nom_f - lti_f)
        dist_lts = abs(lts_f - nom_f)
    except (TypeError, ValueError):
        return "both"
    if dist_lti <= span * 0.05:
        return "upper"
    if dist_lts <= span * 0.05:
        return "lower"
    if dist_lts < dist_lti:
        return "upper"
    if dist_lti < dist_lts:
        return "lower"
    return "both"


def risk_to_limit_score(
    mean: float,
    lti: float | None,
    lts: float | None,
    worse_direction: WorseDirection,
) -> float | None:
    """
    Score de risque par rapport aux limites — plus le score est élevé, plus le groupe est critique.

    upper : proche de LTS ou au-dessus de LTS.
    lower : proche de LTI ou sous LTI.
    both  : maximum des deux composantes.
    """
    if lti is None or lts is None:
        return None

    lti_f, lts_f = float(lti), float(lts)
    mean_f = float(mean)
    span = max(lts_f - lti_f, 1e-12)
    above_lts_penalty = span * 10.0

    def _upper() -> float:
        if mean_f >= lts_f:
            return above_lts_penalty + (mean_f - lts_f)
        # Plus la moyenne est proche de LTS (sans la dépasser), plus le score est élevé.
        return mean_f - lts_f

    def _lower() -> float:
        if mean_f <= lti_f:
            return above_lts_penalty + (lti_f - mean_f)
        # Plus la moyenne est proche de LTI (sans passer en dessous), plus le score est élevé.
        return lti_f - mean_f

    if worse_direction == "upper":
        return _upper()
    if worse_direction == "lower":
        return _lower()
    return max(_upper(), _lower())


def _wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) / n) + z2 / (4.0 * n * n)) / denom
    return center - margin, center + margin


def _ci95_mean(mean: float, std: float, n: int) -> dict[str, Any] | None:
    if n < 2 or std <= 0:
        return None
    half = 1.96 * (std / math.sqrt(n))
    low = round(mean - half, 6)
    high = round(mean + half, 6)
    return {"low": low, "high": high, "label": f"[{low} ; {high}]"}


def _compute_cp_cpk(series: np.ndarray, lsl: float, usl: float) -> tuple[float | None, float | None, str | None]:
    n = len(series)
    if n < MIN_N_CPK:
        return None, None, f"n<{MIN_N_CPK} pour Cp/Cpk fiable"
    mean = float(np.mean(series))
    std = float(np.std(series, ddof=1))
    if std <= 0:
        return None, None, "ecart-type nul"
    cp = (usl - lsl) / (6.0 * std)
    cpu = (usl - mean) / (3.0 * std)
    cpl = (mean - lsl) / (3.0 * std)
    cpk = min(cpu, cpl)
    return round(cp, 6), round(cpk, 6), None


def _out_of_tolerance(series: np.ndarray, lti: float, lts: float) -> tuple[int, float]:
    out = (series < lti) | (series > lts)
    count = int(np.sum(out))
    rate = float(np.mean(out) * 100.0) if len(series) else 0.0
    return count, round(rate, 4)


def _build_group_row(
    group_value: str,
    series: pd.Series,
    *,
    lti: float | None,
    lts: float | None,
    nominal: float | None,
    worse_direction: WorseDirection,
) -> dict[str, Any]:
    arr = series.dropna().to_numpy(dtype=float)
    n = int(len(arr))
    warnings: list[str] = []

    if n < MIN_N_GROUP:
        warnings.append(f"effectif_faible_n_{n}_inferieur_{MIN_N_GROUP}")

    row: dict[str, Any] = {
        "group_value": str(group_value),
        "n": n,
        "mean": None,
        "median": None,
        "std": None,
        "min": None,
        "max": None,
        "q1": None,
        "q3": None,
        "iqr": None,
        "out_of_tolerance_count": None,
        "out_of_tolerance_rate": None,
        "ci95_mean": None,
        "ci95_out_of_tolerance_rate": None,
        "cp": None,
        "cpk": None,
        "risk_to_limit_score": None,
        "rank": None,
        "severity_label": None,
        "warnings": warnings,
    }

    if n < 1:
        return row

    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1

    row.update(
        {
            "mean": round(mean, 6),
            "median": round(float(np.median(arr)), 6),
            "std": round(std, 6),
            "min": round(float(np.min(arr)), 6),
            "max": round(float(np.max(arr)), 6),
            "q1": round(q1, 6),
            "q3": round(q3, 6),
            "iqr": round(iqr, 6),
        }
    )

    row["ci95_mean"] = _ci95_mean(mean, std, n)

    if lti is not None and lts is not None:
        oot_count, oot_rate = _out_of_tolerance(arr, float(lti), float(lts))
        row["out_of_tolerance_count"] = oot_count
        row["out_of_tolerance_rate"] = oot_rate
        low_p, high_p = _wilson_ci(oot_count, n)
        if low_p is not None and high_p is not None:
            row["ci95_out_of_tolerance_rate"] = {
                "low": round(low_p * 100.0, 4),
                "high": round(high_p * 100.0, 4),
                "label": f"[{round(low_p * 100, 4)} % ; {round(high_p * 100, 4)} %]",
                "method": "wilson_score",
            }
        row["risk_to_limit_score"] = round(
            risk_to_limit_score(mean, lti, lts, worse_direction) or 0.0, 6
        )
        cp, cpk, cp_warn = _compute_cp_cpk(arr, float(lti), float(lts))
        row["cp"] = cp
        row["cpk"] = cpk
        if cp_warn:
            warnings.append(cp_warn)

    return row


def _rank_key(row: dict[str, Any]) -> tuple:
    pct = row.get("out_of_tolerance_rate")
    pct_key = float(pct) if pct is not None else -1.0
    cpk = row.get("cpk")
    cpk_key = float(cpk) if cpk is not None else float("inf")
    risk = row.get("risk_to_limit_score")
    risk_key = float(risk) if risk is not None else -1.0
    return (pct_key, -cpk_key, risk_key)


def _assign_ranks_and_labels(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    ranked = sorted(rows, key=_rank_key, reverse=True)
    n_groups = len(ranked)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
        if n_groups == 1:
            row["severity_label"] = "critique"
        elif i == 1:
            row["severity_label"] = "critique"
        elif i == n_groups:
            row["severity_label"] = "favorable"
        else:
            row["severity_label"] = "surveillance"
    return ranked


def should_run(intent: dict, families_executed: list[dict] | None = None) -> bool:
    if not _resolve_group_column(intent):
        return False
    intention = str(intent.get("intention") or "").strip()
    if intention in _F2_INTENTIONS:
        return True
    for fam in families_executed or []:
        if fam.get("family_id") == _F2_FAMILY:
            return True
    return False


def compute_for_variable(
    df: pd.DataFrame,
    intent: dict,
    context: ClientContext,
    variable: str,
) -> dict[str, Any] | None:
    group_col = _resolve_group_column(intent)
    if not group_col or group_col not in df.columns or variable not in df.columns:
        return None

    piece, operation = _resolve_piece_operation(intent)
    lti = lts = nominal = None
    if piece and operation:
        tol = context.get_tolerance(piece, operation, variable)
        if tol:
            try:
                lti = float(tol["lti"])
                lts = float(tol["lts"])
                nominal_raw = tol.get("nominal")
                nominal = float(nominal_raw) if nominal_raw is not None else None
            except (TypeError, ValueError, KeyError):
                pass

    worse_direction = infer_worse_direction(lti, lts, nominal)
    warnings: list[str] = [
        "Statistiques calculees au niveau mesure (une ligne par mesure capteur).",
        "Agregation par OF non incluse en phase 2a.",
    ]

    rows: list[dict[str, Any]] = []
    for group_value, sub in df.groupby(group_col, dropna=True):
        row = _build_group_row(
            str(group_value),
            sub[variable],
            lti=lti,
            lts=lts,
            nominal=nominal,
            worse_direction=worse_direction,
        )
        rows.append(row)

    rows = _assign_ranks_and_labels(rows)
    worst_group = rows[0]["group_value"] if rows else None
    best_group = rows[-1]["group_value"] if rows else None

    return {
        "variable": variable,
        "group_by": group_col,
        "level": LEVEL_MEASURE,
        "ranking_method": RANKING_METHOD_ID,
        "worse_direction": worse_direction,
        "rows": rows,
        "best_group": best_group,
        "worst_group": worst_group,
        "interpretation_limits": INTERPRETATION_LIMITS,
        "warnings": warnings,
    }


def compute_all(
    df: pd.DataFrame,
    intent: dict,
    context: ClientContext,
) -> list[dict[str, Any]]:
    """Une synthèse par variable quantitative de l'intent."""
    if not should_run(intent):
        return []
    group_col = _resolve_group_column(intent)
    if not group_col or group_col not in df.columns:
        return []

    out: list[dict[str, Any]] = []
    for variable in _variables(intent):
        if variable not in df.columns:
            continue
        block = compute_for_variable(df, intent, context, variable)
        if block:
            out.append(block)
    return out
