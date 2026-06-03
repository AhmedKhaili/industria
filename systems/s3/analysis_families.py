"""
P6 — Cartographie analytique : classification des familles F1–F7 (Python pur).

Phase 1 : socle méthodologique ; les specialists exécutés restent alignés
sur INTENTION_SPECIALISTS via équivalence vérifiée en tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Ordre méthodologique (cours de statistiques) — priorité par défaut 1..7
FAMILY_UNIVARIATE = "univariate"  # F1
FAMILY_QUALI_QUANTI = "bivariate_quali_quanti"  # F2
FAMILY_QUANTI_QUANTI = "bivariate_quanti_quanti"  # F3
FAMILY_QUALI_QUALI = "bivariate_quali_quali"  # F4
FAMILY_MULTIVARIATE = "multivariate_explanatory"  # F5
FAMILY_DIMENSION_REDUCTION = "dimension_reduction"  # F6
FAMILY_TEMPORAL_SPC = "temporal_spc"  # F7

FAMILY_ORDER: tuple[str, ...] = (
    FAMILY_UNIVARIATE,
    FAMILY_QUALI_QUANTI,
    FAMILY_QUANTI_QUANTI,
    FAMILY_QUALI_QUALI,
    FAMILY_MULTIVARIATE,
    FAMILY_DIMENSION_REDUCTION,
    FAMILY_TEMPORAL_SPC,
)

FAMILY_PRIORITY: dict[str, int] = {
    fid: idx + 1 for idx, fid in enumerate(FAMILY_ORDER)
}

_PORTRAIT_SPECIALISTS = ["descriptive", "normality", "distribution_fit"]


@dataclass
class AnalysisFamilyPlan:
    """Plan d'analyse pour une famille P6."""

    family_id: str
    target_variables: list[str] = field(default_factory=list)
    grouping_variables: list[str] = field(default_factory=list)
    specialists: list[str] = field(default_factory=list)
    chart_types: list[str] = field(default_factory=list)
    priority: int = 0
    execution_order: int = 0
    warnings: list[str] = field(default_factory=list)


def _variables(intent: dict) -> list[str]:
    raw = intent.get("variables") or []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    return [str(v).strip() for v in raw if str(v).strip()]


def _grouping(intent: dict) -> list[str]:
    gb = intent.get("group_by")
    if gb is None:
        return []
    if isinstance(gb, str):
        return [gb] if gb.strip() else []
    return [str(g).strip() for g in gb if str(g).strip()]


def _plan(
    family_id: str,
    intent: dict,
    *,
    specialists: list[str],
    execution_order: int | None = None,
    warnings: list[str] | None = None,
) -> AnalysisFamilyPlan:
    prio = FAMILY_PRIORITY.get(family_id, 99)
    return AnalysisFamilyPlan(
        family_id=family_id,
        target_variables=_variables(intent),
        grouping_variables=_grouping(intent),
        specialists=list(specialists),
        chart_types=[],
        priority=prio,
        execution_order=execution_order if execution_order is not None else prio,
        warnings=list(warnings or []),
    )


def _families_for_intention(intention: str, intent: dict) -> list[AnalysisFamilyPlan]:
    """Construit les plans famille selon l'intention S1 (mapping P6 §4.4)."""
    plans: list[AnalysisFamilyPlan] = []

    if intention == "portrait_statistique":
        plans.append(
            _plan(
                FAMILY_UNIVARIATE,
                intent,
                specialists=list(_PORTRAIT_SPECIALISTS),
            )
        )
        return plans

    if intention == "comparaison_groupes":
        plans.append(
            _plan(
                FAMILY_QUALI_QUANTI,
                intent,
                specialists=["anova_kruskal", "cp_cpk"],
            )
        )
        return plans

    if intention == "diagnostic_causal":
        plans.append(
            _plan(
                FAMILY_QUALI_QUANTI,
                intent,
                specialists=["anova_kruskal"],
            )
        )
        return plans

    if intention == "conformite":
        plans.append(
            _plan(
                FAMILY_UNIVARIATE,
                intent,
                specialists=["cp_cpk"],
                execution_order=1,
            )
        )
        plans.append(
            _plan(
                FAMILY_TEMPORAL_SPC,
                intent,
                specialists=["zscore", "spc"],
                execution_order=2,
            )
        )
        return plans

    if intention == "tendance":
        plans.append(
            _plan(
                FAMILY_TEMPORAL_SPC,
                intent,
                specialists=["mann_kendall", "ewma_cusum", "regression"],
            )
        )
        return plans

    if intention == "anomalie":
        plans.append(
            _plan(
                FAMILY_TEMPORAL_SPC,
                intent,
                specialists=["zscore", "spc", "ewma_cusum"],
            )
        )
        return plans

    if intention == "analyse_complete":
        plans.append(
            _plan(
                FAMILY_UNIVARIATE,
                intent,
                specialists=list(_PORTRAIT_SPECIALISTS),
                execution_order=1,
            )
        )
        plans.append(
            _plan(
                FAMILY_QUANTI_QUANTI,
                intent,
                specialists=["correlation"],
                execution_order=2,
            )
        )
        plans.append(
            _plan(
                FAMILY_UNIVARIATE,
                intent,
                specialists=["cp_cpk"],
                execution_order=3,
                warnings=["cp_cpk planifié en extension capabilité (F1)"],
            )
        )
        if intent.get("group_by"):
            plans.append(
                _plan(
                    FAMILY_QUALI_QUANTI,
                    intent,
                    specialists=["anova_kruskal"],
                    execution_order=4,
                )
            )
        return plans

    return plans


def classify_analysis_families(
    intent: dict,
    df_schema: dict[str, Any] | None = None,
    context: Any | None = None,
) -> list[AnalysisFamilyPlan]:
    """
    Classifie la question en familles F1–F7 (Python pur).

    Phase 1 : principalement guidé par ``intent["intention"]``.
    ``df_schema`` et ``context`` réservés aux phases suivantes (typage S2).
    """
    del df_schema, context  # phase 1 — non utilisés
    intention = str(intent.get("intention") or "").strip()
    if not intention:
        return []
    return _families_for_intention(intention, intent)


def specialists_from_plans(plans: list[AnalysisFamilyPlan]) -> list[str]:
    """Fusionne les specialists des plans (ordre execution_order, dédoublonnage)."""
    ordered = sorted(plans, key=lambda p: (p.execution_order, p.priority))
    out: list[str] = []
    seen: set[str] = set()
    for plan in ordered:
        for spec in plan.specialists:
            if spec not in seen:
                seen.add(spec)
                out.append(spec)
    return out


def families_executed_payload(
    plans: list[AnalysisFamilyPlan],
    *,
    family_warnings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Représentation JSON-serializable pour metrics_summary / trace."""
    extra = list(family_warnings or [])
    rows: list[dict[str, Any]] = []
    for p in sorted(plans, key=lambda x: (x.execution_order, x.priority)):
        row_warnings = list(p.warnings)
        if extra:
            row_warnings = row_warnings + extra
        rows.append(
            {
                "family_id": p.family_id,
                "priority": p.priority,
                "execution_order": p.execution_order,
                "target_variables": list(p.target_variables),
                "grouping_variables": list(p.grouping_variables),
                "specialists": list(p.specialists),
                "warnings": row_warnings,
            }
        )
    return rows
