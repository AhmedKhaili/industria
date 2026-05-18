from abc import ABC, abstractmethod
import time
import logging
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from state.schema import AgentState

logger = logging.getLogger(__name__)


class BaseSpecialist(ABC):
    """Shared abstract contract for all IndustrIA specialist agents."""

    @abstractmethod
    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate common specialist inputs.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column.
            min_rows: Minimum required number of rows.

        Returns:
            dict: Validation result with `valid`, `warnings`, and `error`.
        """
        warnings: list[str] = []

        if df is None or df.empty:
            return {"valid": False, "warnings": warnings, "error": "DataFrame vide"}

        if target_column not in df.columns:
            return {
                "valid": False,
                "warnings": warnings,
                "error": f"Colonne cible absente: {target_column}",
            }

        if not pd.api.types.is_numeric_dtype(df[target_column]):
            return {
                "valid": False,
                "warnings": warnings,
                "error": f"Colonne cible non numérique: {target_column}",
            }

        if len(df.index) < min_rows:
            return {
                "valid": False,
                "warnings": warnings,
                "error": f"Nombre de lignes insuffisant: {len(df.index)} < {min_rows}",
            }

        series = pd.to_numeric(df[target_column], errors="coerce")
        if series.isna().any():
            return {
                "valid": False,
                "warnings": warnings,
                "error": "NaN détectés dans la colonne cible",
            }

        if np.isinf(series.to_numpy(dtype=float)).any():
            return {
                "valid": False,
                "warnings": warnings,
                "error": "Valeurs infinies détectées dans la colonne cible",
            }

        return {"valid": True, "warnings": warnings, "error": None}

    @abstractmethod
    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Run the pure specialist computation.

        Implementations must operate on `df.copy()`, handle NaN/infinite values,
        and round floating outputs to 3 decimals.
        """
        raise NotImplementedError

    def _round_nested(self, value: Any) -> Any:
        """
        Recursively round floating numeric outputs to 3 decimals.

        Args:
            value: Arbitrary nested result structure.

        Returns:
            Any: Normalized structure.
        """
        if isinstance(value, (float, np.floating)):
            return round(float(value), 3)
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, dict):
            return {k: self._round_nested(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._round_nested(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self._round_nested(v) for v in value)
        return value

    def run(
        self,
        df: pd.DataFrame,
        state: AgentState,
        params: dict | None = None,
    ) -> dict:
        """
        Run the standard specialist pipeline shared by all implementations.

        Args:
            df: Input DataFrame.
            state: Shared pipeline state.
            params: Optional specialist parameters.

        Returns:
            dict: Standardized specialist result payload.
        """
        start_time = time.time()
        agent_name = self.__class__.__name__
        params = params or {}

        if isinstance(state, dict):
            state.setdefault("errors", [])
            state.setdefault("agents_called", [])
            state["agents_called"].append(agent_name)

        numeric_columns = list(df.select_dtypes(include=[np.number]).columns) if df is not None else []

        logger.debug(
            f"[BASE.run] params = {params}"
        )
        logger.debug(
            f"[BASE.run] state.target_column = "
            f"{state.get('target_column', 'ABSENT') if isinstance(state, dict) else 'NO STATE'}"
        )

        target_column = (
            params.get("target_column")
            or state.get("target_column")
        ) if isinstance(state, dict) else params.get("target_column")
        if not target_column:
            target_column = numeric_columns[0] if numeric_columns else None

        if target_column is None:
            if isinstance(state, dict):
                state["errors"].append("Aucune colonne numérique")
            return self.format_error("Aucune colonne numérique", agent_name)

        validation = self._validate_input(df, target_column)
        if not validation["valid"]:
            if isinstance(state, dict) and validation["error"]:
                state["errors"].append(validation["error"])
            return self.format_error(validation["error"], agent_name)

        for warning in validation["warnings"]:
            logger.warning("%s: %s", agent_name, warning)

        try:
            result = self._compute(df.copy(), target_column, params)
        except Exception as exc:
            logger.exception("%s failed during compute", agent_name)
            if isinstance(state, dict):
                state["errors"].append(str(exc))
            return self.format_error(str(exc), agent_name)

        execution_time = int((time.time() - start_time) * 1000)
        return self.format_success(result, execution_time, agent_name)

    def format_success(
        self,
        result: dict,
        execution_time_ms: int,
        agent_name: str,
    ) -> dict:
        """
        Build the standard success payload.

        Args:
            result: Specialist result dictionary.
            execution_time_ms: Execution time in milliseconds.
            agent_name: Concrete specialist name.

        Returns:
            dict: Standardized success payload.
        """
        return {
            "agent": agent_name,
            "status": "success",
            "result": self._round_nested(result),
            "execution_time_ms": execution_time_ms,
            "error": None,
        }

    def format_error(
        self,
        error_message: str,
        agent_name: str = None,
    ) -> dict:
        """
        Build the standard error payload.

        Args:
            error_message: Human-readable error message.
            agent_name: Optional explicit agent name.

        Returns:
            dict: Standardized error payload.
        """
        return {
            "agent": agent_name or self.__class__.__name__,
            "status": "error",
            "result": {},
            "execution_time_ms": 0,
            "error": error_message,
        }


if __name__ == "__main__":
    class TestSpecialist(BaseSpecialist):
        def _validate_input(self, df, target_column, min_rows=5):
            return super()._validate_input(df, target_column, min_rows)

        def _compute(self, df, target_column, params):
            return {
                "mean": round(float(df[target_column].mean()), 3),
                "std": round(float(df[target_column].std()), 3),
            }

    np.random.seed(42)
    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=50, freq="1min"
        ),
        "capteur_a": np.random.normal(100, 5, 50),
    })

    state = {"target_column": "capteur_a", "errors": [], "agents_called": []}
    specialist = TestSpecialist()
    result = specialist.run(df_test, state)

    print(f"Agent  : {result['agent']}")
    print(f"Status : {result['status']}")
    print(f"Result : {result['result']}")
    print(f"Temps  : {result['execution_time_ms']}ms")
    print(f"Erreur : {result['error']}")
