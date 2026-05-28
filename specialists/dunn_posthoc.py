"""
Comparaison post-hoc de Dunn — paires de groupes après Kruskal/ANOVA significatif.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist
from systems.stats_format import format_p_value

logger = logging.getLogger(__name__)


class DunnPosthocSpecialist(BaseSpecialist):
    """Paires de groupes significativement différentes (Dunn + correction Bonferroni)."""

    def __init__(self) -> None:
        self._current_params: dict = {}

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        validation = super()._validate_input(df, target_column, min_rows)
        if not validation["valid"]:
            return validation
        group_col = self._current_params.get("group_column")
        if not group_col or group_col not in df.columns:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "group_column obligatoire pour Dunn post-hoc",
            }
        groups = df[group_col].dropna().unique()
        if len(groups) < 2:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Minimum 2 groupes pour Dunn post-hoc",
            }
        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        import scikit_posthocs as sp

        group_col = str(params["group_column"])
        alpha = float(params.get("alpha", 0.05))
        work = df[[target_column, group_col]].dropna()
        pmat = sp.posthoc_dunn(
            work,
            val_col=target_column,
            group_col=group_col,
            p_adjust="bonferroni",
        )

        paires: list[dict] = []
        cols = list(pmat.columns)
        for i, g1 in enumerate(cols):
            for g2 in cols[i + 1 :]:
                try:
                    pval = float(pmat.loc[g2, g1])
                except (KeyError, TypeError, ValueError):
                    continue
                if pval < alpha:
                    p_disp = format_p_value(pval)
                    paires.append(
                        {
                            "groupe_a": str(g1),
                            "groupe_b": str(g2),
                            "p_value": round(pval, 4),
                            "p_value_display": p_disp,
                            "significatif": True,
                            "libelle": (
                                f"{g1} vs {g2} : {p_disp} — différence significative"
                            ),
                        }
                    )

        paires.sort(key=lambda x: x["p_value"])
        return {
            "colonne_cible": target_column,
            "colonne_groupe": group_col,
            "methode": "Dunn",
            "correction": "bonferroni",
            "alpha": alpha,
            "paires_significatives": paires,
            "n_paires": len(paires),
            "interpretation": (
                f"{len(paires)} paire(s) de groupes significativement différente(s) "
                f"(Dunn, correction Bonferroni, α={alpha})."
                if paires
                else "Aucune paire significative au post-hoc Dunn."
            ),
        }

    def run(
        self,
        df: pd.DataFrame,
        state: dict,
        params: dict | None = None,
    ) -> dict:
        self._current_params = dict(params or {})
        return super().run(df, state, params)
