"""
Port RAG S6 — stub sans import enterprise/.
Un provider externe peut être injecté via S6Pipeline(rag_port=...).
"""

from __future__ import annotations

from typing import Protocol


class RagPort(Protocol):
    def search(self, query: str, *, min_relevance: float = 0.7) -> dict:
        ...


class StubRagPort:
    """Aucun document indexé — pipeline non bloqué."""

    def search(self, query: str, *, min_relevance: float = 0.7) -> dict:
        _ = query, min_relevance
        return {
            "results": [],
            "n_found": 0,
            "error": None,
        }
