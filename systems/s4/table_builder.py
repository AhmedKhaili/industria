"""
Descriptions tabulaires à partir des résultats S3 (pour S5, sans images).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from enterprise.report.formatters import format_bool, format_number

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def _canonical_agent(agent: str | None) -> str:
    if not agent:
        return ""
    name = str(agent)
    mapping = {
        "CpCpkSpecialist": "cp_cpk",
        "AnovaKruskalSpecialist": "anova_kruskal",
        "MannKendallSpecialist": "mann_kendall",
        "ZScoreSpecialist": "zscore",
        "SpcSpecialist": "spc",
    }
    return mapping.get(name, name.lower())


def _cpk_table(specialist_results: list[dict]) -> dict | None:
    rows: list[list[Any]] = []
    for result in specialist_results:
        if _canonical_agent(result.get("agent")) != "cp_cpk":
            continue
        if result.get("status") != "success":
            continue
        payload = result.get("result") or {}
        rows.append(
            [
                payload.get("colonne", "?"),
                format_number(payload.get("Cpk"), 3),
                format_number(payload.get("Cp"), 3),
                format_bool(payload.get("conforme_EN9100")),
                payload.get("interpretation_Cpk", "N/A"),
            ]
        )
    if not rows:
        return None
    return {
        "id": "cpk_summary",
        "title": "Capabilité processus (Cp/Cpk)",
        "columns": ["Variable", "Cpk", "Cp", "Conforme EN9100", "Interprétation"],
        "rows": rows,
        "description": (
            f"Capabilité calculée sur {len(rows)} variable(s). "
            "Seuil EN9100 : Cpk ≥ 1,33."
        ),
    }


def _anova_table(specialist_results: list[dict]) -> dict | None:
    for result in specialist_results:
        if _canonical_agent(result.get("agent")) != "anova_kruskal":
            continue
        if result.get("status") != "success":
            continue
        payload = result.get("result") or {}
        return {
            "id": "anova_summary",
            "title": "Comparaison de groupes",
            "columns": ["Méthode", "Statistique", "p-value", "Significatif"],
            "rows": [
                [
                    payload.get("methode_choisie", "N/A"),
                    format_number(payload.get("test_stat"), 4),
                    format_number(payload.get("p_value"), 4),
                    format_bool(payload.get("significatif")),
                ]
            ],
            "description": (
                f"Test {payload.get('methode_choisie', 'N/A')} : "
                f"p={format_number(payload.get('p_value'), 4)}, "
                f"différence {'significative' if payload.get('significatif') else 'non significative'}."
            ),
        }
    return None


def _trend_table(specialist_results: list[dict]) -> dict:
    rows: list[list[Any]] = []
    for result in specialist_results:
        if _canonical_agent(result.get("agent")) != "mann_kendall":
            continue
        if result.get("status") != "success":
            continue
        payload = result.get("result") or {}
        rows.append(
            [
                payload.get("colonne", "?"),
                payload.get("tendance", "N/A"),
                format_number(payload.get("p_value"), 4),
                format_number(payload.get("sen_slope"), 6),
            ]
        )
    if not rows:
        return None
    return {
        "id": "trend_summary",
        "title": "Tendance (Mann-Kendall)",
        "columns": ["Variable", "Tendance", "p-value", "Pente Sen"],
        "rows": rows,
        "description": f"Tendance évaluée sur {len(rows)} variable(s).",
    }


def _intent_context_table(intent: dict, context: "ClientContext") -> dict:
    piece, operation = intent.get("piece"), intent.get("operation")
    filtres = intent.get("filtres") or {}
    if isinstance(piece, list):
        piece = piece[0] if piece else None
    piece = piece or filtres.get("piece")
    operation = operation or filtres.get("operation")
    variables = intent.get("variables") or []
    return {
        "id": "analysis_context",
        "title": "Contexte d'analyse",
        "columns": ["Champ", "Valeur"],
        "rows": [
            ["Intention", intent.get("intention", "N/A")],
            ["Pièce", piece or "N/A"],
            ["Opération", operation or "N/A"],
            ["Variables", ", ".join(str(v) for v in variables[:12]) or "N/A"],
            ["Groupement", str(intent.get("group_by") or "N/A")],
        ],
        "description": "Contexte issu de l'intent S1 et du YAML client.",
    }


def build_tables(
    intent: dict,
    context: "ClientContext",
    specialist_results: list[dict],
    metrics_summary: dict | None = None,
) -> dict:
    try:
        _ = metrics_summary
        tables: list[dict] = []
        tables.append(_intent_context_table(intent, context))

        for builder in (_cpk_table, _anova_table, _trend_table):
            table = builder(specialist_results)
            if table:
                tables.append(table)

        paragraphs = [t["description"] for t in tables if t.get("description")]
        descriptions_tabulaires = "\n\n".join(paragraphs)

        return {
            "error": None,
            "tables": tables,
            "descriptions_tabulaires": descriptions_tabulaires,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "tables": [],
            "descriptions_tabulaires": "",
        }
