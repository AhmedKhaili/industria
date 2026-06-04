"""
Nettoyage des données selon dataset.regles_nettoyage du YAML S0.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_FR_DECIMAL_COMMA = re.compile(r"^-?\d+,\d+$")


def _is_empty_value(series: pd.Series) -> pd.Series:
    """Valeurs manquantes ou chaîne vide (colonnes PAS souvent vides en LONG)."""
    as_str = series.astype(str).str.strip()
    return series.isna() | as_str.eq("") | as_str.str.lower().isin(("nan", "none"))


def _parse_numeric_locale(series: pd.Series) -> pd.Series:
    """
    Convertit en numérique ; accepte la virgule décimale française (ex. -18,5).
    """
    as_str = series.astype(str).str.strip()
    fr_mask = as_str.str.match(_FR_DECIMAL_COMMA.pattern, na=False)
    normalized = as_str.where(~fr_mask, as_str.str.replace(",", ".", regex=False))
    return pd.to_numeric(normalized, errors="coerce")


def _eval_condition(series: pd.Series, condition: str) -> pd.Series:
    cond = condition.strip()
    if cond.startswith("<="):
        threshold = float(cond[2:].strip())
        return series <= threshold
    if cond.startswith(">="):
        threshold = float(cond[2:].strip())
        return series >= threshold
    if cond.startswith("<"):
        threshold = float(cond[1:].strip())
        return series < threshold
    if cond.startswith(">"):
        threshold = float(cond[1:].strip())
        return series > threshold
    if cond.startswith("=="):
        threshold = float(cond[2:].strip())
        return series == threshold
    raise ValueError(f"Condition non supportée : {condition}")


def run(df: pd.DataFrame, context: "ClientContext") -> dict:
    """
    Applique regles_nettoyage. Lignes invalides → df_anomalies.
  Retourne df nettoyé + statistiques.
    """
    try:
        rules = context.regles_nettoyage or {}
        if not rules:
            return {
                "error": None,
                "df": df,
                "df_anomalies": pd.DataFrame(),
                "cleaning_stats": {"rules_applied": 0, "rules_skipped": 0},
            }

        working = df.copy()
        anomalies: list[pd.DataFrame] = []
        stats: dict = {"rules": {}, "rules_applied": 0, "rules_skipped": 0}

        for col, rule in rules.items():
            if col not in working.columns:
                stats["rules"][col] = {"status": "skipped", "reason": "colonne_absente"}
                stats["rules_skipped"] += 1
                continue

            action = rule.get("action", "")
            before = len(working)

            if action == "supprimer_si_invalide" and "valeurs_valides" in rule:
                valid = set(rule["valeurs_valides"])
                empty = _is_empty_value(working[col])
                mask_valid = working[col].isin(valid) | empty
                invalid = working[~mask_valid]
                if len(invalid):
                    anomalies.append(invalid)
                working = working[mask_valid]
                removed = before - len(working)
            elif action == "supprimer_si_invalide" and "condition" in rule:
                numeric = _parse_numeric_locale(working[col])
                empty = _is_empty_value(working[col])
                mask_valid = _eval_condition(numeric, rule["condition"]) & numeric.notna()
                mask_valid = mask_valid | empty
                invalid = working[~mask_valid]
                if len(invalid):
                    anomalies.append(invalid)
                working = working[mask_valid]
                removed = before - len(working)
            else:
                stats["rules"][col] = {"status": "skipped", "reason": "action_inconnue"}
                stats["rules_skipped"] += 1
                continue

            stats["rules"][col] = {
                "status": "applied",
                "rows_removed": removed,
                "rows_before": before,
                "rows_after": len(working),
            }
            stats["rules_applied"] += 1

        df_anomalies = pd.concat(anomalies, ignore_index=True) if anomalies else pd.DataFrame()
        stats["rows_in"] = len(df)
        stats["rows_out"] = len(working)
        stats["rows_anomalies"] = len(df_anomalies)

        return {
            "error": None,
            "df": working.reset_index(drop=True),
            "df_anomalies": df_anomalies,
            "cleaning_stats": stats,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "df": None,
            "df_anomalies": pd.DataFrame(),
            "cleaning_stats": {},
        }
