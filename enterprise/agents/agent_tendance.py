"""
Agent Tendance — Mann-Kendall, Mann-Whitney, série temporelle PNG.
Python pur, zéro LLM.
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pymannkendall as mk
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from enterprise.report.charts import build_timeseries
from enterprise.report.formatters import format_dict, format_number, format_percentage

logger = logging.getLogger(__name__)

_TREND_FR = {
    "increasing": "hausse",
    "decreasing": "baisse",
    "no trend": "stable",
    "no trend detected": "stable",
}


class AgentTendance:
    """Analyse de tendance sur une série capteur (30 jours par défaut)."""

    def run(
        self,
        df: pd.DataFrame,
        target_col: str,
        window_days: int = 30,
    ) -> dict:
        """
        Mann-Kendall + comparaison hebdomadaire (Mann-Whitney).

        Returns:
            dict: tendance, p_value, PNG, ``error`` si n < 5.
        """
        base = self._empty_result()
        try:
            if df is None or df.empty:
                base["error"] = "DataFrame vide"
                base["timeseries_png"] = build_timeseries(
                    pd.DataFrame(), target_col, title="Tendance"
                )
                return base

            if target_col not in df.columns:
                base["error"] = f"Colonne absente: {target_col}"
                base["timeseries_png"] = build_timeseries(
                    pd.DataFrame(), target_col, title="Tendance"
                )
                return base

            work = self._prepare_series(df, target_col, window_days)
            serie = pd.to_numeric(work[target_col], errors="coerce").dropna()
            n_points = int(len(serie))

            base["n_points"] = n_points
            if n_points < 5:
                base["error"] = "Données insuffisantes (n<5)"
                base["timeseries_png"] = build_timeseries(
                    work, target_col, title="Tendance"
                )
                return base

            mk_result = mk.original_test(serie.to_numpy(dtype=float))
            trend = str(getattr(mk_result, "trend", "no trend"))
            p_value = float(getattr(mk_result, "p", 1.0))
            slope_sen = float(getattr(mk_result, "slope", 0.0))
            significant = bool(p_value < 0.05)
            direction_fr = _TREND_FR.get(trend.lower(), "stable")

            evolution_pct, mw_p, mw_sig = self._compare_weeks(work, target_col)

            resume = (
                f"{format_dict({'direction': direction_fr, 'slope': slope_sen})}, "
                f"p={format_number(p_value, 2)}"
            )
            if evolution_pct is not None:
                resume += f", évolution={format_percentage(evolution_pct / 100.0)}"

            anomalies = None
            if "type_anomalie" in work.columns or "anomalie" in work.columns:
                anomalies = work[
                    work.get("type_anomalie", work.get("anomalie", False)).astype(bool)
                ]

            png = build_timeseries(
                work,
                target_col,
                anomalies=anomalies,
                title=f"Tendance — {target_col}",
            )

            return {
                "trend": trend,
                "p_value": p_value,
                "slope_sen": slope_sen,
                "significant": significant,
                "evolution_pct": evolution_pct,
                "mann_whitney_p": mw_p,
                "mann_whitney_significant": mw_sig,
                "direction_fr": direction_fr,
                "resume": resume,
                "timeseries_png": png,
                "n_points": n_points,
                "error": None,
            }
        except Exception as exc:
            logger.exception("AgentTendance.run failed")
            base["error"] = str(exc)
            try:
                base["timeseries_png"] = build_timeseries(
                    df if df is not None else pd.DataFrame(),
                    target_col,
                    title="Tendance",
                )
            except Exception:
                pass
            return base

    def _empty_result(self) -> dict:
        return {
            "trend": None,
            "p_value": None,
            "slope_sen": None,
            "significant": None,
            "evolution_pct": None,
            "mann_whitney_p": None,
            "mann_whitney_significant": None,
            "direction_fr": None,
            "resume": None,
            "timeseries_png": b"",
            "n_points": 0,
            "error": None,
        }

    def _prepare_series(
        self,
        df: pd.DataFrame,
        target_col: str,
        window_days: int,
    ) -> pd.DataFrame:
        work = df.copy()
        time_col = self._detect_time_column(work)
        if time_col:
            work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
            work = work.dropna(subset=[time_col])
            cutoff = work[time_col].max() - timedelta(days=window_days)
            work = work[work[time_col] >= cutoff].sort_values(time_col)
        return work

    @staticmethod
    def _detect_time_column(df: pd.DataFrame) -> str | None:
        for col in df.columns:
            if col.lower() in ("timestamp", "time", "datetime", "date", "ts"):
                return col
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                return col
        if isinstance(df.index, pd.DatetimeIndex):
            work = df.reset_index()
            return work.columns[0]
        return None

    def _compare_weeks(
        self,
        df: pd.DataFrame,
        target_col: str,
    ) -> tuple[float | None, float | None, bool | None]:
        """Compare les 7 derniers jours vs les 7 jours précédents."""
        time_col = self._detect_time_column(df)
        if not time_col or time_col not in df.columns:
            return None, None, None

        work = df.copy()
        work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
        work = work.dropna(subset=[time_col, target_col]).sort_values(time_col)
        if work.empty:
            return None, None, None

        t_max = work[time_col].max()
        recent_start = t_max - timedelta(days=7)
        prev_start = t_max - timedelta(days=14)
        recent = work[work[time_col] > recent_start][target_col]
        previous = work[
            (work[time_col] > prev_start) & (work[time_col] <= recent_start)
        ][target_col]

        recent = pd.to_numeric(recent, errors="coerce").dropna()
        previous = pd.to_numeric(previous, errors="coerce").dropna()

        evolution_pct = None
        if len(recent) > 0 and len(previous) > 0:
            mean_prev = float(previous.mean())
            mean_recent = float(recent.mean())
            if mean_prev != 0:
                evolution_pct = round(
                    (mean_recent - mean_prev) / abs(mean_prev) * 100.0, 2
                )
            else:
                evolution_pct = 0.0

        if len(recent) == 0 or len(previous) == 0:
            return evolution_pct, None, None

        try:
            _stat, p_val = stats.mannwhitneyu(
                recent,
                previous,
                alternative="two-sided",
            )
            p_float = float(p_val)
            return evolution_pct, p_float, bool(p_float < 0.05)
        except Exception as exc:
            logger.warning("Mann-Whitney failed: %s", exc)
            return evolution_pct, None, None
