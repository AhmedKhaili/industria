"""
Orchestrateur IndustrIA : enchaîne router → SQL → agents analytiques (placeholders) → LLM.
Ne doit pas planter : chaque étape est isolée et journalisée.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any

# Permet `python enterprise/agents/orchestrator_agent.py` depuis la racine du dépôt
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from enterprise.agents.llm_agent import LLMAgent
from enterprise.agents.router_agent import RouterAgent
from enterprise.agents.sql_agent import SQLAgent

from core.data.config import CONFIG

logger = logging.getLogger(__name__)

PIECE_KEYS = ("PIECE_A", "PIECE_B", "PIECE_C")

# Agents gérés ailleurs dans le pipeline (pas d'import dynamique ici)
_ORCHESTRATION_AGENTS = frozenset(
    {"sql_agent", "llm_agent", "router_agent", "orchestrator_agent"}
)


def _load_nominaux_pieces() -> dict[str, Any]:
    """Extrait nominaux / LTI / LST pour les 3 modèles de pièces."""
    pieces = CONFIG.get("pieces") or {}
    out: dict[str, Any] = {}
    for key in PIECE_KEYS:
        if key in pieces:
            out[key] = pieces[key]
    return out


def _build_sql_question(user_question: str, route: dict[str, Any]) -> str:
    """Construit la consigne naturelle pour SQLAgent à partir du routage."""
    tables = route.get("tables") or []
    tf = route.get("time_filter")
    parts = [user_question.strip()]
    if tables:
        parts.append(f"Interroger principalement les tables : {', '.join(tables)}.")
    else:
        parts.append(
            "Interroger les tables ebauche_data, filage_data et formage_data "
            "(requête pertinente couvrant les besoins, éventuellement plusieurs tables)."
        )
    if tf:
        parts.append(f"Filtre temporel exprimé par l'utilisateur : {tf}.")
    parts.append("Limiter à 100 lignes pour l'extraction.")
    return " ".join(parts)


def _try_import_and_run_agent(agent_name: str, context: dict[str, Any]) -> dict[str, Any]:
    """
    Tente d'exécuter enterprise.agents.<agent_name>.run(context).
    Sinon retourne le placeholder Sprint 1.
    """
    if agent_name in _ORCHESTRATION_AGENTS:
        return {
            "status": "skipped",
            "agent": agent_name,
            "reason": "Agent pris en charge par l'orchestrateur",
        }

    mod_path = Path(__file__).resolve().parent / f"{agent_name}.py"
    if not mod_path.is_file():
        logger.warning("Agent %s non encore implémenté — skipped", agent_name)
        return {"status": "not_implemented", "agent": agent_name}

    try:
        mod = importlib.import_module(f"enterprise.agents.{agent_name}")
    except Exception as e:
        logger.exception("Import échoué pour %s : %s", agent_name, e)
        return {"status": "not_implemented", "agent": agent_name, "import_error": str(e)}

    run_fn = getattr(mod, "run", None)
    if run_fn is None or not callable(run_fn):
        logger.warning(
            "Agent %s : pas de fonction run() callable — placeholder",
            agent_name,
        )
        return {"status": "not_implemented", "agent": agent_name}

    try:
        return run_fn(context)
    except Exception as e:
        logger.exception("Exécution échouée pour %s : %s", agent_name, e)
        return {"status": "error", "agent": agent_name, "error": str(e)}


class OrchestratorAgent:
    """Chef d'orchestre : contexte → router → SQL → analyse (placeholders) → LLM."""

    def __init__(self) -> None:
        self._router = RouterAgent()
        self._sql = SQLAgent()
        self._llm = LLMAgent()

    def ask(self, question: str) -> dict[str, Any]:
        errors: list[str] = []
        nominaux: dict[str, Any] = {}
        route: dict[str, Any] = {
            "agents": [],
            "mode": "sequential",
            "tables": [],
            "time_filter": None,
            "target_columns": [],
            "error": None,
        }
        sql_out: dict[str, Any] = {
            "sql": None,
            "data": [],
            "row_count": 0,
            "error": None,
        }
        analytic_results: dict[str, Any] = {}
        not_implemented: list[str] = []

        # ÉTAPE 1 — contexte métier
        try:
            nominaux = _load_nominaux_pieces()
        except Exception as e:
            logger.exception("context_enrichment : %s", e)
            errors.append(f"context_enrichment: {e}")

        # ÉTAPE 2 — routing (question brute ; nominaux passés en contexte structuré)
        try:
            route = self._router.route(question)
            if route.get("error"):
                errors.append(f"router: {route['error']}")
        except Exception as e:
            logger.exception("routing : %s", e)
            errors.append(f"routing: {e}")
            route = {
                "agents": ["descriptive_agent"],
                "mode": "sequential",
                "tables": [],
                "time_filter": None,
                "target_columns": [],
                "error": str(e),
                "intent": ["summary"],
            }

        agents_list = list(route.get("agents") or [])

        # ÉTAPE 3 — données
        try:
            sql_question = _build_sql_question(question, route)
            sql_out = self._sql.ask(sql_question)
            if sql_out.get("error"):
                errors.append(f"sql: {sql_out['error']}")
        except Exception as e:
            logger.exception("data_fetching : %s", e)
            errors.append(f"data_fetching: {e}")

        # ÉTAPE 4 — analyse (import dynamique ou placeholder)
        ctx_for_agents: dict[str, Any] = {
            "question": question,
            "route": route,
            "sql_data": sql_out,
            "nominaux": nominaux,
        }
        for agent_name in agents_list:
            try:
                res = _try_import_and_run_agent(agent_name, ctx_for_agents)
                analytic_results[agent_name] = res
                if res.get("status") == "not_implemented":
                    not_implemented.append(agent_name)
            except Exception as e:
                logger.exception("analysis agent %s : %s", agent_name, e)
                errors.append(f"analysis:{agent_name}:{e}")
                analytic_results[agent_name] = {
                    "status": "error",
                    "agent": agent_name,
                    "error": str(e),
                }

        # ÉTAPE 5 — juge statisticien (placeholder)
        logger.info("Judge non implémenté — skipped")

        # ÉTAPE 6 — explication LLM
        sample = (sql_out.get("data") or [])[:5]
        analysis_results: dict[str, Any] = {
            "question": question,
            "agents_used": agents_list,
            "sql_data": {
                "row_count": sql_out.get("row_count", 0),
                "sample": sample,
            },
            "results": analytic_results,
            "context": {
                "tables": route.get("tables") or [],
                "time_filter": route.get("time_filter"),
                "target_columns": route.get("target_columns") or [],
                "nominaux": nominaux,
            },
        }

        explain_out: dict[str, Any] = {
            "explanation": "",
            "recommendation": "",
            "anomaly_detected": False,
            "agents_used": agents_list,
            "error": None,
        }
        try:
            explain_out = self._llm.explain(analysis_results)
            if explain_out.get("error"):
                errors.append(f"llm: {explain_out['error']}")
        except Exception as e:
            logger.exception("explanation : %s", e)
            errors.append(f"explanation: {e}")
            explain_out = {
                "explanation": "Synthèse indisponible (erreur LLM).",
                "recommendation": "Consulter les données brutes et le SQL exécuté.",
                "anomaly_detected": False,
                "agents_used": agents_list,
                "error": str(e),
            }

        # ÉTAPE 7 — sortie
        agg_error = "; ".join(errors) if errors else None

        return {
            "question": question,
            "explanation": explain_out.get("explanation") or "",
            "recommendation": explain_out.get("recommendation") or "",
            "anomaly_detected": bool(explain_out.get("anomaly_detected")),
            "agents_used": agents_list,
            "sql_row_count": int(sql_out.get("row_count") or 0),
            "analysis_details": {
                "routing": route,
                "sql": {
                    "sql": sql_out.get("sql"),
                    "error": sql_out.get("error"),
                },
                "analytic_results": analytic_results,
                "not_implemented_agents": not_implemented,
                "nominaux_keys": list(nominaux.keys()),
            },
            "error": agg_error,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    tests = [
        "Y a-t-il des anomalies dans le formage depuis lundi ?",
        "Donne-moi un résumé de la production",
        "Compare les pièces M2224 et M2225 au filage",
    ]
    orch = OrchestratorAgent()
    for q in tests:
        print("\n" + "=" * 72)
        out = orch.ask(q)
        print("-> QUESTION :", out["question"])
        print("-> AGENTS APPELÉS :", ", ".join(out["agents_used"]) or "(aucun)")
        print("-> EXPLICATION :", out["explanation"])
        print("-> RECOMMANDATION :", out["recommendation"])
        print("-> ANOMALIE DÉTECTÉE :", out["anomaly_detected"])
        print("-> LIGNES ANALYSÉES :", out["sql_row_count"])
        ni = out["analysis_details"].get("not_implemented_agents") or []
        print("-> AGENTS NON IMPLÉMENTÉS :", ", ".join(ni) if ni else "(aucun)")
        if out.get("error"):
            print("-> ERREURS PARTIELLES :", out["error"])
