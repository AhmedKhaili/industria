"""
Router analytique IndustrIA : classification NL → intents → liste d'agents.
Le LLM ne fait que remplir un JSON ; le mapping intent→agents est en Python.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from ollama import Client

OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5-coder:14b"
OLLAMA_TIMEOUT_S = 60.0

VALID_INTENTS = frozenset(
    {
        "anomaly",
        "correlation",
        "drift",
        "comparison",
        "causality",
        "capability",
        "prediction",
        "summary",
        "cross_process",
    }
)

VALID_TABLES = frozenset({"ebauche_data", "filage_data", "formage_data"})

SYSTEM_PROMPT = """Tu es un classificateur. Analyse la question et retourne UNIQUEMENT un JSON valide sans markdown.

Format exact (guillemets doubles obligatoires pour JSON) :
{
  "intent": ["anomaly"|"correlation"|"drift"|"comparison"|"causality"|"capability"|"prediction"|"summary"|"cross_process"],
  "tables": ["ebauche_data"|"filage_data"|"formage_data"],
  "time_filter": "cette semaine"|"depuis lundi"|null,
  "target_columns": ["nom_colonne_1"] ou []
}

Une question peut avoir plusieurs intents dans le tableau "intent".
Réponds UNIQUEMENT avec le JSON, rien d'autre."""

INTENT_TO_AGENTS: dict[str, list[str]] = {
    "anomaly": [
        "zscore_agent",
        "isolation_forest_agent",
        "outlier_agent",
        "changepoint_agent",
        "matrix_profile_agent",
    ],
    "correlation": [
        "correlation_agent",
        "mutual_info_agent",
        "pcmci_agent",
    ],
    "drift": [
        "trend_agent",
        "cusum_agent",
        "ewma_agent",
    ],
    "comparison": [
        "descriptive_agent",
        "distribution_agent",
        "anova_agent",
    ],
    "causality": [
        "pcmci_agent",
        "feature_importance_agent",
        "regression_agent",
    ],
    "capability": [
        "capability_agent",
        "spc_agent",
        "distribution_agent",
    ],
    "prediction": [
        "forecast_agent",
        "trend_agent",
        "rul_agent",
    ],
    "summary": [
        "descriptive_agent",
        "oee_agent",
        "isolation_forest_agent",
    ],
    "cross_process": [
        "cross_process_agent",
        "lag_agent",
        "correlation_agent",
    ],
}

FALLBACK_ERROR = "Classification échouée, analyse descriptive lancée"


def _strip_markdown_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_classification_json(content: str) -> dict[str, Any] | None:
    """Tente d'extraire un objet JSON depuis la réponse modèle."""
    cleaned = _strip_markdown_json(content)
    if not cleaned:
        return None

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    try:
        obj = ast.literal_eval(cleaned)
        if isinstance(obj, dict):
            return obj
    except (SyntaxError, ValueError):
        pass

    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        blob = m.group(0)
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            try:
                obj = ast.literal_eval(blob)
                return obj if isinstance(obj, dict) else None
            except (SyntaxError, ValueError):
                return None
    return None


def _normalize_payload(raw: dict[str, Any]) -> dict[str, Any]:
    intents_in = raw.get("intent", [])
    if isinstance(intents_in, str):
        intents_in = [intents_in]
    intents = [str(i).strip().lower() for i in intents_in if i is not None]
    intents = [i for i in intents if i in VALID_INTENTS]

    tables_in = raw.get("tables", [])
    if isinstance(tables_in, str):
        tables_in = [tables_in]
    tables = [str(t).strip() for t in tables_in if t is not None]
    tables = [t for t in tables if t in VALID_TABLES]

    tf = raw.get("time_filter")
    if tf is not None and tf != "":
        time_filter: str | None = str(tf).strip()
        if time_filter.lower() in ("null", "none", ""):
            time_filter = None
    else:
        time_filter = None

    cols = raw.get("target_columns", [])
    if cols is None:
        cols = []
    if isinstance(cols, str):
        cols = [cols]
    target_columns = [str(c).strip() for c in cols if c is not None and str(c).strip()]

    return {
        "intent": intents,
        "tables": tables,
        "time_filter": time_filter,
        "target_columns": target_columns,
    }


def _agents_for_intents(intents: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for intent in intents:
        for agent in INTENT_TO_AGENTS.get(intent, []):
            if agent not in seen:
                seen.add(agent)
                ordered.append(agent)
    return ordered


def _execution_mode(agents: list[str]) -> str:
    if len(agents) <= 1:
        return "sequential"
    return "parallel"


class RouterAgent:
    """Route une question vers les agents analytiques via classification Ollama + mapping Python."""

    def __init__(
        self,
        *,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: float = OLLAMA_TIMEOUT_S,
    ) -> None:
        self._client = Client(host=host, timeout=timeout)
        self._model = model

    def _call_ollama(self, question: str) -> str:
        resp = self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            options={
                "num_ctx": 4000,
                "temperature": 0.0,
            },
        )
        if resp.message and resp.message.content:
            return resp.message.content.strip()
        return ""

    def route(self, question: str) -> dict[str, Any]:
        """
        Retourne la liste d'agents, le mode d'exécution et les métadonnées de classification.
        """
        base: dict[str, Any] = {
            "agents": [],
            "mode": "sequential",
            "intent": [],
            "tables": [],
            "time_filter": None,
            "target_columns": [],
            "raw_question": question,
            "error": None,
        }

        if not question or not question.strip():
            base["error"] = "Question vide."
            base["intent"] = ["summary"]
            base["agents"] = ["descriptive_agent"]
            base["mode"] = _execution_mode(base["agents"])
            return base

        raw_text = self._call_ollama(question)
        parsed = _parse_classification_json(raw_text)

        if parsed is None:
            base["intent"] = ["summary"]
            base["agents"] = ["descriptive_agent"]
            base["mode"] = "sequential"
            base["error"] = FALLBACK_ERROR
            return base

        norm = _normalize_payload(parsed)
        intents = norm["intent"]

        if not intents:
            base["intent"] = ["summary"]
            base["agents"] = ["descriptive_agent"]
            base["mode"] = "sequential"
            base["tables"] = norm["tables"]
            base["time_filter"] = norm["time_filter"]
            base["target_columns"] = norm["target_columns"]
            base["error"] = FALLBACK_ERROR
            return base

        agents = _agents_for_intents(intents)
        if not agents:
            base["intent"] = ["summary"]
            base["agents"] = ["descriptive_agent"]
            base["mode"] = "sequential"
            base["error"] = FALLBACK_ERROR
            return base

        base["intent"] = intents
        base["agents"] = agents
        base["mode"] = _execution_mode(agents)
        base["tables"] = norm["tables"]
        base["time_filter"] = norm["time_filter"]
        base["target_columns"] = norm["target_columns"]
        return base


if __name__ == "__main__":
    agent = RouterAgent()
    tests = [
        "Y a-t-il des anomalies dans le formage depuis lundi ?",
        "Quelle corrélation entre le four 1 et la qualité ?",
        "Compare les pièces M2224 et M2225 au filage",
        "Donne-moi un résumé complet de la production",
    ]
    for q in tests:
        print("\n" + "=" * 72)
        print(f"Q: {q}")
        out = agent.route(q)
        for k, v in out.items():
            print(f"  {k}: {v}")
