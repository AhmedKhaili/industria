import copy
import logging
import sys
import time
from pathlib import Path
from typing import Literal

import numpy as np

from tenacity import retry, stop_after_attempt, wait_exponential

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from langgraph.graph import END, StateGraph
from state.schema import AgentState, create_initial_state
from enterprise.agents.agent_1_analyst import AnalystAgent
from enterprise.agents.agent_2_sql import SQLAgent
from enterprise.agents.agent_3_cleaner import DataCleaner
from enterprise.agents.agent_4a_methodologist import MethodologistAgent
from enterprise.agents.agent_4b_dispatcher import DispatcherAgent
from enterprise.agents.statistician_judge import StatisticianJudge
from enterprise.agents.agent_5_interpreter import InterpreterAgent

logger = logging.getLogger(__name__)

analyst = AnalystAgent()
sql_agent = SQLAgent()
cleaner = DataCleaner()
methodologist = MethodologistAgent()
dispatcher = DispatcherAgent()
judge = StatisticianJudge()
interpreter = InterpreterAgent()


def _append_agent_called(state: AgentState | dict, agent_name: str) -> None:
    """
    Register one agent call without duplicating entries.

    Args:
        state: Shared pipeline state.
        agent_name: Agent identifier to append.
    """
    if not isinstance(state, dict):
        return

    state.setdefault("agents_called", [])
    if agent_name not in state["agents_called"]:
        state["agents_called"].append(agent_name)


def _append_error(state: AgentState | dict, error_message: str | None) -> None:
    """
    Append an error message to the shared state when present.

    Args:
        state: Shared pipeline state.
        error_message: Optional human-readable error.
    """
    if not isinstance(state, dict) or not error_message:
        return

    state.setdefault("errors", [])
    state["errors"].append(str(error_message))


_MIN_DISPATCHER_ROWS = 5


def _pick_analysis_df(state: AgentState | dict):
    """
    Pick the best available DataFrame for downstream analytics.

    Prefers `df_propre` when it has enough rows for specialists; otherwise falls
    back to `df_raw` so aggressive cleaning does not block the dispatcher.

    Args:
        state: Shared pipeline state.

    Returns:
        Any: `df_propre` when available, otherwise `df_raw`, otherwise None.
    """
    if not isinstance(state, dict):
        return None

    df_propre = state.get("df_propre")
    df_raw = state.get("df_raw")

    propre_ok = (
        df_propre is not None
        and not getattr(df_propre, "empty", True)
        and len(df_propre.index) >= _MIN_DISPATCHER_ROWS
    )
    if propre_ok:
        return df_propre

    if df_propre is not None and not getattr(df_propre, "empty", True):
        raw_len = len(df_raw.index) if df_raw is not None else 0
        if raw_len >= _MIN_DISPATCHER_ROWS:
            logger.warning(
                "df_propre trop petit (%s lignes), "
                "dispatcher utilise df_raw (%s lignes)",
                len(df_propre.index),
                raw_len,
            )
            return df_raw

    if df_propre is not None and not getattr(df_propre, "empty", False):
        return df_propre

    if df_raw is not None and not getattr(df_raw, "empty", False):
        return df_raw

    return None


def node_analyst(state: AgentState) -> AgentState:
    """
    Run the semantic analyst and update the shared state.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Node analyst started")
    result = analyst.run(state["question"], state)
    _append_agent_called(state, "agent_1_analyst")
    _append_error(state, result.get("error"))
    return state


def node_sql(state: AgentState) -> AgentState:
    """
    Run the SQL agent and update the shared state.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Node sql started")
    result = sql_agent.run(state["question"], state)
    state["df_raw"] = state.get("df_raw")

    target_col = state.get("target_column", "")
    df_raw = state.get("df_raw")
    if (
        df_raw is not None
        and not getattr(df_raw, "empty", True)
        and isinstance(target_col, str)
        and target_col
        and target_col not in df_raw.columns
    ):
        logger.warning(
            "target_column %s absente du df_raw, "
            "recalage sur premiere colonne numerique",
            target_col,
        )
        id_cols = {"piece_id", "id", "row_id"}
        numeric_cols = [
            col
            for col in df_raw.select_dtypes(include=[np.number]).columns
            if col not in id_cols
        ]
        avg_cols = [col for col in numeric_cols if str(col).startswith("avg_")]
        pick = (avg_cols or numeric_cols)
        if pick:
            state["target_column"] = pick[0]

    _append_agent_called(state, "agent_2_sql")
    _append_error(state, result.get("error"))
    return state


def node_cleaner(state: AgentState) -> AgentState:
    """
    Run the cleaner when raw data is available.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Node cleaner started")
    df = state.get("df_raw")
    if df is None or getattr(df, "empty", False):
        _append_error(state, "Pas de donnees a nettoyer")
        return state

    result = cleaner.run(df, state)
    _append_agent_called(state, "agent_3_cleaner")
    _append_error(state, result.get("error"))
    return state


def node_methodologist(state: AgentState) -> AgentState:
    """
    Run the intent classifier for specialist dispatch.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Node methodologist started")

    if not state.get("columns"):
        df = _pick_analysis_df(state)
        if df is not None:
            state["columns"] = list(df.columns)

    result = methodologist.run(state["question"], state)
    _append_agent_called(state, "agent_4a_methodologist")
    _append_error(state, result.get("error"))
    return state


def node_dispatcher(state: AgentState) -> AgentState:
    """
    Dispatch specialists on the cleaned or raw analysis DataFrame.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Node dispatcher started")
    df = _pick_analysis_df(state)
    if df is None:
        _append_error(state, "Pas de donnees pour le dispatcher")
        return state

    result = dispatcher.run(df, state)
    _append_agent_called(state, "agent_4b_dispatcher")
    _append_error(state, result.get("error"))
    return state


def node_judge(state: AgentState) -> AgentState:
    """
    Validate specialist outputs with the statistician judge.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Node judge started")
    result = judge.run(state)
    _append_agent_called(state, "statistician_judge")
    _append_error(state, result.get("error"))
    return state


def node_interpreter(state: AgentState) -> AgentState:
    """
    Run Agent 5 to produce OBSERVER/ANALYSER and update state fields.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Node interpreter started")
    result = interpreter.run(state)
    _append_error(state, result.get("error"))
    return state


def node_report(state: AgentState) -> AgentState:
    """
    Placeholder for the report agent until Sprint 5 implementation.

    Args:
        state: Shared pipeline state.

    Returns:
        AgentState: Updated state.
    """
    logger.info("Report agent placeholder - Sprint 5")
    state["pdf_path"] = ""
    _append_agent_called(state, "report_agent")
    return state


def should_continue(state: AgentState) -> Literal["continue", "stop"]:
    """
    Stop the pipeline early when SQL did not produce usable data.

    Args:
        state: Shared pipeline state.

    Returns:
        Literal["continue", "stop"]: Routing decision after SQL.
    """
    if len(state.get("errors", [])) > 2:
        logger.error("Trop d'erreurs - arret")
        return "stop"

    df_raw = state.get("df_raw")
    if df_raw is None or getattr(df_raw, "empty", False):
        logger.warning("Pas de donnees - arret")
        return "stop"

    return "continue"


workflow = StateGraph(AgentState)

workflow.add_node("analyst", node_analyst)
workflow.add_node("sql", node_sql)
workflow.add_node("cleaner", node_cleaner)
workflow.add_node("methodologist", node_methodologist)
workflow.add_node("dispatcher", node_dispatcher)
workflow.add_node("judge", node_judge)
workflow.add_node("interpreter", node_interpreter)
workflow.add_node("report", node_report)

workflow.set_entry_point("analyst")

workflow.add_edge("analyst", "sql")
workflow.add_conditional_edges(
    "sql",
    should_continue,
    {
        "continue": "cleaner",
        "stop": END,
    },
)
workflow.add_edge("cleaner", "methodologist")
workflow.add_edge("methodologist", "dispatcher")
workflow.add_edge("dispatcher", "judge")
workflow.add_edge("judge", "interpreter")
workflow.add_edge("interpreter", "report")
workflow.add_edge("report", END)

app = workflow.compile()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5), reraise=True)
def _invoke_app(state: AgentState) -> AgentState:
    """
    Invoke the compiled LangGraph application with retry protection.

    Args:
        state: Initial pipeline state.

    Returns:
        AgentState: Final pipeline state.
    """
    logger.info("Invoking LangGraph application")
    return app.invoke(copy.deepcopy(state))


def run_pipeline(question: str) -> dict:
    """
    Run the full IndustrIA LangGraph pipeline for one user question.

    Args:
        question: User question in natural language.

    Returns:
        dict: Pipeline summary ready for API/UI consumption.
    """
    logger.info("Pipeline demarre: %s", question)
    start_time = time.time()

    state = create_initial_state(question)
    state["pipeline_start_time"] = start_time

    try:
        final_state = _invoke_app(state)
    except Exception as exc:
        logger.error("Pipeline error: %s", exc)
        return {
            "error": str(exc),
            "question": question,
            "agents_called": [],
            "tables": [],
            "target_column": "",
            "intention": {},
            "specialist_results": [],
            "judge_warnings": [],
            "errors": [str(exc)],
            "explanation": "",
            "recommendation": "",
            "pdf_path": "",
            "execution_time_ms": int((time.time() - start_time) * 1000),
        }

    execution_time = int((time.time() - start_time) * 1000)

    return {
        "question": question,
        "agents_called": final_state.get("agents_called", []),
        "tables": final_state.get("tables", []),
        "target_column": final_state.get("target_column", ""),
        "intention": final_state.get("intention", {}),
        "specialist_results": final_state.get("validated_results", []),
        "judge_warnings": final_state.get("judge_warnings", []),
        "errors": final_state.get("errors", []),
        "explanation": final_state.get("explanation", ""),
        "recommendation": final_state.get("recommendation", ""),
        "pdf_path": final_state.get("pdf_path", ""),
        "execution_time_ms": execution_time,
    }


if __name__ == "__main__":
    # Install if needed: pip install langgraph
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    questions = [
        "Y a-t-il des anomalies sur les capteurs ?",
        "Quelle est la tendance de la production ?",
        "Compare les differents groupes de donnees",
    ]

    for question in questions:
        logger.info("%s", "=" * 60)
        logger.info("QUESTION : %s", question)

        result = run_pipeline(question)

        logger.info("Agents appeles : %s", result["agents_called"])
        logger.info("Tables         : %s", result["tables"])
        logger.info("Target         : %s", result["target_column"])
        logger.info(
            "Intention      : %s",
            result.get("intention", {}).get("goal", "N/A"),
        )
        logger.info("Specialistes   : %s", len(result["specialist_results"]))
        logger.info("Warnings       : %s", len(result["judge_warnings"]))
        logger.info("Erreurs        : %s", result["errors"])
        logger.info("Temps total    : %sms", result["execution_time_ms"])
