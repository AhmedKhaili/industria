"""
Heuristiques de parsing S1 — entièrement pilotées par le YAML S0 (dataset.s1_parsing).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def piece_pattern_from_modeles(modeles: list[str]) -> str:
    if not modeles:
        return r"\b([A-Z0-9][A-Z0-9_-]{2,})\b"
    alts = "|".join(re.escape(m) for m in modeles)
    return rf"\b({alts})\b"


def default_operations_synonymes(operations: list[str]) -> dict[str, list[str]]:
    return {op: [op.lower()] for op in operations}


class S1Parsing:
    def __init__(self, context: "ClientContext") -> None:
        self._ctx = context
        self._piece_patterns = list(context.s1_piece_patterns)
        self._op_synonyms = dict(context.s1_operations_synonymes)

    def extract_piece_codes(self, question: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for pattern in self._piece_patterns:
            for match in pattern.finditer(question):
                code = match.group(1) if match.lastindex else match.group(0)
                key = code.upper()
                if key not in seen:
                    seen.add(key)
                    found.append(code.upper())
        return found

    def extract_unknown_piece_codes(self, question: str) -> list[str]:
        active = {m.upper() for m in self._ctx.modeles_actifs}
        return [c for c in self.extract_piece_codes(question) if c.upper() not in active]

    def resolve_valid_pieces(self, question: str) -> list[str]:
        active = {m.upper(): m for m in self._ctx.modeles_actifs}
        valid: list[str] = []
        for code in self.extract_piece_codes(question):
            canon = active.get(code.upper())
            if canon and canon not in valid:
                valid.append(canon)
        return valid

    def operation_in_question(self, question: str) -> str | None:
        q = question.lower()
        for op in self._ctx.operations_actives:
            if re.search(rf"\b{re.escape(op.lower())}\b", q):
                return op
        for op, synonyms in self._op_synonyms.items():
            for syn in synonyms:
                s = syn.lower().strip()
                if not s:
                    continue
                if re.search(rf"(?<![a-z0-9_]){re.escape(s)}(?![a-z0-9_])", q):
                    return op
        return None

    def has_operation_in_question(self, question: str) -> bool:
        return self.operation_in_question(question) is not None

    def has_valid_piece_in_question(self, question: str) -> bool:
        return bool(self.resolve_valid_pieces(question))

    def is_piece_only(self, question: str) -> bool:
        tokens = re.findall(r"[a-z0-9_]+", question, re.IGNORECASE)
        active_upper = {m.upper() for m in self._ctx.modeles_actifs}
        piece_tokens = [t for t in tokens if t.upper() in active_upper]
        other_tokens = [t for t in tokens if t.upper() not in active_upper]
        return len(piece_tokens) == 1 and len(other_tokens) == 0

    def is_unknown_piece_only(self, question: str) -> bool:
        unknown = self.extract_unknown_piece_codes(question)
        if len(unknown) != 1:
            return False
        tokens = re.findall(r"[a-z0-9_]+", question, re.IGNORECASE)
        active_upper = {m.upper() for m in self._ctx.modeles_actifs}
        unknown_upper = unknown[0].upper()
        other = [
            t
            for t in tokens
            if t.upper() not in active_upper and t.upper() != unknown_upper
        ]
        return len(other) == 0

    def match_continuation_piece(self, question: str) -> str | None:
        if not re.search(r"(?:et\s+)?(?:pour|sur)\s+", question, re.IGNORECASE):
            return None
        codes = self.extract_piece_codes(question)
        if not codes:
            return None
        active = {m.upper(): m for m in self._ctx.modeles_actifs}
        for code in reversed(codes):
            if code.upper() in active:
                return active[code.upper()]
        return codes[-1].upper()

    def match_continuation_operation(self, question: str) -> str | None:
        if not re.search(r"(?:et\s+)?(?:au|à)\s", question, re.IGNORECASE):
            return None
        return self.operation_in_question(question)
