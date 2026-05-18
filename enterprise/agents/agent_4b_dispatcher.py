import asyncio
import importlib
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from state.schema import AgentState

logger = logging.getLogger(__name__)

GOAL_TO_SPECIALISTS = {
    "detection_anomalies": [
        "zscore",
        "ewma_cusum",
        "spc",
    ],
    "comparaison_groupes": [
        "anova_kruskal",
        "pivot",
    ],
    "correlation": [
        "correlation",
    ],
    "capabilite": [
        "cp_cpk",
        "spc",
        "pivot",
    ],
    "tendance": [
        "mann_kendall",
        "ewma_cusum",
        "regression",
    ],
    "cross_process": [
        "correlation",
        "zscore",
        "pivot",
    ],
    "simulation": [
        "regression",
        "pivot",
    ],
    "resume": [
        "zscore",
        "cp_cpk",
        "spc",
        "pivot",
    ],
}

SPECIALIST_CLASSES = {
    "zscore": "ZScoreSpecialist",
    "cp_cpk": "CpCpkSpecialist",
    "correlation": "CorrelationSpecialist",
    "anova_kruskal": "AnovaKruskalSpecialist",
    "ewma_cusum": "EwmaCusumSpecialist",
    "spc": "SpcSpecialist",
    "regression": "RegressionSpecialist",
    "pivot": "PivotSpecialist",
    "fourier": "FourierSpecialist",
    "mann_kendall": "MannKendallSpecialist",
}


class DispatcherAgent:
    """Dispatch specialist agents deterministically from the classified intention."""

    def _pre_gate(
        self,
        df: pd.DataFrame | None,
        goal: str,
        specialists: list[str],
        intention: dict | None = None,
    ) -> dict:
        """
        Filter the requested specialists based on minimal data sufficiency rules.

        Args:
            df: Input DataFrame to analyze.
            goal: Classified analytical goal.
            specialists: Initial specialist list for the goal.
            intention: Intention payload from agent 4a.

        Returns:
            dict: Blocking status, valid specialists, and warnings.
        """
        warnings: list[str] = []

        if df is None or df.empty:
            warnings.append("DataFrame vide ou absent - aucun specialiste executable")
            return {
                "blocked": True,
                "specialists_valides": [],
                "warnings": warnings,
            }

        if len(df.index) < 5:
            warnings.append("Donnees insuffisantes: moins de 5 lignes")
            logger.warning(
                "Pre-gate bloque (goal=%s): %s lignes, specialists=%s",
                goal,
                len(df.index),
                specialists,
            )
            return {
                "blocked": True,
                "specialists_valides": [],
                "warnings": warnings,
            }

        specialists_valides = list(specialists)
        numeric_columns = list(df.select_dtypes(include=[np.number]).columns)

        if len(df.index) < 30 and "cp_cpk" in specialists_valides:
            specialists_valides.remove("cp_cpk")
            warning = "cp_cpk retire: moins de 30 lignes"
            logger.warning(warning)
            warnings.append(warning)

        if len(df.index) < 30 and "anova_kruskal" in specialists_valides:
            specialists_valides.remove("anova_kruskal")
            warning = "anova_kruskal retire: moins de 30 lignes"
            logger.warning(warning)
            warnings.append(warning)

        if len(numeric_columns) < 2 and "correlation" in specialists_valides:
            specialists_valides.remove("correlation")
            warning = "correlation retire: moins de 2 colonnes numeriques"
            logger.warning(warning)
            warnings.append(warning)

        if len(numeric_columns) < 2 and "regression" in specialists_valides:
            specialists_valides.remove("regression")
            warning = "regression retire: moins de 2 colonnes numeriques"
            logger.warning(warning)
            warnings.append(warning)

        if "anova_kruskal" in specialists_valides:
            group_column = None
            if isinstance(intention, dict):
                candidate = intention.get("group_col")
                if isinstance(candidate, str) and candidate in df.columns:
                    group_column = candidate

            if group_column is None:
                group_column = self._pick_categorical_column(df)

            if group_column is None:
                specialists_valides.remove("anova_kruskal")
                warning = "Pas de colonne catégorielle disponible"
                logger.warning(warning)
                warnings.append(warning)
            elif df[group_column].nunique(dropna=True) < 2:
                specialists_valides.remove("anova_kruskal")
                warning = (
                    f"anova_kruskal retire: {group_column} "
                    "n'a qu'un groupe distinct"
                )
                logger.warning(warning)
                warnings.append(warning)

        return {
            "blocked": len(specialists_valides) == 0,
            "specialists_valides": specialists_valides,
            "warnings": warnings,
        }

    def _pick_categorical_column(self, df: pd.DataFrame | None) -> str | None:
        """
        Pick a categorical column for group comparisons.

        Prefers industrial labels (`modele`, etc.) when they have at least two
        distinct values; otherwise falls back to the first object/string column.

        Args:
            df: Candidate analysis DataFrame.

        Returns:
            str | None: First categorical-like column, if any.
        """
        if df is None or df.empty:
            return None

        for preferred in ("modele", "categorie", "machine", "numero_programme"):
            if preferred not in df.columns:
                continue
            series = df[preferred]
            if (
                pd.api.types.is_object_dtype(series)
                or pd.api.types.is_string_dtype(series)
                or pd.api.types.is_categorical_dtype(series)
            ) and series.nunique(dropna=True) >= 2:
                return preferred

        for column in df.columns:
            series = df[column]
            if (
                pd.api.types.is_object_dtype(series)
                or pd.api.types.is_string_dtype(series)
                or pd.api.types.is_categorical_dtype(series)
            ):
                return str(column)

        return None

    def _load_specialist(self, name: str) -> object | None:
        """
        Load a specialist instance dynamically from the `specialists` package.

        Args:
            name: Specialist short name.

        Returns:
            object | None: Instantiated specialist or None if unavailable.
        """
        class_name = SPECIALIST_CLASSES.get(name)
        if class_name is None:
            logger.warning("Specialiste inconnu: %s", name)
            return None

        try:
            module = importlib.import_module(f"specialists.{name}")
            specialist_cls = getattr(module, class_name)
            return specialist_cls()
        except Exception:
            logger.exception("Chargement du specialiste %s impossible", name)
            return None

    def _run_specialist(
        self,
        name: str,
        df: pd.DataFrame,
        state: dict,
        params: dict,
    ) -> dict:
        """
        Load and execute one specialist safely.

        Args:
            name: Specialist short name.
            df: DataFrame to analyze.
            state: Specialist-local state copy.
            params: Specialist parameter dictionary.

        Returns:
            dict: Specialist standard result payload.
        """
        specialist = self._load_specialist(name)
        if specialist is None:
            return {
                "agent": name,
                "status": "error",
                "result": {},
                "execution_time_ms": 0,
                "error": f"Specialiste introuvable: {name}",
            }

        try:
            params = dict(params or {})
            params["target_column"] = state.get("target_column", "")
            return specialist.run(df, state, params)
        except Exception as exc:
            logger.exception("Execution du specialiste %s echouee", name)
            return {
                "agent": name,
                "status": "error",
                "result": {},
                "execution_time_ms": 0,
                "error": str(exc),
            }

    def _build_params(
        self,
        name: str,
        intention: dict,
        state: dict,
        df: pd.DataFrame,
    ) -> dict:
        """
        Build specialist-specific parameters from the current intention and state.

        Args:
            name: Specialist short name.
            intention: Intention payload from agent 4a.
            state: Shared pipeline state.
            df: DataFrame used for specialist execution.

        Returns:
            dict: Specialist parameters.
        """
        params: dict[str, Any] = {}

        if name == "anova_kruskal":
            group_column = intention.get("group_col")
            if not isinstance(group_column, str) or group_column not in df.columns:
                group_column = self._pick_categorical_column(df)
            params["group_column"] = group_column

        if name == "pivot":
            params["group_col"] = intention.get("group_col")

        if name == "cp_cpk":
            params["LSL"] = state.get("LSL")
            params["USL"] = state.get("USL")
            if params["LSL"] is None or params["USL"] is None:
                logger.warning("LSL/USL manquants")

        return params

    def _build_specialist_state(
        self,
        state: dict,
        intention: dict,
    ) -> dict:
        """
        Build a per-specialist state copy while preserving the shared parent state.

        Args:
            state: Shared dispatcher state.
            intention: Intention payload from agent 4a.

        Returns:
            dict: Specialist-local state copy.
        """
        specialist_state = dict(state)
        specialist_state.setdefault("errors", [])
        specialist_state.setdefault("warnings", [])
        specialist_state.setdefault("agents_called", [])

        group_col = intention.get("group_col")
        if isinstance(group_col, str) and group_col:
            specialist_state["group_column"] = group_col

        return specialist_state

    def _run_specialists_parallel(
        self,
        task_specs: list[dict],
    ) -> list[dict]:
        """
        Execute specialist calls in parallel with `asyncio.gather()`.

        Args:
            task_specs: Task specifications containing specialist name, state, df, and params.

        Returns:
            list[dict]: Specialist result payloads.
        """
        async def _runner() -> list:
            tasks = [
                asyncio.to_thread(
                    self._run_specialist,
                    spec["name"],
                    spec["df"],
                    spec["state"],
                    spec["params"],
                )
                for spec in task_specs
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        def _execute_in_thread() -> list:
            container: dict[str, Any] = {}

            def _worker() -> None:
                try:
                    container["results"] = asyncio.run(_runner())
                except Exception as exc:
                    container["error"] = exc

            thread = threading.Thread(target=_worker, daemon=True)
            thread.start()
            thread.join()
            if "error" in container:
                raise container["error"]
            return container.get("results", [])

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            raw_results = asyncio.run(_runner())
        else:
            raw_results = _execute_in_thread()

        results: list[dict] = []
        for spec, item in zip(task_specs, raw_results):
            if isinstance(item, Exception):
                logger.error(
                    "Execution parallele du specialiste %s a leve une exception: %s",
                    spec["name"],
                    item,
                )
                results.append({
                    "agent": spec["name"],
                    "status": "error",
                    "result": {},
                    "execution_time_ms": 0,
                    "error": str(item),
                })
            else:
                results.append(item)
        return results

    def run(
        self,
        df: pd.DataFrame,
        state: AgentState | dict,
    ) -> dict:
        """
        Select, pre-filter, execute, and collect specialists from the current intention.

        Args:
            df: Cleaned DataFrame ready for specialist execution.
            state: Shared pipeline state.

        Returns:
            dict: Structured dispatcher result payload.
        """
        start_time = time.time()

        if isinstance(state, dict):
            state.setdefault("errors", [])
            state.setdefault("warnings", [])
            state.setdefault("agents_called", [])
            state["agents_called"].append("agent_4b_dispatcher")

        try:
            intention = state.get("intention", {}) if isinstance(state, dict) else {}
            # Ne jamais écraser target_column
            # avec l'intention du LLM
            # state["target_column"] est posé par agent_1
            # et ne doit jamais être modifié après
            goal = intention.get("goal", "resume")
            if goal not in GOAL_TO_SPECIALISTS:
                goal = "resume"

            specialists = list(GOAL_TO_SPECIALISTS.get(goal, GOAL_TO_SPECIALISTS["resume"]))
            if goal == "correlation" and bool(intention.get("time_aware")):
                if "fourier" not in specialists:
                    specialists.append("fourier")

            pre_gate = self._pre_gate(df, goal, specialists, intention)
            specialists_valides = pre_gate["specialists_valides"]
            specialists_bloques = [
                specialist for specialist in specialists
                if specialist not in specialists_valides
            ]

            if isinstance(state, dict):
                state["judge_warnings"] = pre_gate["warnings"]

            if pre_gate["blocked"]:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_message = "Aucun specialiste executable apres pre-gate"
                if isinstance(state, dict):
                    state["specialist_results"] = []
                return {
                    "agent": "agent_4b_dispatcher",
                    "status": "error",
                    "goal": goal,
                    "specialists_appelés": [],
                    "specialists_bloqués": specialists_bloques or specialists,
                    "results": [],
                    "pre_gate_warnings": pre_gate["warnings"],
                    "execution_time_ms": execution_time_ms,
                    "error": error_message,
                }

            task_specs = []
            for name in specialists_valides:
                params = self._build_params(
                    name,
                    intention,
                    state if isinstance(state, dict) else {},
                    df,
                )
                specialist_state = self._build_specialist_state(
                    state if isinstance(state, dict) else {},
                    intention,
                )
                task_specs.append({
                    "name": name,
                    "df": df,
                    "state": specialist_state,
                    "params": params,
                })

            if isinstance(state, dict):
                state["specialist_tasks"] = [
                    {
                        "agent": spec["name"],
                        "params": spec["params"],
                    }
                    for spec in task_specs
                ]

            results = self._run_specialists_parallel(task_specs)

            if isinstance(state, dict):
                state["specialist_results"] = results

            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_4b_dispatcher",
                "status": "success",
                "goal": goal,
                "specialists_appelés": specialists_valides,
                "specialists_bloqués": specialists_bloques,
                "results": results,
                "pre_gate_warnings": pre_gate["warnings"],
                "execution_time_ms": execution_time_ms,
                "error": None,
            }
        except Exception as exc:
            logger.exception("agent_4b_dispatcher failed")
            if isinstance(state, dict):
                state.setdefault("errors", [])
                state["errors"].append(str(exc))
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_4b_dispatcher",
                "status": "error",
                "goal": state.get("intention", {}).get("goal", "resume") if isinstance(state, dict) else "resume",
                "specialists_appelés": [],
                "specialists_bloqués": [],
                "results": [],
                "pre_gate_warnings": [],
                "execution_time_ms": execution_time_ms,
                "error": str(exc),
            }


if __name__ == "__main__":
    import numpy as np
    import pandas as pd

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    np.random.seed(42)
    n = 100

    base = np.random.normal(100, 10, n)
    df_base = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "capteur_a": base,
        "capteur_b": base * 0.8 + np.random.normal(0, 5, n),
        "categorie": ["A"] * 50 + ["B"] * 50,
    })

    dispatcher = DispatcherAgent()

    cas_tests = [
        {
            "nom": "CAS 1 — Anomalie/Dérive ambiguë",
            "state": {
                "intention": {
                    "goal": "detection_anomalies",
                    "target_col": "capteur_a",
                    "group_col": None,
                    "time_aware": True,
                },
                "target_column": "capteur_a",
            },
        },
        {
            "nom": "CAS 2 — Comparaison groupes",
            "state": {
                "intention": {
                    "goal": "comparaison_groupes",
                    "target_col": "capteur_a",
                    "group_col": "categorie",
                    "time_aware": False,
                },
                "target_column": "capteur_a",
            },
        },
        {
            "nom": "CAS 3 — Capabilité sans LSL/USL",
            "state": {
                "intention": {
                    "goal": "capabilite",
                    "target_col": "capteur_a",
                    "group_col": None,
                    "time_aware": False,
                },
                "target_column": "capteur_a",
            },
        },
        {
            "nom": "CAS 4 — Données insuffisantes",
            "df_override": pd.DataFrame({
                "capteur_a": [1.0, 2.0, 3.0],
            }),
            "state": {
                "intention": {
                    "goal": "detection_anomalies",
                    "target_col": "capteur_a",
                    "group_col": None,
                    "time_aware": False,
                },
                "target_column": "capteur_a",
            },
        },
        {
            "nom": "CAS 5 — Résumé général",
            "state": {
                "intention": {
                    "goal": "resume",
                    "target_col": "capteur_a",
                    "group_col": None,
                    "time_aware": False,
                },
                "target_column": "capteur_a",
            },
        },
        {
            "nom": "CAS 6 — Tendance progressive",
            "state": {
                "intention": {
                    "goal": "tendance",
                    "target_col": "capteur_a",
                    "group_col": None,
                    "time_aware": True,
                },
                "target_column": "capteur_a",
            },
        },
    ]

    for cas in cas_tests:
        df_test = cas.get("df_override", df_base)
        state = cas["state"]

        print(f"\n{'=' * 50}")
        print(f"{cas['nom']}")

        result = dispatcher.run(df_test, state)

        print(f"Status       : {result['status']}")
        print(f"Goal         : {result['goal']}")
        print(f"Spécialistes : {result['specialists_appelés']}")
        print(f"Warnings     : {result['pre_gate_warnings']}")
        print(f"Temps        : {result['execution_time_ms']}ms")

        for specialist_result in result.get("results", []):
            status = specialist_result.get("status", "?")
            agent = specialist_result.get("agent", "?")
            print(f"  -> {agent}: {status}")
