"""
P7-F2 — encadrés pédagogiques certifiés (zéro LLM, pas de norme inventée).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def cpk_thresholds_from_context(context: "ClientContext") -> list[dict[str, Any]]:
    """Seuils Cpk depuis recommandations.seuils_cpk (configuration client)."""
    rec = context.get_recommandations()
    seuils = rec.get("seuils_cpk") if isinstance(rec, dict) else {}
    if not isinstance(seuils, dict):
        seuils = {}
    out: list[dict[str, Any]] = []
    p1 = seuils.get("p1_sous")
    p2 = seuils.get("p2_sous")
    p3 = seuils.get("p3_sous")
    if p1 is not None:
        out.append(
            {
                "id": "critique",
                "max": float(p1),
                "source": "recommandations.seuils_cpk.p1_sous",
            }
        )
    if p1 is not None and p2 is not None:
        out.append(
            {
                "id": "limite",
                "min": float(p1),
                "max": float(p2),
                "source": "recommandations.seuils_cpk.p2_sous",
            }
        )
    if p2 is not None and p3 is not None:
        out.append(
            {
                "id": "acceptable",
                "min": float(p2),
                "max": float(p3),
                "source": "recommandations.seuils_cpk.p3_sous",
            }
        )
    return out


def build_how_to_read_cpk(
    context: "ClientContext",
    *,
    cpk_present: bool,
    worst_group: str | None,
    min_cpk: float | None,
    min_cpk_source_path: str | None,
) -> dict[str, Any]:
    thresholds = cpk_thresholds_from_context(context)
    paragraphs = [
        "Le Cpk mesure la capabilité du processus par rapport aux tolérances : "
        "plus il est élevé, plus la dispersion est maîtrisée par rapport aux limites.",
        "Repères utilisés dans ce rapport (seuils de lecture définis dans la "
        "configuration client) :",
    ]
    for th in thresholds:
        tid = th.get("id", "")
        if tid == "critique" and th.get("max") is not None:
            paragraphs.append(
                f"— en dessous de {th['max']:.2f} : situation critique ;"
            )
        elif tid == "limite":
            paragraphs.append(
                f"— entre {th.get('min', 1.0):.2f} et {th.get('max', 1.33):.2f} : "
                "limite, surveillance renforcée ;"
            )
        elif tid == "acceptable" and th.get("min") is not None:
            paragraphs.append(
                f"— à partir de {th['min']:.2f} : acceptable sous réserve du contexte client."
            )

    case_note = ""
    if cpk_present and worst_group and min_cpk is not None:
        case_note = (
            f"Dans cette analyse, le Cpk le plus faible est {min_cpk:.2f} "
            f"(groupe {worst_group})."
        )
    elif not cpk_present:
        case_note = (
            "Le Cpk n'a pas été calculé pour cette analyse "
            "(effectif insuffisant ou écart-type nul sur au moins un groupe)."
        )

    return {
        "title": "Comment lire le Cpk ?",
        "cpk_present_in_analysis": cpk_present,
        "paragraphs": paragraphs,
        "thresholds": thresholds,
        "case_note": case_note,
        "case_note_source_path": min_cpk_source_path,
    }
