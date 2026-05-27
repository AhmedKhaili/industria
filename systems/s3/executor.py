"""
Exécution des spécialistes avec pre-gates et tolérances YAML.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from specialists.anova_kruskal import AnovaKruskalSpecialist
from specialists.cp_cpk import CpCpkSpecialist
from specialists.ewma_cusum import EwmaCusumSpecialist
from specialists.mann_kendall import MannKendallSpecialist
from specialists.regression import RegressionSpecialist
from specialists.spc import SpcSpecialist
from specialists.zscore import ZScoreSpecialist

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

MIN_N_CP_ANOVA = 10

_SPECIALIST_CLASSES = {
    "cp_cpk": CpCpkSpecialist,
    "zscore": ZScoreSpecialist,
    "spc": SpcSpecialist,
    "anova_kruskal": AnovaKruskalSpecialist,
    "mann_kendall": MannKendallSpecialist,
    "ewma_cusum": EwmaCusumSpecialist,
    "regression": RegressionSpecialist,
}


def _skipped(agent: str, reason: str) -> dict:
    return {
        "agent": agent,
        "status": "skipped",
        "result": {"reason": reason},
        "error": None,
        "execution_time_ms": 0,
    }


def _resolve_piece_operation(intent: dict) -> tuple[str | None, str | None]:
    filtres = intent.get("filtres") or {}
    piece = intent.get("piece") or filtres.get("piece")
    operation = intent.get("operation") or filtres.get("operation")
    if isinstance(piece, list):
        piece = piece[0] if piece else None
    return piece, operation


def _resolve_group_column(intent: dict) -> str | None:
    group_by = intent.get("group_by")
    if isinstance(group_by, list):
        return group_by[0] if group_by else None
    return group_by


def _target_columns(df: pd.DataFrame, intent: dict) -> list[str]:
    variables = intent.get("variables") or []
    numeric = set(df.select_dtypes(include="number").columns)
    if variables:
        return [v for v in variables if v in numeric]
    return sorted(numeric)


def _tolerance_params(
    context: "ClientContext",
    piece: str | None,
    operation: str | None,
    tag: str,
) -> dict | None:
    if not piece or not operation:
        return None
    tol = context.get_tolerance(piece, operation, tag)
    if not tol:
        return None
    lti, lts = tol.get("lti"), tol.get("lts")
    if lti is None or lts is None:
        return None
    try:
        lsl = float(lti)
        usl = float(lts)
    except (TypeError, ValueError):
        return None
    if lsl >= usl:
        return None
    nominal = tol.get("nominal")
    target = float(nominal) if nominal is not None else (lsl + usl) / 2
    return {"LSL": lsl, "USL": usl, "target": target}


def _pre_gate_cp_cpk(
    df: pd.DataFrame,
    context: "ClientContext",
    intent: dict,
    target_column: str,
) -> str | None:
    if len(df) < MIN_N_CP_ANOVA:
        return f"n={len(df)} < {MIN_N_CP_ANOVA}"
    piece, operation = _resolve_piece_operation(intent)
    if _tolerance_params(context, piece, operation, target_column) is None:
        return "LTI/LTS absents dans le YAML pour cette variable"
    return None


def _pre_gate_anova(df: pd.DataFrame, intent: dict) -> str | None:
    if len(df) < MIN_N_CP_ANOVA:
        return f"n={len(df)} < {MIN_N_CP_ANOVA}"
    group_col = _resolve_group_column(intent)
    if not group_col:
        return "group_by absent dans l'intent"
    if group_col not in df.columns:
        return f"colonne group_by absente du df_propre : {group_col}"
    groups = df[group_col].dropna().unique()
    if len(groups) < 2:
        return "un seul groupe unique — ANOVA impossible"
    return None


def _build_state(intent: dict, target_column: str) -> dict:
    group_col = _resolve_group_column(intent)
    return {
        "target_column": target_column,
        "group_column": group_col,
        "errors": [],
        "agents_called": [],
    }


def _df_for_target(df: pd.DataFrame, target_column: str) -> pd.DataFrame:
    if target_column not in df.columns:
        return df.iloc[0:0]
    return df.dropna(subset=[target_column])


def _run_one(
    agent: str,
    df: pd.DataFrame,
    intent: dict,
    context: "ClientContext",
    target_column: str,
) -> dict:
    work_df = _df_for_target(df, target_column)
    if work_df.empty:
        return _skipped(agent, f"aucune valeur non nulle pour {target_column}")

    if agent == "cp_cpk":
        reason = _pre_gate_cp_cpk(work_df, context, intent, target_column)
        if reason:
            return _skipped(agent, reason)
    if agent == "anova_kruskal":
        reason = _pre_gate_anova(work_df, intent)
        if reason:
            return _skipped(agent, reason)

    cls = _SPECIALIST_CLASSES.get(agent)
    if cls is None:
        return {
            "agent": agent,
            "status": "error",
            "result": {},
            "error": f"Spécialiste inconnu : {agent}",
            "execution_time_ms": 0,
        }

    params: dict[str, Any] = {"target_column": target_column}
    if agent == "cp_cpk":
        piece, operation = _resolve_piece_operation(intent)
        tol_params = _tolerance_params(context, piece, operation, target_column)
        if tol_params:
            params.update(tol_params)
    if agent == "anova_kruskal":
        group_col = _resolve_group_column(intent)
        if group_col:
            params["group_column"] = group_col

    specialist = cls()
    raw = specialist.run(work_df, _build_state(intent, target_column), params)
    raw["agent"] = agent
    return raw


def run_all(
    df: pd.DataFrame,
    intent: dict,
    context: "ClientContext",
    specialists: list[str],
) -> dict:
    try:
        if df is None or df.empty:
            return {"error": "df_propre vide", "specialist_results": []}

        targets = _target_columns(df, intent)
        if not targets:
            return {
                "error": "Aucune colonne cible numérique dans df_propre",
                "specialist_results": [],
            }

        results: list[dict] = []
        multi_target = {"cp_cpk", "zscore", "spc", "mann_kendall", "ewma_cusum", "regression"}
        single_target = {"anova_kruskal"}

        for agent in specialists:
            if agent in single_target:
                col = targets[0]
                results.append(_run_one(agent, df, intent, context, col))
            elif agent in multi_target:
                for col in targets:
                    results.append(_run_one(agent, df, intent, context, col))
            else:
                results.append(
                    {
                        "agent": agent,
                        "status": "error",
                        "result": {},
                        "error": f"Spécialiste non orchestré : {agent}",
                        "execution_time_ms": 0,
                    }
                )

        return {"error": None, "specialist_results": results}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "specialist_results": []}
