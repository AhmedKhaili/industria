"""
A4 — Synthèse actionnelle (LLM 14b) adaptée au profil.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.s5 import llm_client
from systems.s6 import prep

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def run(
    items: list[dict],
    context: "ClientContext",
    profile: str,
    intent: dict,
) -> dict:
    try:
        prof = prep.profile_config(context, profile)
        tokens_max = int(prof.get("tokens_max", 250))
        forbidden = list(prof.get("forbidden_words", []))

        lines = []
        for it in items:
            lines.append(
                f"- [{it['priorite']}] {it.get('action', '')} "
                f"(délai {it['delai']}, {it['responsable']})"
            )
        corpus = "\n".join(lines)

        forbidden_note = ""
        if forbidden:
            forbidden_note = "Ne utilise pas : " + ", ".join(forbidden) + ".\n"

        prompt = (
            f"Profil : {profile}\n"
            f"Pièce : {intent.get('piece')} — Opération : {intent.get('operation')}\n"
            f"{forbidden_note}"
            "Rédige un paragraphe court (pas de liste à puces) qui synthétise "
            "les actions prioritaires ci-dessous. Ne invente aucun chiffre.\n\n"
            f"{corpus}\n\n"
            "Synthèse actionnelle :"
        )

        synthese = llm_client.chat(prompt, num_predict=tokens_max * 2)
        warnings: list[str] = []

        if not synthese:
            synthese = _fallback_paragraph(items)
            llm_used = False
        else:
            llm_used = True

        synthese, w = prep.strip_forbidden(synthese, forbidden)
        warnings.extend(w)
        synthese = prep.truncate_tokens(synthese, tokens_max)

        return {
            "error": None,
            "synthese_action": synthese.strip(),
            "llm_used": llm_used,
            "warnings": warnings,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "synthese_action": _fallback_paragraph(items),
            "llm_used": False,
            "warnings": [],
        }


def _fallback_paragraph(items: list[dict]) -> str:
    if not items:
        return "Aucune action corrective requise — surveillance standard."
    parts = [f"{it['priorite']}: {it.get('action', it['justification'])[:120]}" for it in items[:6]]
    return "Plan d'action : " + " ".join(parts)
