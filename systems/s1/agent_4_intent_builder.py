"""
Construction déterministe de intent.json — Python pur, zéro LLM.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from systems.s1.agent_2_entity_extractor import (
    FACTEUR_LEXICAL_CERTAIN,
    THRESHOLD_AMBIGUOUS,
    THRESHOLD_CERTAIN,
)

from systems.s1.parsing import S1Parsing

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_IMPACT_KEYWORDS = (
    "impact",
    "influence",
    "qui",
    "lequel",
    "meilleur",
    "moins bon",
    "versus",
    "entre",
    "comparer",
)
_GROUPING_PHRASES = (
    "par machine",
    "par fournisseur",
    "par matrice",
    "comparer",
    "comparaison",
)
_CONFORMITE_WORDS = (
    "conforme",
    "conformes",
    "conformité",
    "conformite",
    "bonnes",
    "bonne",
    "qualité",
    "qualite",
    "tolérance",
    "tolerance",
    "cpk",
)
_TENDANCE_WORDS = ("dérive", "derive", "évolution", "evolution", "tendance", "progression")
_ANOMALIE_WORDS = ("anomalie", "aberrant", "suspect", "anormal", "pic")
_VAGUE_PHRASES = (
    "dis moi tout",
    "dit moi tout",
    "parle moi de",
    "explique moi",
    "tout sur le",
    "tout sur la",
)
_RE_COMPARE = re.compile(r"\b(compare|comparer|comparaison)\b")


class Agent4IntentBuilder:
    def run(
        self,
        preprocessed: dict,
        entities: dict,
        resolutions: dict,
        context: "ClientContext",
    ) -> dict:
        try:
            intent = self._build(preprocessed, entities, resolutions, context)
            return {**intent, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {
                "intention": None,
                "piece": None,
                "operation": None,
                "variables": [],
                "group_by": None,
                "filtres": {},
                "clarification_needed": True,
                "clarification_manque": ["piece"],
                "contexte_session": {},
                "error": str(exc),
            }

    def _pick_best(
        self,
        candidates: list[dict],
        resolutions: dict,
        term_key: str,
        value_field: str = "value",
    ) -> tuple[str | None, float]:
        if not candidates:
            return None, 0.0
        top = candidates[0]
        score = float(top.get("score", 0))
        val = top.get(value_field) or top.get("key")
        if score >= THRESHOLD_CERTAIN:
            return val, score
        if THRESHOLD_AMBIGUOUS <= score < THRESHOLD_CERTAIN:
            res = resolutions.get("resolutions", {}).get(term_key)
            if res:
                return res.get("value"), float(res.get("score", score))
        return None, score

    @staticmethod
    def _strip_accents(text: str) -> str:
        decomposed = unicodedata.normalize("NFD", text)
        return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")

    @staticmethod
    def _term_lexical_score(term: str, question: str) -> float:
        if len(term) < 4:
            return 0.0
        t = term.lower().replace("_", " ")
        q = question.lower()
        t_plain = Agent4IntentBuilder._strip_accents(t)
        q_plain = Agent4IntentBuilder._strip_accents(q)
        if len(t_plain) >= 6 and t_plain in q_plain:
            return 1.0
        if re.search(rf"(?<![a-z0-9_]){re.escape(t_plain)}(?![a-z0-9_])", q_plain):
            return 1.0
        words = re.findall(r"[a-z0-9_]+", q_plain)
        best = 0.0
        for w in words:
            fuzzy = max(
                fuzz.ratio(t_plain, w) / 100.0,
                fuzz.token_sort_ratio(t_plain, w) / 100.0,
            )
            if fuzzy >= FACTEUR_LEXICAL_CERTAIN and abs(len(t_plain) - len(w)) > 1:
                continue
            best = max(best, fuzzy)
        if " " in t_plain:
            best = max(best, fuzz.token_sort_ratio(t_plain, q_plain) / 100.0)
        return best

    def _facteur_lexical_score(
        self,
        fk: str,
        question: str,
        context: "ClientContext",
        scope: str | None = None,
    ) -> float:
        scopes = [scope] if scope else [s for s, k, _ in context.iter_facteurs() if k == fk]
        best = 0.0
        for sc in scopes:
            cfg = context.get_facteur_config(fk, sc)
            if not cfg:
                continue
            terms = [fk] + list(cfg.get("synonymes", []))
            best = max(
                best,
                max((self._term_lexical_score(t, question) for t in terms), default=0.0),
            )
        return best

    def _facteur_explicit(
        self,
        fk: str,
        question: str,
        context: "ClientContext",
        scope: str | None = None,
    ) -> bool:
        return (
            self._facteur_lexical_score(fk, question, context, scope)
            >= FACTEUR_LEXICAL_CERTAIN
        )

    def _variable_group_lexical_score(
        self,
        group_key: str,
        question: str,
        context: "ClientContext",
        operation: str | None = None,
    ) -> float:
        ops = [operation] if operation else [o for o, k, _ in context.iter_variables() if k == group_key]
        best = 0.0
        for op in ops:
            cfg = context.entites_variables.get(op, {}).get(group_key, {})
            if not cfg:
                continue
            terms = [group_key] + list(cfg.get("synonymes", []))
            best = max(
                best,
                max((self._term_lexical_score(t, question) for t in terms), default=0.0),
            )
        return best

    def _variable_group_explicit(
        self,
        group_key: str,
        question: str,
        context: "ClientContext",
        operation: str | None = None,
    ) -> bool:
        return (
            self._variable_group_lexical_score(group_key, question, context, operation)
            >= FACTEUR_LEXICAL_CERTAIN
        )

    @staticmethod
    def _parsing(context: "ClientContext") -> S1Parsing:
        return S1Parsing(context)

    @staticmethod
    def _extract_unknown_piece_codes(
        question: str, context: "ClientContext"
    ) -> list[str]:
        return Agent4IntentBuilder._parsing(context).extract_unknown_piece_codes(question)

    @staticmethod
    def _is_unknown_piece_only_question(
        question: str, context: "ClientContext"
    ) -> bool:
        return Agent4IntentBuilder._parsing(context).is_unknown_piece_only(question)

    @staticmethod
    def _resolve_piece_exact(
        question: str, context: "ClientContext"
    ) -> tuple[str | list[str] | None, float]:
        found = Agent4IntentBuilder._parsing(context).resolve_valid_pieces(question)
        if len(found) > 1:
            return found, 1.0
        if len(found) == 1:
            return found[0], 1.0
        return None, 0.0

    @staticmethod
    def _operation_explicit_in_question(
        question: str, context: "ClientContext"
    ) -> str | None:
        return Agent4IntentBuilder._parsing(context).operation_in_question(question)

    @staticmethod
    def _is_piece_only_question(question: str, context: "ClientContext") -> bool:
        return Agent4IntentBuilder._parsing(context).is_piece_only(question)

    @staticmethod
    def _intention_from_keywords(question: str) -> str | None:
        if _RE_COMPARE.search(question):
            return "comparaison_groupes"
        if any(w in question for w in _CONFORMITE_WORDS):
            return "conformite"
        if any(w in question for w in _TENDANCE_WORDS):
            return "tendance"
        if any(w in question for w in _ANOMALIE_WORDS):
            return "anomalie"
        if any(k in question for k in _IMPACT_KEYWORDS):
            return "comparaison_groupes"
        if any(p in question for p in _GROUPING_PHRASES):
            return "comparaison_groupes"
        return None

    @staticmethod
    def _infer_operation_from_tag(
        question: str, piece: str | None, context: "ClientContext"
    ) -> str | None:
        if not piece:
            return None
        q = question.lower()
        matched: list[tuple[int, str, str]] = []
        for op in context.operations_actives:
            for tag in context.get_tags_for(piece, op):
                t = tag.lower()
                if t in q:
                    matched.append((len(t), op, tag))
        if not matched:
            return None
        matched.sort(key=lambda x: x[0], reverse=True)
        longest = matched[0][0]
        ops = {m[1] for m in matched if m[0] == longest}
        if len(ops) == 1:
            return next(iter(ops))
        return None

    @staticmethod
    def _matched_tags_in_question(
        question: str, piece: str, operation: str, context: "ClientContext"
    ) -> list[str]:
        q = question.lower()
        return [
            tag
            for tag in context.get_tags_for(piece, operation)
            if tag.lower() in q
        ]

    def _intention_explicit_in_question(
        self, question: str, entities: dict, resolutions: dict, context: "ClientContext"
    ) -> bool:
        if _RE_COMPARE.search(question):
            return True
        if any(w in question for w in _CONFORMITE_WORDS):
            return True
        if any(w in question for w in _TENDANCE_WORDS):
            return True
        if any(w in question for w in _ANOMALIE_WORDS):
            return True
        if any(k in question for k in _IMPACT_KEYWORDS):
            return True
        if any(p in question for p in _GROUPING_PHRASES):
            return True

        res = resolutions.get("resolutions", {}).get("intention")
        if res and float(res.get("score", 0)) >= THRESHOLD_CERTAIN:
            return True

        for cand in entities.get("intentions_candidates", []):
            if float(cand.get("score", 0)) < THRESHOLD_CERTAIN:
                continue
            key = cand.get("key")
            cfg = context.entites_intentions.get(key, {})
            terms = [key] + list(cfg.get("synonymes", []))
            for term in terms:
                t = (term or "").lower()
                if len(t) >= 4 and t in question:
                    return True
        return False

    def _has_industrial_anchor(self, question: str, context: "ClientContext") -> bool:
        """Signal métier explicite (hors intention sémantique seule)."""
        if self._extract_unknown_piece_codes(question, context):
            return True
        if any(m.lower() in question for m in context.modeles_actifs):
            return True
        if any(op.lower() in question for op in context.operations_actives):
            return True
        for scope, fk, _ in context.iter_facteurs():
            if self._facteur_explicit(fk, question, context, scope):
                return True
        for op, vk, _ in context.iter_variables():
            if self._variable_group_explicit(vk, question, context, op):
                return True
        piece_in_q = next((m for m in context.modeles_actifs if m.lower() in question), None)
        if piece_in_q:
            for op in context.operations_actives:
                for tag in context.get_tags_for(piece_in_q, op):
                    if tag.lower() in question:
                        return True
        return False

    def _resolve_operation(
        self,
        question: str,
        entities: dict,
        resolutions: dict,
        piece: str | None,
        context: "ClientContext",
    ) -> str | None:
        explicit_op = self._operation_explicit_in_question(question, context)
        if explicit_op:
            return explicit_op

        piece_for_tag = piece[0] if isinstance(piece, list) else piece
        if piece_for_tag:
            tag_op = self._infer_operation_from_tag(question, piece_for_tag, context)
            if tag_op:
                return tag_op

        explicit_vars: list[tuple[str, str]] = []
        for op, key, _ in context.iter_variables():
            if self._variable_group_explicit(key, question, context, op):
                explicit_vars.append((op, key))

        if explicit_vars:
            ops = [op for op, _ in explicit_vars if op]
            if len(set(ops)) > 1:
                return None
            if ops and len(set(ops)) == 1:
                return ops[0]

        scoped_ops: list[str] = []
        for f in entities.get("facteurs_candidates", []):
            if float(f.get("score", 0)) < THRESHOLD_AMBIGUOUS:
                continue
            fk = f["key"]
            scope = f.get("operation")
            if not self._facteur_explicit(fk, question, context, scope):
                continue
            if scope and scope != "COMMUN":
                scoped_ops.append(scope)

        if scoped_ops and len(set(scoped_ops)) == 1:
            return scoped_ops[0]

        return None

    def _build(
        self,
        preprocessed: dict,
        entities: dict,
        resolutions: dict,
        context: "ClientContext",
    ) -> dict:
        question = preprocessed.get("question_normalisee", "")

        piece, _piece_score = self._resolve_piece_exact(question, context)
        piece_only = self._is_piece_only_question(question, context)
        unknown_pieces = self._extract_unknown_piece_codes(question, context)
        unknown_piece_only = self._is_unknown_piece_only_question(question, context)

        has_anchor = self._has_industrial_anchor(question, context)

        intention: str | None = None
        if not piece_only:
            if self._intention_explicit_in_question(
                question, entities, resolutions, context
            ):
                intention, intention_score = self._pick_best(
                    entities.get("intentions_candidates", []),
                    resolutions,
                    "intention",
                    value_field="key",
                )
                if intention_score < THRESHOLD_AMBIGUOUS:
                    intention = None
            intention = intention or self._intention_from_keywords(question)

        if any(v in question for v in _VAGUE_PHRASES):
            intention = None

        if piece_only:
            intention = None

        var_groups: list[tuple[str | None, str]] = []
        for op, key, _ in context.iter_variables():
            if self._variable_group_explicit(key, question, context, op):
                var_groups.append((op, key))

        operation = self._resolve_operation(
            question, entities, resolutions, piece, context
        )

        if piece_only:
            operation = None

        if (
            not intention
            and not piece_only
            and has_anchor
            and piece
            and operation
        ):
            intention = "conformite"

        # Variables
        variables: list[str] = []
        piece_for_vars = piece[0] if isinstance(piece, list) else piece

        if piece_for_vars and operation:
            explicit_tags = self._matched_tags_in_question(
                question, piece_for_vars, operation, context
            )
            if explicit_tags:
                variables = list(dict.fromkeys(explicit_tags))
            elif var_groups:
                for op_scope, g in var_groups:
                    if op_scope and op_scope != operation:
                        continue
                    variables.extend(
                        context.resolve_tags_for_variable_group(
                            piece_for_vars, operation, g
                        )
                    )
            else:
                variables = context.get_tags_for(piece_for_vars, operation)
            variables = list(dict.fromkeys(variables))

        # group_by
        group_by: str | list[str] | None = None

        facteur_cols: list[str] = []
        explicit_facteurs: list[tuple[str, str, float]] = []
        for scope, fk, _ in context.iter_facteurs():
            sc = self._facteur_lexical_score(fk, question, context, scope)
            if sc >= FACTEUR_LEXICAL_CERTAIN:
                explicit_facteurs.append((fk, scope, sc))
        explicit_facteurs.sort(key=lambda x: x[2], reverse=True)
        multi_facteur_q = " et " in question or " entre " in question or " qui " in question
        if len(explicit_facteurs) > 1 and not multi_facteur_q:
            explicit_facteurs = [max(explicit_facteurs, key=lambda x: x[2])]

        wants_group_by = intention == "comparaison_groupes" and (
            bool(explicit_facteurs)
            or any(p in question for p in _GROUPING_PHRASES)
            or multi_facteur_q
        )

        if wants_group_by:
            for fk, scope, _lex_sc in explicit_facteurs:
                col = context.facteur_colonne(fk, scope)
                if fk == "machine":
                    col = context.colonnes.get("machine", "Numero Machine")
                if isinstance(col, list):
                    facteur_cols.extend(col)
                elif col:
                    facteur_cols.append(col)

            if len(facteur_cols) > 1:
                group_by = list(dict.fromkeys(facteur_cols))
            elif len(facteur_cols) == 1:
                group_by = facteur_cols[0]

        # Filtres
        filtres: dict = {}
        if piece:
            filtres["piece"] = piece
            if isinstance(piece, list) and len(piece) == 1:
                filtres["piece"] = piece[0]
        if operation:
            filtres["operation"] = operation
        ft = preprocessed.get("filtres_temporels", {})
        for k in ("Date_debut", "Date_fin", "jeton"):
            if ft.get(k):
                filtres[k] = ft[k]

        # Cohérence variables
        if piece_for_vars and operation and variables:
            valid = set(context.get_tags_for(piece_for_vars, operation))
            variables = [v for v in variables if v in valid]

        if piece:
            active_upper = {m.upper() for m in context.modeles_actifs}
            if isinstance(piece, list):
                piece = [p for p in piece if p.upper() in active_upper]
                if not piece:
                    piece = None
            elif piece.upper() not in active_upper:
                piece = None

        piece_inconnue: str | list[str] | None = None

        if piece_only:
            clarification_manque = ["intention", "operation"]
            clarification_needed = True
        elif unknown_pieces and not piece:
            piece_inconnue = unknown_pieces[0] if len(unknown_pieces) == 1 else unknown_pieces
            clarification_manque = ["piece_inconnue"]
            clarification_needed = True
            if unknown_piece_only:
                intention = None
                operation = None
        elif not has_anchor:
            clarification_manque = ["hors_sujet"]
            intention = None
            clarification_needed = True
        else:
            clarification_manque = []
            if not piece:
                clarification_manque.append("piece")
            if not operation:
                clarification_manque.append("operation")
            if not intention:
                clarification_manque.append("intention")
            clarification_needed = bool(clarification_manque)

        ctx_session = dict(preprocessed.get("contexte_session", {}))
        if piece:
            ctx_session["piece"] = piece
        if operation:
            ctx_session["operation"] = operation

        result = {
            "intention": intention,
            "piece": piece,
            "operation": operation,
            "variables": variables,
            "group_by": group_by,
            "filtres": filtres,
            "clarification_needed": clarification_needed,
            "clarification_manque": clarification_manque,
            "contexte_session": ctx_session,
        }
        if piece_inconnue is not None:
            result["piece_inconnue"] = piece_inconnue
        return result
