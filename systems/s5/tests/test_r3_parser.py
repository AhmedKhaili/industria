"""Tests parseur R3 batch (sans LLM)."""

from __future__ import annotations

from systems.s5.agents.r3_graph_interpreter import _parse_numbered_response


class TestR3Parser:
    def test_format_n_prefix(self) -> None:
        text = "N. 1. Premier graphique.\nN. 2. Deuxième tableau."
        assert _parse_numbered_response(text, 2) == [
            "Premier graphique.",
            "Deuxième tableau.",
        ]

    def test_format_strict(self) -> None:
        text = "1. Ligne un.\n2. Ligne deux.\n3. Ligne trois."
        assert _parse_numbered_response(text, 3) == [
            "Ligne un.",
            "Ligne deux.",
            "Ligne trois.",
        ]

    def test_inline_numbered(self) -> None:
        text = "1. Alpha. 2. Beta. 3. Gamma."
        got = _parse_numbered_response(text, 3)
        assert got[0] and "Alpha" in got[0]
        assert got[1] and "Beta" in got[1]
        assert got[2] and "Gamma" in got[2]
