"""
Pré-traitement de la question utilisateur — Python pur, zéro LLM.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import dateparser

from systems.s1.parsing import S1Parsing

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_RE_DEPUIS = re.compile(
    r"\bdepuis\s+(\d+)\s*(jour|jours|semaine|semaines|mois|an|ans)\b",
    re.IGNORECASE,
)
_RE_IL_Y_A = re.compile(
    r"\bil\s+y\s+a\s+(\d+)\s*(jour|jours|semaine|semaines|mois)\b",
    re.IGNORECASE,
)
_RE_MOIS_DERNIER = re.compile(r"\b(le\s+)?mois\s+dernier\b", re.IGNORECASE)
_RE_SEMAINE_DERNIERE = re.compile(r"\bla\s+semaine\s+derni[eè]re\b", re.IGNORECASE)
_RE_HIER = re.compile(r"\bhier\b", re.IGNORECASE)
_RE_CAMPAGNE = re.compile(
    r"\b(derni[eè]re\s+campagne|sur\s+la\s+campagne)\b",
    re.IGNORECASE,
)
_RE_DERNIER_LOT = re.compile(r"\bdernier\s+lot\b", re.IGNORECASE)

_CONTINUATION_PREFIXES = (
    "et ",
    "et pour",
    "et au",
    "et sur",
    "et le ",
    "et la ",
    "et les ",
)
_CONTINUATION_ANCHOR_WORDS = (
    "conformite",
    "conformité",
    "cpk",
    "compare",
    "comparer",
    "comparaison",
    "anomalie",
    "dérive",
    "derive",
    "impact",
    "qualite",
    "qualité",
    "matrice",
    "pastille",
    "fournisseur",
    "retaille",
    "vrillage",
    "desaxage",
    "forme",
    "montre",
    "analyse",
    "anomalies",
    "tolerance",
    "tolérance",
)


class Agent1Preprocessor:
    def run(
        self,
        question: str,
        context: "ClientContext",
        session_memory: dict | None = None,
    ) -> dict:
        session_memory = session_memory or {}
        try:
            originale = question.strip()
            normalisee = self._normalize(originale)

            filtres = self._extract_temporal(normalisee, context)
            normalisee = self._inject_session(normalisee, session_memory, context)
            continuation = self._is_continuation(
                originale, normalisee, session_memory, context
            )

            ctx_session = {
                k: session_memory[k]
                for k in ("intention", "piece", "operation", "group_by", "variables")
                if session_memory.get(k) is not None
            }

            return {
                "question_normalisee": normalisee,
                "question_originale": originale,
                "filtres_temporels": filtres,
                "contexte_session": ctx_session,
                "continuation": continuation,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "question_normalisee": (question or "").lower().strip(),
                "question_originale": question,
                "filtres_temporels": {},
                "contexte_session": {},
                "continuation": False,
                "error": str(exc),
            }

    @staticmethod
    def _is_continuation(
        originale: str,
        normalisee: str,
        session_memory: dict,
        context: "ClientContext",
    ) -> bool:
        parsing = S1Parsing(context)
        if not session_memory:
            return False
        if parsing.is_piece_only(normalisee):
            return False
        q = originale.lower().strip()
        if any(q.startswith(p) for p in _CONTINUATION_PREFIXES):
            return True
        tokens = normalisee.split()
        if len(tokens) > 5:
            return False
        if any(w in normalisee for w in _CONTINUATION_ANCHOR_WORDS):
            return False
        has_piece = parsing.has_valid_piece_in_question(normalisee)
        has_op = parsing.has_operation_in_question(normalisee)
        if has_piece and len(tokens) <= 4:
            return True
        if has_op and not has_piece and len(tokens) <= 4:
            return True
        return False

    def _normalize(self, text: str) -> str:
        t = unicodedata.normalize("NFKC", text).lower().strip()
        t = re.sub(r"\s+", " ", t)
        t = re.sub(r"\blepaisseur\b", "epaisseur", t)
        t = re.sub(r"\bo filage\b", "au filage", t)
        return t

    def _extract_temporal(self, question: str, context: "ClientContext") -> dict:
        filtres: dict = {
            "Date_debut": None,
            "Date_fin": None,
            "jeton": None,
        }
        now = datetime.now()

        period = self._parse_calendar_period(question, now)
        if period:
            filtres.update(period)
            return filtres

        cal = self._parse_with_dateparser(question, now)
        if cal:
            filtres.update(cal)
            return filtres

        if _RE_CAMPAGNE.search(question):
            filtres["jeton"] = "EVENT_LATEST_CAMPAIGN"
            return filtres
        if _RE_DERNIER_LOT.search(question):
            filtres["jeton"] = "EVENT_LATEST_LOT"
            return filtres

        return filtres

    @staticmethod
    def _parse_calendar_period(question: str, now: datetime) -> dict | None:
        if _RE_MOIS_DERNIER.search(question):
            first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_prev = first_this - timedelta(days=1)
            first_prev = last_prev.replace(day=1)
            return {
                "Date_debut": first_prev.strftime("%Y-%m-%d"),
                "Date_fin": last_prev.strftime("%Y-%m-%d"),
            }

        if _RE_SEMAINE_DERNIERE.search(question):
            today = now.date()
            start_this_week = today - timedelta(days=today.weekday())
            end_last_week = start_this_week - timedelta(days=1)
            start_last_week = end_last_week - timedelta(days=6)
            return {
                "Date_debut": start_last_week.isoformat(),
                "Date_fin": end_last_week.isoformat(),
            }

        return None

    def _parse_with_dateparser(self, question: str, now: datetime) -> dict | None:
        settings = {
            "PREFER_DATES_FROM": "past",
            "RELATIVE_BASE": now,
            "RETURN_AS_TIMEZONE_AWARE": False,
        }

        phrases: list[str] = []
        for m in _RE_DEPUIS.finditer(question):
            phrases.append(m.group(0))
        for m in _RE_IL_Y_A.finditer(question):
            phrases.append(m.group(0))
        if _RE_HIER.search(question):
            phrases.append("hier")

        if not phrases:
            parsed = dateparser.parse(
                question,
                languages=["fr"],
                settings=settings,
            )
            if parsed:
                phrases = [question]

        for phrase in phrases:
            parsed = dateparser.parse(phrase, languages=["fr"], settings=settings)
            if not parsed:
                continue
            if _RE_DEPUIS.search(phrase) or _RE_IL_Y_A.search(phrase):
                return {
                    "Date_debut": parsed.strftime("%Y-%m-%d"),
                    "Date_fin": now.strftime("%Y-%m-%d"),
                }
            if _RE_HIER.search(phrase):
                d = parsed.strftime("%Y-%m-%d")
                return {"Date_debut": d, "Date_fin": d}

        m = _RE_DEPUIS.search(question) or _RE_IL_Y_A.search(question)
        if m:
            n = int(m.group(1))
            unit = m.group(2).lower()
            if unit.startswith("jour"):
                delta_days = n
            elif unit.startswith("semaine"):
                delta_days = n * 7
            elif unit.startswith("mois"):
                delta_days = n * 30
            else:
                delta_days = n * 365
            debut = now - timedelta(days=delta_days)
            return {
                "Date_debut": debut.strftime("%Y-%m-%d"),
                "Date_fin": now.strftime("%Y-%m-%d"),
            }

        return None

    def _inject_session(self, question: str, session_memory: dict, context: "ClientContext") -> str:
        if not session_memory:
            return question

        parsing = S1Parsing(context)
        piece = parsing.match_continuation_piece(question)
        if piece:
            session_memory["piece"] = piece

        operation = parsing.match_continuation_operation(question)
        if operation:
            session_memory["operation"] = operation

        return question
