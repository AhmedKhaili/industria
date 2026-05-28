"""
Sélection des types de graphiques selon l'intention S1.
"""

from __future__ import annotations

INTENTION_CHARTS: dict[str, list[str]] = {
    "conformite": ["histogram"],
    "comparaison_groupes": ["boxplot"],
    "tendance": ["timeseries"],
    "anomalie": ["timeseries"],
    "portrait_statistique": ["histogram", "boxplot", "qqplot"],
    "diagnostic_causal": ["boxplot"],
    "analyse_complete": ["histogram", "boxplot"],
}


def dispatch(intent: dict) -> dict:
    try:
        intention = intent.get("intention")
        if not intention:
            return {"error": "Intent sans intention — impossible de dispatcher S4", "chart_types": []}
        chart_types = list(INTENTION_CHARTS.get(intention, []))
        if not chart_types:
            return {
                "error": f"Intention non supportée par S4 : {intention}",
                "chart_types": [],
            }
        return {"error": None, "chart_types": chart_types}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "chart_types": []}
