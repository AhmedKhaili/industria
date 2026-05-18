from typing import TypedDict, Any, Optional
import pandas as pd


class AgentState(TypedDict):
    """Typed shared LangGraph state for the IndustrIA pipeline."""

    # Question originale
    question: str
    user_profile: str  # operateur|technicien|ingenieur|directeur

    # Sortie Agent 1
    tables: list[str]
    columns: list[str]
    target_column: str
    filters: dict

    # Sortie Agent 2
    df_raw: Any  # pd.DataFrame

    # Sortie Agent 3
    df_propre: Any  # pd.DataFrame
    df_anomalies: Any  # pd.DataFrame
    cleaning_stats: dict

    # Sortie Agent 4a
    intention: dict
    # Format intention :
    # {
    #   "goal": str,
    #   "target_col": str,
    #   "group_col": str | null,
    #   "time_aware": bool
    # }

    # Sortie Agent 4b
    specialist_tasks: list[dict]
    # Format specialist_tasks :
    # [{"agent": "zscore", "params": {...}}]

    # Sortie agents spécialistes
    specialist_results: list[dict]
    # Format specialist_results :
    # [{
    #   "agent": str,
    #   "status": str,
    #   "result": dict,
    #   "execution_time_ms": int,
    #   "error": str | null
    # }]

    # Sortie Statistician Judge
    validated_results: list[dict]
    judge_warnings: list[str]

    # Sortie Agent 5 (OAPC)
    explanation: str
    recommendation: str
    rapport_oapc: dict
    priority: str  # P1|P2|P3|P4
    anomaly_detected: bool
    confidence: str  # "haute"|"moyenne"|"faible"

    # Sortie Agents 6a / 6b
    interpretations: dict
    # Format interpretations :
    # {"ZScoreSpecialist": "texte...", "SpcSpecialist": "..."}

    resume_executif: str

    # Sortie Agent 6c / historique
    pdf_path: str
    analyses_history: list[dict]

    # Métadonnées pipeline
    errors: list[str]
    warnings: list[str]
    pipeline_start_time: float
    agents_called: list[str]


def create_initial_state(question: str) -> AgentState:
    """
    Create an empty shared state with the question pre-filled.

    Args:
        question: Original user question.

    Returns:
        AgentState: Initialized state with default empty values.
    """
    _unused_pd_reference: Optional[type[pd.DataFrame]] = pd.DataFrame
    _ = _unused_pd_reference

    return {
        "question": question,
        "user_profile": "technicien",
        "tables": [],
        "columns": [],
        "target_column": "",
        "filters": {},
        "df_raw": None,
        "df_propre": None,
        "df_anomalies": None,
        "cleaning_stats": {},
        "intention": {},
        "specialist_tasks": [],
        "specialist_results": [],
        "validated_results": [],
        "judge_warnings": [],
        "explanation": "",
        "recommendation": "",
        "rapport_oapc": {},
        "priority": "P4",
        "anomaly_detected": False,
        "confidence": "",
        "interpretations": {},
        "resume_executif": "",
        "pdf_path": "",
        "analyses_history": [],
        "errors": [],
        "warnings": [],
        "pipeline_start_time": 0.0,
        "agents_called": [],
    }
