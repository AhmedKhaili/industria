import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist


class CpCpkSpecialist(BaseSpecialist):
    """Process capability specialist for Cp/Cpk, Pp/Ppk, and EN9100 interpretation."""

    def __init__(self) -> None:
        """Store params temporarily so `_validate_input()` can also validate spec limits."""
        self._current_params: dict = {}

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and Cp/Cpk-specific constraints.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column.
            min_rows: Base interface parameter preserved for compatibility.

        Returns:
            dict: Validation payload.
        """
        validation = super()._validate_input(df, target_column, min_rows)
        if not validation["valid"]:
            return validation

        if len(df.index) < 30:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Minimum 30 points requis pour calcul Cp/Cpk fiable",
            }

        params = self._current_params or {}
        if "LSL" not in params or "USL" not in params:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "LSL et USL obligatoires pour calcul Cp/Cpk",
            }

        lsl = params.get("LSL")
        usl = params.get("USL")
        try:
            lsl = float(lsl)
            usl = float(usl)
        except (TypeError, ValueError):
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "LSL et USL doivent etre numeriques",
            }

        if not lsl < usl:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "LSL doit etre < USL",
            }

        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute process capability indices and EN9100-oriented interpretation.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters containing LSL, USL, and optional target.

        Returns:
            dict: Cp/Cpk metrics, normality check, and EN9100 compliance indicator.
        """
        LSL = float(params.get("LSL"))
        USL = float(params.get("USL"))
        target = float(params.get("target", (LSL + USL) / 2))

        series = df[target_column].dropna()

        mean = float(series.mean())
        std = float(series.std(ddof=1))

        if std <= 0:
            raise ValueError("Ecart-type nul: calcul Cp/Cpk impossible")

        Cp = (USL - LSL) / (6 * std)

        Cpu = (USL - mean) / (3 * std)
        Cpl = (mean - LSL) / (3 * std)
        Cpk = min(Cpu, Cpl)

        std_global = float(series.std(ddof=0))
        if std_global <= 0:
            raise ValueError("Ecart-type global nul: calcul Pp/Ppk impossible")

        Pp = (USL - LSL) / (6 * std_global)
        Ppu = (USL - mean) / (3 * std_global)
        Ppl = (mean - LSL) / (3 * std_global)
        Ppk = min(Ppu, Ppl)

        hors_LSL = float((series < LSL).sum() / len(series) * 100)
        hors_USL = float((series > USL).sum() / len(series) * 100)
        hors_limites = hors_LSL + hors_USL

        if len(series) <= 5000:
            _, shapiro_p = stats.shapiro(series)
            normale = bool(shapiro_p > 0.05)
        else:
            shapiro_p = None
            normale = None

        def interpreter_cp(valeur: float) -> str:
            if valeur >= 1.67:
                return "Excellent - EN9100 satisfait"
            elif valeur >= 1.33:
                return "Acceptable - surveillance requise"
            elif valeur >= 1.0:
                return "Limite - amelioration necessaire"
            else:
                return "Non capable - action corrective"

        return {
            "colonne": target_column,
            "LSL": LSL,
            "USL": USL,
            "target": target,
            "n": len(series),
            "mean": round(mean, 3),
            "std": round(std, 3),
            "Cp": round(Cp, 3),
            "Cpk": round(Cpk, 3),
            "Cpu": round(Cpu, 3),
            "Cpl": round(Cpl, 3),
            "Pp": round(Pp, 3),
            "Ppk": round(Ppk, 3),
            "hors_LSL_pct": round(hors_LSL, 3),
            "hors_USL_pct": round(hors_USL, 3),
            "hors_limites_pct": round(hors_limites, 3),
            "normale": normale,
            "shapiro_p": round(float(shapiro_p), 4) if shapiro_p is not None else None,
            "interpretation_Cp": interpreter_cp(Cp),
            "interpretation_Cpk": interpreter_cp(Cpk),
            "conforme_EN9100": bool(Cpk >= 1.33),
        }

    @staticmethod
    def _enrich_result(payload: dict) -> dict:
        """Alias métier + clés attendues par les agents rapport (cpk minuscule)."""
        out = dict(payload)
        cpk = payload.get("Cpk")
        cp = payload.get("Cp")
        out["cpk"] = cpk
        out["cp"] = cp
        out["mean"] = payload.get("mean")
        out["std"] = payload.get("std")
        out["lsl"] = payload.get("LSL")
        out["usl"] = payload.get("USL")
        out["n"] = payload.get("n")
        hors = payload.get("hors_limites_pct")
        if hors is not None:
            try:
                out["within_spec_pct"] = round(100.0 - float(hors), 3)
            except (TypeError, ValueError):
                out["within_spec_pct"] = None
        return out

    def run(
        self,
        df: pd.DataFrame,
        state: dict,
        params: dict | None = None,
    ) -> dict:
        """
        Expose params to `_validate_input()` without changing the shared base interface.
        """
        self._current_params = dict(params or {})
        try:
            result = super().run(df, state, params)
            if (
                result.get("status") == "success"
                and isinstance(result.get("result"), dict)
            ):
                result["result"] = self._enrich_result(result["result"])
            return result
        finally:
            self._current_params = {}


if __name__ == "__main__":
    np.random.seed(42)
    n = 100

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "mesure_mm": np.random.normal(50.0, 0.3, n),
    })

    state = {"target_column": "mesure_mm", "errors": [], "agents_called": []}
    params = {
        "LSL": 49.0,
        "USL": 51.0,
        "target": 50.0,
    }

    specialist = CpCpkSpecialist()
    result = specialist.run(df_test, state, params)

    print(f"Agent    : {result['agent']}")
    print(f"Status   : {result['status']}")
    print(f"Cp       : {result['result']['Cp']}")
    print(f"Cpk      : {result['result']['Cpk']}")
    print(f"Normale  : {result['result']['normale']}")
    print(f"EN9100   : {result['result']['conforme_EN9100']}")
    print(f"Interpret: {result['result']['interpretation_Cpk']}")
    print(f"Hors lim : {result['result']['hors_limites_pct']}%")
    print(f"Temps    : {result['execution_time_ms']}ms")
    print(f"Erreur   : {result['error']}")
