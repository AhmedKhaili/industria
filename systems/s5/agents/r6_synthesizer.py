"""
R6 — Synthèse finale adaptée au profil (LLM 14b).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.s5 import llm_client, prep

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    if _estimate_tokens(text) <= max_tokens:
        return text
    ratio = max_tokens / max(_estimate_tokens(text), 1)
    cut = int(len(text) * ratio * 0.95)
    return text[:cut].rsplit(" ", 1)[0] + "…"


def run(
    interpretations: list[dict],
    context: "ClientContext",
    profile: str,
    intent: dict,
    specialist_results: list[dict] | None = None,
) -> dict:
    try:
        cfg = prep.profile_config(context, profile)
        tokens_max = int(cfg.get("tokens_max", 250))
        forbidden = list(cfg.get("forbidden_words", []))
        internal_terms = prep.synthese_forbidden_terms(context)

        corpus = _truncate_to_tokens(
            prep.build_synthesis_corpus(interpretations, specialist_results),
            tokens_max * 2,
        )

        forbidden_note = ""
        if forbidden:
            forbidden_note = (
                "Ne utilise PAS ces termes : " + ", ".join(forbidden) + ".\n"
            )
        internal_note = (
            "N'utilise JAMAIS de noms techniques internes (identifiants de tableaux, "
            "noms de modules, snake_case type cpk_summary). Rédige pour un rapport qualité.\n"
            "Interdit absolu : « intent S1 », « YAML client », « tableau présente », "
            "références au pipeline ou aux modules IndustrIA.\n"
        )

        prompt = (
            f"Profil lecteur : {profile}\n"
            f"Intention analyse : {intent.get('intention', 'analyse')}\n"
            f"Pièce : {intent.get('piece')}\n"
            f"Opération : {intent.get('operation')}\n"
            f"{forbidden_note}"
            f"{internal_note}"
            "Synthétise en un paragraphe clair les points suivants "
            "(ne invente aucun chiffre). "
            "Pour les p-values : reprends les libellés certifiés tels quels — "
            "jamais « environ 0 », « p = 0,000 » ni « 0,0000 ».\n\n"
            f"{corpus}\n\n"
            "Synthèse :"
        )

        synthese = llm_client.chat(prompt, num_predict=tokens_max * 2)
        if synthese:
            synthese, _ = prep.sanitize_synthesis_text(
                synthese.strip(), internal_terms, forbidden
            )
            return {"error": None, "synthese": synthese, "llm_used": True}

        synthese = corpus.replace("- [", "\n• ").replace("]", ":")[: tokens_max * 5]
        if not synthese.strip():
            synthese = "Synthèse non disponible — résultats techniques ci-dessus."

        return {"error": None, "synthese": synthese.strip(), "llm_used": False}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "synthese": "", "llm_used": False}
