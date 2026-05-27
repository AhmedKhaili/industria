"""
Génération de questions de clarification — templates Python purs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from data.config import get_profile

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


class Agent5Clarifier:
    def run(
        self,
        intent_incomplet: dict,
        context: "ClientContext",
        user_profile: str = "technicien",
    ) -> dict:
        try:
            _ = get_profile(user_profile)
            manque = intent_incomplet.get("clarification_manque", [])
            propositions = self._build_propositions(manque, context)
            question = self._build_question(manque, propositions, context, intent_incomplet)
            return {
                "question_clarification": question,
                "propositions": propositions,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            manque = intent_incomplet.get("clarification_manque", ["piece"])
            propositions = list(context.modeles_actifs)
            return {
                "question_clarification": self._build_question(
                    manque, propositions, context, intent_incomplet
                ),
                "propositions": propositions,
                "error": str(exc),
            }

    def _build_propositions(self, manque: list[str], context: "ClientContext") -> list:
        if "hors_sujet" in manque:
            return []
        if "piece_inconnue" in manque or "piece" in manque:
            return list(context.modeles_actifs)
        if "operation" in manque:
            return list(context.operations_actives)
        if "intention" in manque:
            return list(context.entites_intentions.keys())
        return list(context.modeles_actifs)

    @staticmethod
    def _build_question(
        manque: list[str],
        propositions: list,
        context: "ClientContext",
        intent_incomplet: dict | None = None,
    ) -> str:
        intent_incomplet = intent_incomplet or {}

        if "hors_sujet" in manque:
            return (
                "Je ne comprends pas cette question. "
                "Posez une question sur vos données de production — "
                "conformité, comparaison de machines, détection de dérives..."
            )

        if "piece_inconnue" in manque:
            code = intent_incomplet.get("piece_inconnue", "?")
            if isinstance(code, list):
                code = ", ".join(str(c) for c in code)
            pieces = ", ".join(str(p) for p in propositions[:12])
            return (
                f"La pièce {code} n'existe pas dans votre dataset. "
                f"Pièces disponibles : {pieces}"
            )

        if "piece" in manque:
            pieces = ", ".join(str(p) for p in propositions[:12])
            return (
                f"Sur quelle pièce souhaitez-vous l'analyse ? "
                f"Pièces disponibles : {pieces}"
            )

        if "operation" in manque:
            ops = ", ".join(str(o) for o in propositions) or ", ".join(
                context.operations_actives
            )
            return f"Sur quelle opération ? {ops} ?"

        if "intention" in manque:
            return (
                "Quel type d'analyse souhaitez-vous ? "
                "Conformité, comparaison, tendance ou détection d'anomalies ?"
            )

        opts = ", ".join(str(p) for p in propositions[:8])
        return f"Pouvez-vous préciser votre demande ? Options : {opts}"
