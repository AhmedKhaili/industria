"""
Agent Heatmap — matrice de corrélations Pearson/Spearman.
Python pur, zéro LLM.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from enterprise.report.charts import build_heatmap
from enterprise.report.formatters import format_number

logger = logging.getLogger(__name__)


class AgentHeatmap:
    """Calcule une matrice de corrélations et une heatmap PNG."""

    def run(
        self,
        df: pd.DataFrame,
        method: str = "pearson",
        min_cols: int = 2,
    ) -> dict:
        """
        Args:
            df: DataFrame avec colonnes numériques capteurs.
            method: ``pearson`` ou ``spearman``.
            min_cols: Nombre minimum de colonnes numériques.

        Returns:
            dict: matrice, top paires, PNG, ``error`` éventuel.
        """
        method_norm = (method or "pearson").strip().lower()
        if method_norm not in ("pearson", "spearman"):
            method_norm = "pearson"

        base = {
            "corr_matrix": {},
            "top_correlations": [],
            "heatmap_png": b"",
            "method": method_norm,
            "n_variables": 0,
            "error": None,
        }

        try:
            if df is None or df.empty:
                base["error"] = "DataFrame vide"
                base["heatmap_png"] = build_heatmap(
                    pd.DataFrame(), title="Corrélations"
                )
                return base

            numeric = self._numeric_columns(df)
            if len(numeric) < min_cols:
                base["error"] = (
                    f"Colonnes numériques insuffisantes: {len(numeric)} < {min_cols}"
                )
                base["heatmap_png"] = build_heatmap(
                    pd.DataFrame(), title="Corrélations"
                )
                return base

            corr_df = df[numeric].corr(method=method_norm)
            corr_dict = {
                str(row): {
                    str(col): float(corr_df.loc[row, col])
                    if not pd.isna(corr_df.loc[row, col])
                    else None
                    for col in corr_df.columns
                }
                for row in corr_df.index
            }

            top = self._top_correlation_pairs(corr_df)
            png = build_heatmap(corr_df, title=f"Corrélations ({method_norm})")

            base["corr_matrix"] = corr_dict
            base["top_correlations"] = top
            base["heatmap_png"] = png
            base["n_variables"] = len(numeric)
            return base
        except Exception as exc:
            logger.exception("AgentHeatmap.run failed")
            base["error"] = str(exc)
            try:
                base["heatmap_png"] = build_heatmap(
                    pd.DataFrame(), title="Corrélations"
                )
            except Exception:
                pass
            return base

    @staticmethod
    def _numeric_columns(df: pd.DataFrame) -> list[str]:
        cols = []
        for col in df.columns:
            if pd.api.types.is_bool_dtype(df[col]):
                continue
            if pd.api.types.is_numeric_dtype(df[col]):
                cols.append(col)
        return cols

    @staticmethod
    def _correlation_force(abs_r: float) -> str:
        if abs_r > 0.7:
            return "forte"
        if abs_r > 0.4:
            return "modérée"
        return "faible"

    def _top_correlation_pairs(
        self,
        corr_df: pd.DataFrame,
        max_pairs: int = 10,
    ) -> list[dict]:
        pairs: list[dict] = []
        cols = list(corr_df.columns)
        for i, col_a in enumerate(cols):
            for j in range(i + 1, len(cols)):
                col_b = cols[j]
                r = corr_df.loc[col_a, col_b]
                if pd.isna(r):
                    continue
                r_float = float(r)
                pairs.append({
                    "col_a": str(col_a),
                    "col_b": str(col_b),
                    "r": round(r_float, 4),
                    "force": self._correlation_force(abs(r_float)),
                })

        pairs.sort(key=lambda p: abs(p["r"]), reverse=True)
        return pairs[:max_pairs]
