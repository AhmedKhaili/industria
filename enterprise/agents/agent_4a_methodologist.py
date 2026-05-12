import json
import logging
import re
import sys
import time
from pathlib import Path

import ollama
from tenacity import retry, stop_after_attempt, wait_exponential

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from state.schema import AgentState

logger = logging.getLogger(__name__)


class MethodologistAgent:
    """Classify analytical intent from a user question and available columns."""

    def __init__(self) -> None:
        """Initialize valid goal values and fallback column heuristics."""
        self._valid_goals = {
            "detection_anomalies",
            "comparaison_groupes",
            "correlation",
            "capabilite",
            "tendance",
            "cross_process",
            "simulation",
            "resume",
        }
        self._non_metric_hints = {
            "timestamp",
            "time",
            "date",
            "datetime",
            "modele",
            "model",
            "equipe",
            "team",
            "groupe",
            "group",
            "matrice",
            "status",
            "etat",
            "type",
            "lot",
            "batch",
            "id",
        }

    def _build_prompt(self, question: str, columns: list[str]) -> dict:
        """
        Build the system and user prompts for intent classification.

        Args:
            question: User question in French.
            columns: Available column names.

        Returns:
            dict: Prompt payload with `system` and `user`.
        """
        system_prompt = (
            "Tu es un classificateur d'intention.\n"
            "Tu analyses une question industrielle\n"
            "et tu retournes UNIQUEMENT ce JSON :\n"
            "{\n"
            "  'goal': 'detection_anomalies' ou\n"
            "          'comparaison_groupes' ou\n"
            "          'correlation' ou\n"
            "          'capabilite' ou\n"
            "          'tendance' ou\n"
            "          'cross_process' ou\n"
            "          'simulation' ou\n"
            "          'resume',\n"
            "  'target_col': 'nom_colonne_principale',\n"
            "  'group_col': 'nom_colonne_groupe' ou null,\n"
            "  'time_aware': true ou false\n"
            "}\n\n"
            f"Colonnes disponibles : {columns}\n\n"
            "Exemples :\n"
            "'anomalies sur le four 3' ->\n"
            "{'goal':'detection_anomalies',\n"
            " 'target_col':'four_3',\n"
            " 'group_col':null,'time_aware':false}\n\n"
            "'compare modèles M2224 et M2225' ->\n"
            "{'goal':'comparaison_groupes',\n"
            " 'target_col':'lvdt_moyenne',\n"
            " 'group_col':'modele','time_aware':false}\n\n"
            "Réponds UNIQUEMENT avec le JSON.\n"
            "Pas de markdown. Pas d'explication."
        )

        user_prompt = (
            f"Question : {question}\n\n"
            "Réponds UNIQUEMENT avec le JSON.\n"
            "Pas de markdown. Pas d'explication.\n"
            "Pas de texte avant ou après le JSON."
        )
        return {"system": system_prompt, "user": user_prompt}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _call_ollama(self, prompt: dict) -> dict | None:
        """
        Call Ollama and parse the cleaned JSON payload.

        Args:
            prompt: Prompt dictionary containing `system` and `user`.

        Returns:
            dict | None: Parsed JSON payload or None on parse failure.
        """
        response = ollama.chat(
            model="qwen2.5-coder:7b",
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
            ],
            format="json",
            options={
                "num_ctx": 2000,
                "num_predict": 150,
                "temperature": 0.1,
            },
        )

        raw = ""
        if isinstance(response, dict):
            raw = str(response.get("message", {}).get("content", "") or "")
        else:
            message = getattr(response, "message", None)
            if message is not None:
                raw = str(getattr(message, "content", "") or "")

        logger.debug("Intention brute : %s", raw)

        cleaned = raw.replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        cleaned = cleaned[start:end + 1]
        try:
            return json.loads(cleaned)
        except Exception:
            return None

    def _pick_default_target_column(self, columns: list[str]) -> str:
        """
        Pick a plausible fallback target column when only column names are available.

        Args:
            columns: Available column names.

        Returns:
            str: Best-effort fallback target column.
        """
        for column in columns:
            lowered = str(column).strip().lower()
            if lowered and lowered not in self._non_metric_hints:
                if not any(hint in lowered for hint in self._non_metric_hints):
                    return column

        for column in columns:
            if str(column).strip():
                return column
        return ""

    def _validate_output(self, output: dict, columns: list[str]) -> dict:
        """
        Validate and normalize the LLM output with Python-only rules.

        Args:
            output: Raw LLM dictionary.
            columns: Available column names.

        Returns:
            dict: Normalized intention payload.
        """
        goal = output.get("goal", "resume")
        if not isinstance(goal, str) or goal not in self._valid_goals:
            goal = "resume"

        target_col = output.get("target_col", "")
        if not isinstance(target_col, str) or target_col not in columns:
            target_col = self._pick_default_target_column(columns)

        group_col = output.get("group_col")
        if not isinstance(group_col, str) or group_col not in columns:
            group_col = None

        time_aware = output.get("time_aware")
        if not isinstance(time_aware, bool):
            time_aware = False

        return {
            "goal": goal,
            "target_col": target_col,
            "group_col": group_col,
            "time_aware": time_aware,
        }

    def run(self, question: str, state: AgentState | dict) -> dict:
        """
        Classify the question intent, validate the JSON output, and update state.

        Args:
            question: User question in French.
            state: Shared agent state.

        Returns:
            dict: Structured methodologist result payload.
        """
        start_time = time.time()
        attempts = 0

        if isinstance(state, dict):
            state.setdefault("errors", [])
            state.setdefault("agents_called", [])
            state["agents_called"].append("agent_4a_methodologist")

        try:
            columns = state.get("columns", []) if isinstance(state, dict) else []
            columns = columns if isinstance(columns, list) else []

            validated: dict | None = None
            attempt_errors: list[str] = []
            for attempt in range(3):
                attempts = attempt + 1
                prompt = self._build_prompt(question, columns)
                try:
                    output = self._call_ollama(prompt)
                except Exception as exc:
                    logger.warning(
                        "Methodologist attempt %s failed: %s",
                        attempts,
                        exc,
                    )
                    attempt_errors.append(str(exc))
                    continue
                if output:
                    validated = self._validate_output(output, columns)
                    break

            if validated is None:
                validated = {
                    "goal": "resume",
                    "target_col": columns[0] if columns else "",
                    "group_col": None,
                    "time_aware": False,
                }
                if isinstance(state, dict) and attempt_errors:
                    state["errors"].append("; ".join(attempt_errors))

            if isinstance(state, dict):
                state["intention"] = validated

            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_4a_methodologist",
                "status": "success",
                "intention": validated,
                "attempts": attempts,
                "execution_time_ms": execution_time_ms,
                "error": None,
            }
        except Exception as exc:
            logger.exception("agent_4a_methodologist failed")
            if isinstance(state, dict):
                state.setdefault("errors", [])
                state["errors"].append(str(exc))
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_4a_methodologist",
                "status": "error",
                "intention": {
                    "goal": "resume",
                    "target_col": "",
                    "group_col": None,
                    "time_aware": False,
                },
                "attempts": attempts,
                "execution_time_ms": execution_time_ms,
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    agent = MethodologistAgent()

    tests = [
        {
            "question": "Y a-t-il des anomalies sur le four 3 ?",
            "state": {
                "columns": [
                    "timestamp",
                    "four_1",
                    "four_2",
                    "four_3",
                    "verin_1",
                    "modele",
                ]
            },
        },
        {
            "question": "Compare les modèles M1565 et M1566",
            "state": {
                "columns": [
                    "timestamp",
                    "modele",
                    "matrice",
                    "lvdt_formage",
                    "verin_1",
                ]
            },
        },
        {
            "question": "Y a-t-il une corrélation entre le four et la pression ?",
            "state": {
                "columns": [
                    "timestamp",
                    "four_1",
                    "verin_1",
                    "verin_2",
                ]
            },
        },
    ]

    for test in tests:
        state = test["state"]
        result = agent.run(test["question"], state)
        print(f"\n{'=' * 50}")
        print(f"Q         : {test['question']}")
        print(f"Goal      : {result['intention']['goal']}")
        print(f"Target    : {result['intention']['target_col']}")
        print(f"Group     : {result['intention']['group_col']}")
        print(f"Tentatives: {result['attempts']}")
        print(f"Temps     : {result['execution_time_ms']}ms")
