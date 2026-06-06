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

_RE_WORD_IMPACT = re.compile(r"\b(impact|influence)\b")
_RE_WORD_COMPARE = re.compile(r"\b(compare|comparer|comparaison|versus|entre)\b")
_RE_WORD_CAUSENT = re.compile(r"\bcausent?\b")
_INTENTION_LEXICAL_MIN = 0.68
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
)


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

    @staticmethod
    def _pastille_side_from_question(question: str) -> str | None:
        """
        Détecte pastille extérieure vs intérieure dans la question.
        Retourne 'ext', 'int', ou None si ambigu / non précisé.
        """
        q = Agent4IntentBuilder._strip_accents(question.lower())
        ext_hit = bool(
            re.search(r"\b(exterieur|exterieure)\b", q)
            or re.search(r"\bpastille\s+ext\b", q)
            or re.search(r"\bext\b", q)
        )
        int_hit = bool(
            re.search(r"\b(interieur|interieure)\b", q)
            or re.search(r"\bpastille\s+int\b", q)
        )
        if ext_hit and int_hit:
            return None
        if ext_hit:
            return "ext"
        if int_hit:
            return "int"
        return None

    def _resolve_facteur_colonnes(
        self,
        fk: str,
        scope: str | None,
        question: str,
        context: "ClientContext",
    ) -> tuple[list[str], bool]:
        """
        Colonnes group_by pour un facteur.
        (colonnes, pastille_cote_ambiguous) — dual colonne_ext/int sans côté précisé.
        """
        if fk == "machine":
            machine = context.colonnes.get("machine", "Numero Machine")
            return ([str(machine)] if machine else []), False

        cfg = context.get_facteur_config(fk, scope)
        if not cfg:
            return [], False

        if "colonne" in cfg:
            col = cfg["colonne"]
            return ([str(col)] if col else []), False

        ext_col = cfg.get("colonne_ext")
        int_col = cfg.get("colonne_int")
        if ext_col and int_col:
            side = self._pastille_side_from_question(question)
            if side == "ext":
                return [str(ext_col)], False
            if side == "int":
                return [str(int_col)], False
            return [], True

        cols: list[str] = []
        if ext_col:
            cols.append(str(ext_col))
        if int_col:
            cols.append(str(int_col))
        return cols, False

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

    def _intention_terms(self, intent_key: str, context: "ClientContext") -> list[str]:
        cfg = context.entites_intentions.get(intent_key, {})
        terms = [intent_key.replace("_", " ")]
        terms.extend(str(s) for s in cfg.get("synonymes", []) if s)
        return terms

    def _score_intention_yaml(
        self, question: str, context: "ClientContext"
    ) -> list[tuple[str, float, int, int]]:
        """(intent_key, score, longest_synonym_len, priorite_yaml) triés par pertinence."""
        ranked: list[tuple[str, float, int, int]] = []
        for key, cfg in context.entites_intentions.items():
            priorite = int(cfg.get("priorite", 50))
            best_score = 0.0
            best_len = 0
            for term in self._intention_terms(key, context):
                t = term.strip().lower()
                if len(t) < 3:
                    continue
                sc = self._term_lexical_score(t, question)
                if sc > best_score or (sc == best_score and len(t) > best_len):
                    best_score = sc
                    best_len = len(t)
            if best_score >= _INTENTION_LEXICAL_MIN:
                ranked.append((key, best_score, best_len, priorite))
        ranked.sort(key=lambda x: (x[3], x[1], x[2]), reverse=True)
        return ranked

    def _resolve_intention(
        self,
        question: str,
        entities: dict,
        resolutions: dict,
        context: "ClientContext",
        *,
        piece_only: bool,
    ) -> str | None:
        if piece_only:
            return None
        if _RE_WORD_CAUSENT.search(question):
            return "diagnostic_causal"

        yaml_ranked = self._score_intention_yaml(question, context)
        if yaml_ranked:
            return yaml_ranked[0][0]

        intention, intention_score = self._pick_best(
            entities.get("intentions_candidates", []),
            resolutions,
            "intention",
            value_field="key",
        )
        if intention and intention_score >= THRESHOLD_AMBIGUOUS:
            return intention

        return self._intention_from_keywords(question)

    @staticmethod
    def _intention_from_keywords(question: str) -> str | None:
        if _RE_WORD_COMPARE.search(question):
            return "comparaison_groupes"
        if any(w in question for w in _CONFORMITE_WORDS):
            return "conformite"
        if any(w in question for w in _TENDANCE_WORDS):
            return "tendance"
        if any(w in question for w in _ANOMALIE_WORDS):
            return "anomalie"
        if _RE_WORD_IMPACT.search(question):
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
        if self._score_intention_yaml(question, context):
            return True
        if _RE_WORD_COMPARE.search(question):
            return True
        if _RE_WORD_CAUSENT.search(question):
            return True
        if any(w in question for w in _CONFORMITE_WORDS):
            return True
        if any(w in question for w in _TENDANCE_WORDS):
            return True
        if any(w in question for w in _ANOMALIE_WORDS):
            return True
        if _RE_WORD_IMPACT.search(question):
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

        intention: str | None = self._resolve_intention(
            question,
            entities,
            resolutions,
            context,
            piece_only=piece_only,
        )

        if any(v in question for v in _VAGUE_PHRASES) and intention not in (
            "analyse_complete",
            "portrait_statistique",
        ):
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
        pastille_cote_ambiguous = False

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

        wants_group_by = intention in (
            "comparaison_groupes",
            "diagnostic_causal",
        ) and (
            bool(explicit_facteurs)
            or any(p in question for p in _GROUPING_PHRASES)
            or multi_facteur_q
            or intention == "diagnostic_causal"
        )

        if wants_group_by:
            for fk, scope, _lex_sc in explicit_facteurs:
                cols, ambiguous = self._resolve_facteur_colonnes(
                    fk, scope, question, context
                )
                if ambiguous:
                    pastille_cote_ambiguous = True
                else:
                    facteur_cols.extend(cols)

            if len(facteur_cols) > 1:
                group_by = list(dict.fromkeys(facteur_cols))
            elif len(facteur_cols) == 1:
                group_by = facteur_cols[0]

        if (
            intention == "diagnostic_causal"
            and not group_by
            and operation == "EQUATOR"
            and (
                self._variable_group_explicit("forme", question, context, "EQUATOR")
                or self._variable_group_explicit("veine", question, context, "EQUATOR")
            )
        ):
            group_by = context.colonnes.get("matrice", "Ref_Matrice")

        if (
            intention == "diagnostic_causal"
            and not group_by
            and piece_for_vars
            and operation
        ):
            group_by = context.get_group_by_defaut(piece_for_vars, operation)

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

        if pastille_cote_ambiguous:
            if "pastille_cote" not in clarification_manque:
                clarification_manque.append("pastille_cote")
            clarification_needed = True
            group_by = None

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
        self._assert_intent_language(result)
        return result

    @staticmethod
    def _assert_intent_language(intent: dict) -> None:
        """Interdit « causent » dans les valeurs texte de l'intent (PHILOSOPHY §28)."""
        for val in intent.values():
            if isinstance(val, str) and "causent" in val.lower():
                raise ValueError("Intent interdit : formulation causale")
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and "causent" in item.lower():
                        raise ValueError("Intent interdit : formulation causale")
