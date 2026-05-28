"""
Classement « pire matrice / pire groupe » — Python pur (règles YAML recommandations).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_DEFAULT_PIRE_MATRICE = {
    "variable_pivot": "cpk_min",
    "ex_aequo": "pct_hors_tolerance",
    "critere_groupe": "pct_hors_tolerance",
}


def _pire_matrice_cfg(context: "ClientContext") -> dict:
    raw = context.get_recommandations()
    cfg = dict(_DEFAULT_PIRE_MATRICE)
    block = raw.get("pire_matrice", {}) if isinstance(raw, dict) else {}
    if isinstance(block, dict):
        cfg.update(block)
    return cfg


def _canonical_agent(agent: str | None) -> str:
    name = str(agent or "").strip()
    mapping = {
        "CpCpkSpecialist": "cp_cpk",
        "AnovaKruskalSpecialist": "anova_kruskal",
    }
    return mapping.get(name, name.lower())


def _cpk_rows(specialist_results: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in specialist_results:
        if _canonical_agent(item.get("agent")) != "cp_cpk":
            continue
        if item.get("status") != "success":
            continue
        res = item.get("result") or {}
        cpk = res.get("Cpk", res.get("cpk"))
        col = res.get("colonne")
        if col is None or cpk is None:
            continue
        try:
            rows.append({"variable": str(col), "cpk": float(cpk)})
        except (TypeError, ValueError):
            continue
    return rows


def _pct_hors_tolerance(series: pd.Series, lti: float, lts: float) -> float:
    if series.empty:
        return 0.0
    out = (series < lti) | (series > lts)
    return float(out.mean() * 100.0)


def _select_pivot_variable(
    cpk_rows: list[dict],
    df: pd.DataFrame,
    intent: dict,
    context: "ClientContext",
    cfg: dict,
) -> dict | None:
    if not cpk_rows:
        return None
    min_cpk = min(r["cpk"] for r in cpk_rows)
    tied = [r for r in cpk_rows if abs(r["cpk"] - min_cpk) < 1e-9]
    if len(tied) == 1:
        return tied[0]

    piece = intent.get("piece")
    operation = intent.get("operation")
    filtres = intent.get("filtres") or {}
    if isinstance(piece, list):
        piece = piece[0] if piece else None
    piece = piece or filtres.get("piece")
    operation = operation or filtres.get("operation")

    best = tied[0]
    best_pct = -1.0
    for row in tied:
        var = row["variable"]
        if var not in df.columns or not piece or not operation:
            continue
        tol = context.get_tolerance(str(piece), str(operation), var)
        if not tol:
            continue
        try:
            lti, lts = float(tol["lti"]), float(tol["lts"])
        except (TypeError, ValueError, KeyError):
            continue
        pct = _pct_hors_tolerance(df[var].dropna(), lti, lts)
        if pct > best_pct:
            best_pct = pct
            best = {**row, "pct_hors_tolerance_global": pct}
    return best


def _resolve_group_column(intent: dict) -> str | None:
    group_by = intent.get("group_by")
    if isinstance(group_by, list):
        return group_by[0] if group_by else None
    return group_by


def _rank_groups_on_variable(
    df: pd.DataFrame,
    variable: str,
    group_col: str,
    context: "ClientContext",
    intent: dict,
    cfg: dict,
) -> list[dict]:
    if group_col not in df.columns or variable not in df.columns:
        return []

    piece = intent.get("piece")
    operation = intent.get("operation")
    filtres = intent.get("filtres") or {}
    if isinstance(piece, list):
        piece = piece[0] if piece else None
    piece = piece or filtres.get("piece")
    operation = operation or filtres.get("operation")

    lti, lts = None, None
    if piece and operation:
        tol = context.get_tolerance(str(piece), str(operation), variable)
        if tol:
            try:
                lti, lts = float(tol["lti"]), float(tol["lts"])
            except (TypeError, ValueError, KeyError):
                pass

    rankings: list[dict] = []
    for groupe, sub in df.groupby(group_col, dropna=True):
        serie = sub[variable].dropna()
        if serie.empty:
            continue
        pct = (
            _pct_hors_tolerance(serie, lti, lts)
            if lti is not None and lts is not None
            else 0.0
        )
        rankings.append(
            {
                "groupe": str(groupe),
                "median": round(float(serie.median()), 4),
                "n": int(len(serie)),
                "pct_hors_tolerance": round(pct, 2),
            }
        )

    critere = str(cfg.get("critere_groupe", "pct_hors_tolerance"))
    if critere == "pct_hors_tolerance":
        rankings.sort(key=lambda x: (-x["pct_hors_tolerance"], x["median"]))
    else:
        rankings.sort(key=lambda x: x["median"])
    return rankings


def compute_worst_group(
    df: pd.DataFrame,
    intent: dict,
    context: "ClientContext",
    specialist_results: list[dict],
) -> dict[str, Any]:
    """
    Détermine la variable pivot (Cpk min) et le groupe le plus dégradé (ex. matrice).
  Retour vide si non applicable.
    """
    cfg = _pire_matrice_cfg(context)
    group_col = _resolve_group_column(intent)
    if not group_col:
        return {}

    cpk_rows = _cpk_rows(specialist_results)
    pivot = _select_pivot_variable(cpk_rows, df, intent, context, cfg)
    if not pivot:
        return {}

    variable = pivot["variable"]
    rankings = _rank_groups_on_variable(df, variable, group_col, context, intent, cfg)
    if not rankings:
        return {}

    worst = rankings[0]
    return {
        "variable_pivot": variable,
        "cpk_pivot": pivot["cpk"],
        "group_col": group_col,
        "pire_groupe": worst["groupe"],
        "pire_groupe_pct_hors_tolerance": worst["pct_hors_tolerance"],
        "pire_groupe_median": worst["median"],
        "classement_groupes": rankings,
        "regle": cfg,
    }
