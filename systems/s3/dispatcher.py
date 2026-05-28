"""
Sélection des spécialistes selon l'intention S1.
"""

from __future__ import annotations

_PORTRAIT_SPECIALISTS = ["descriptive", "normality", "distribution_fit"]

INTENTION_SPECIALISTS: dict[str, list[str]] = {
    "conformite": ["cp_cpk", "zscore", "spc"],
    "comparaison_groupes": ["anova_kruskal", "cp_cpk"],
    "diagnostic_causal": ["anova_kruskal"],
    "tendance": ["mann_kendall", "ewma_cusum", "regression"],
    "anomalie": ["zscore", "spc", "ewma_cusum"],
    "portrait_statistique": list(_PORTRAIT_SPECIALISTS),
    "analyse_complete": list(_PORTRAIT_SPECIALISTS) + ["correlation", "cp_cpk"],
}


def _specialists_for_intention(intention: str, intent: dict) -> list[str]:
    specialists = list(INTENTION_SPECIALISTS.get(intention, []))
    if intention == "analyse_complete" and intent.get("group_by"):
        if "anova_kruskal" not in specialists:
            specialists.append("anova_kruskal")
    return specialists


def dispatch(intent: dict) -> dict:
    """Retourne la liste des spécialistes à exécuter pour cet intent."""
    try:
        intention = intent.get("intention")
        if not intention:
            return {
                "error": "Intent sans intention — impossible de dispatcher S3",
                "specialists": [],
            }
        specialists = _specialists_for_intention(intention, intent)
        if not specialists:
            return {
                "error": f"Intention non supportée par S3 : {intention}",
                "specialists": [],
            }
        return {"error": None, "specialists": specialists}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "specialists": []}
