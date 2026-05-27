"""
Sélection des spécialistes selon l'intention S1.
"""

from __future__ import annotations

INTENTION_SPECIALISTS: dict[str, list[str]] = {
    "conformite": ["cp_cpk", "zscore", "spc"],
    "comparaison_groupes": ["anova_kruskal", "cp_cpk"],
    "tendance": ["mann_kendall", "ewma_cusum", "regression"],
    "anomalie": ["zscore", "spc", "ewma_cusum"],
}


def dispatch(intent: dict) -> dict:
    """Retourne la liste des spécialistes à exécuter pour cet intent."""
    try:
        intention = intent.get("intention")
        if not intention:
            return {
                "error": "Intent sans intention — impossible de dispatcher S3",
                "specialists": [],
            }
        specialists = list(INTENTION_SPECIALISTS.get(intention, []))
        if not specialists:
            return {
                "error": f"Intention non supportée par S3 : {intention}",
                "specialists": [],
            }
        return {"error": None, "specialists": specialists}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "specialists": []}
