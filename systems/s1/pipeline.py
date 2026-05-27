"""
Orchestration S1 — compréhension de la question → intent.json ou clarification.
"""

from __future__ import annotations

from systems.s1.agent_1_preprocessor import Agent1Preprocessor
from systems.s1.agent_2_entity_extractor import (
    THRESHOLD_AMBIGUOUS,
    THRESHOLD_CERTAIN,
    Agent2EntityExtractor,
)
from systems.s1.agent_3_disambiguator import Agent3Disambiguator
from systems.s1.agent_4_intent_builder import Agent4IntentBuilder
from systems.s1.agent_5_clarifier import Agent5Clarifier
from systems.s1.client_context import ClientContext
from systems.s1.parsing import S1Parsing

_CONTINUATION_PREFIXES = (
    "et ",
    "et pour",
    "et au",
    "et sur",
    "et le ",
    "et la ",
    "et les ",
)
_SESSION_FIELDS = ("intention", "piece", "operation", "group_by", "variables")


class S1Pipeline:
    def __init__(self, yaml_path: str) -> None:
        self.ctx = ClientContext.load(yaml_path)
        self.a1 = Agent1Preprocessor()
        self.a2 = Agent2EntityExtractor()
        self.a3 = Agent3Disambiguator()
        self.a4 = Agent4IntentBuilder()
        self.a5 = Agent5Clarifier()
        self.session_memory: dict = {}

    def run(self, question: str, user_profile: str = "technicien") -> dict:
        trace: list[dict] = []
        try:
            pre = self.a1.run(question, self.ctx, self.session_memory)
            trace.append({"step": "agent_1_preprocessor", "ok": pre.get("error") is None})

            entities = self.a2.run(pre["question_normalisee"], self.ctx)
            trace.append({"step": "agent_2_entity_extractor", "ok": entities.get("error") is None})

            ambiguites = self._collect_ambiguities(pre["question_normalisee"], entities)
            resolutions = {"resolutions": {}}
            if ambiguites:
                resolutions = self.a3.run(ambiguites, self.ctx)
                trace.append(
                    {
                        "step": "agent_3_disambiguator",
                        "ok": resolutions.get("error") is None,
                        "n": len(ambiguites),
                    }
                )

            intent = self.a4.run(pre, entities, resolutions, self.ctx)
            trace.append(
                {
                    "step": "agent_4_intent_builder",
                    "ok": intent.get("error") is None,
                    "clarification_needed": intent.get("clarification_needed"),
                }
            )

            if (
                pre.get("continuation")
                and self.session_memory
                and not S1Parsing(self.ctx).is_piece_only(pre["question_normalisee"])
            ):
                intent = self._merge_session_continuation(
                    intent, pre, entities, resolutions
                )

            clarification = None
            if intent.get("clarification_needed"):
                clarification = self.a5.run(intent, self.ctx, user_profile)
                trace.append({"step": "agent_5_clarifier", "ok": clarification.get("error") is None})
                return {
                    "intent": intent,
                    "clarification": clarification,
                    "pipeline_trace": trace,
                    "error": None,
                }

            self._update_session(intent)
            return {
                "intent": intent,
                "clarification": None,
                "pipeline_trace": trace,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "intent": None,
                "clarification": None,
                "pipeline_trace": trace,
                "error": str(exc),
            }

    @staticmethod
    def _is_continuation(question: str, session_memory: dict) -> bool:
        """Délègue à agent_1 — conservé pour compatibilité interne."""
        if not session_memory:
            return False
        q = question.lower().strip()
        if any(q.startswith(p) for p in _CONTINUATION_PREFIXES):
            return True
        return False

    def _merge_session_continuation(
        self, intent: dict, pre: dict, entities: dict, resolutions: dict
    ) -> dict:
        question = pre.get("question_normalisee", "")
        session = self.session_memory
        merged = dict(intent)

        parsing = S1Parsing(self.ctx)
        piece_in_q = parsing.has_valid_piece_in_question(question)
        op_in_q = parsing.has_operation_in_question(question)
        op_explicit = parsing.operation_in_question(question)

        if not piece_in_q and session.get("piece"):
            merged["piece"] = session["piece"]

        if not op_in_q and session.get("operation"):
            merged["operation"] = session["operation"]
        elif op_in_q:
            merged["operation"] = op_explicit

        if not self.a4._intention_explicit_in_question(
            question, entities, resolutions, self.ctx
        ):
            if session.get("intention"):
                merged["intention"] = session["intention"]

        explicit_grouping = any(
            kw in question
            for kw in (
                "fournisseur",
                "matrice",
                "retaille",
                "machine",
                "presse",
                "comparer",
                "comparaison",
                "impact",
                "entre",
            )
        )
        if not explicit_grouping and session.get("group_by") is not None:
            merged["group_by"] = session["group_by"]

        if op_in_q and session.get("operation") and merged.get("operation") != session.get(
            "operation"
        ):
            merged["group_by"] = None

        if merged.get("piece") and merged.get("operation"):
            if not merged.get("variables") and session.get("variables") and not op_in_q:
                merged["variables"] = list(session["variables"])
            elif op_in_q:
                merged["variables"] = self.ctx.get_tags_for(
                    merged["piece"][0]
                    if isinstance(merged["piece"], list)
                    else merged["piece"],
                    merged["operation"],
                )

        filtres = dict(merged.get("filtres") or {})
        if merged.get("piece"):
            filtres["piece"] = merged["piece"]
        if merged.get("operation"):
            filtres["operation"] = merged["operation"]
        ft = pre.get("filtres_temporels", {})
        for k in ("Date_debut", "Date_fin", "jeton"):
            if ft.get(k):
                filtres[k] = ft[k]
        merged["filtres"] = filtres

        manque: list[str] = []
        if merged.get("clarification_manque") and "hors_sujet" in merged["clarification_manque"]:
            manque = ["hors_sujet"]
        else:
            if not merged.get("piece"):
                manque.append("piece")
            if not merged.get("operation"):
                manque.append("operation")
            if not merged.get("intention"):
                manque.append("intention")

        merged["clarification_manque"] = manque
        merged["clarification_needed"] = bool(manque)

        ctx_session = {
            k: merged[k]
            for k in ("piece", "operation", "intention", "group_by")
            if merged.get(k) is not None
        }
        merged["contexte_session"] = ctx_session
        return merged

    def _collect_ambiguities(self, question: str, entities: dict) -> list[dict]:
        amb: list[dict] = []

        def maybe_add(terme: str, candidates: list[dict], field: str = "value") -> None:
            if not candidates:
                return
            top = candidates[0]
            score = float(top.get("score", 0))
            if THRESHOLD_AMBIGUOUS <= score < THRESHOLD_CERTAIN:
                amb.append(
                    {
                        "terme": terme,
                        "candidats": [
                            {
                                "value": c.get(field) or c.get("key"),
                                "description": str(c.get(field) or c.get("key")),
                                "score": c.get("score"),
                            }
                            for c in candidates[:3]
                        ],
                    }
                )

        maybe_add("piece", entities.get("pieces_candidates", []))
        maybe_add("operation", entities.get("operations_candidates", []))
        maybe_add("intention", entities.get("intentions_candidates", []), field="key")

        for f in entities.get("facteurs_candidates", [])[:3]:
            sc = float(f.get("score", 0))
            if THRESHOLD_AMBIGUOUS <= sc < THRESHOLD_CERTAIN:
                amb.append(
                    {
                        "terme": f.get("key", "facteur"),
                        "candidats": [
                            {
                                "value": f["key"],
                                "description": f.get("value", f["key"]),
                                "score": sc,
                            }
                        ],
                    }
                )
        return amb

    def _update_session(self, intent: dict) -> None:
        self.session_memory = {
            k: intent[k]
            for k in _SESSION_FIELDS
            if intent.get(k) is not None
        }
