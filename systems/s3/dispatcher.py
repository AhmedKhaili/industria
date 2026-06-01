"""
Sélection des spécialistes selon l'intention S1.

P6 phase 1 : classification par familles + fallback INTENTION_SPECIALISTS.
"""

from __future__ import annotations

from systems.s3 import analysis_families

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


def _specialists_fallback_warning(
    intention: str,
    derived: list[str],
    legacy: list[str],
    fallback_reason: str,
) -> dict:
    return {
        "intention": intention,
        "derived_specialists": list(derived),
        "legacy_specialists": list(legacy),
        "fallback_reason": fallback_reason,
    }


def dispatch(intent: dict) -> dict:
    """Retourne la liste des spécialistes à exécuter pour cet intent."""
    try:
        intention = intent.get("intention")
        if not intention:
            return {
                "error": "Intent sans intention — impossible de dispatcher S3",
                "specialists": [],
                "analysis_families": [],
                "analysis_family_warnings": [],
            }
        legacy = _specialists_for_intention(intention, intent)
        plans = analysis_families.classify_analysis_families(intent)
        derived = analysis_families.specialists_from_plans(plans)
        analysis_family_warnings: list[dict] = []
        if derived and derived == legacy:
            specialists = derived
        else:
            specialists = legacy
            if not derived:
                reason = "derived_specialists_empty"
            else:
                reason = "derived_specialists_mismatch_legacy"
            analysis_family_warnings.append(
                _specialists_fallback_warning(intention, derived, legacy, reason)
            )
        families_payload = analysis_families.families_executed_payload(
            plans, family_warnings=analysis_family_warnings
        )
        if not specialists:
            return {
                "error": f"Intention non supportée par S3 : {intention}",
                "specialists": [],
                "analysis_families": families_payload,
                "analysis_family_warnings": analysis_family_warnings,
            }
        return {
            "error": None,
            "specialists": specialists,
            "analysis_families": families_payload,
            "analysis_family_warnings": analysis_family_warnings,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "specialists": [],
            "analysis_families": [],
            "analysis_family_warnings": [],
        }
