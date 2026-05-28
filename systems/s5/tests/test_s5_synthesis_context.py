"""Synthèse R6 — contexte réel, pas de placeholders."""

from __future__ import annotations

from systems.s5 import prep


def test_sanitize_removes_piece_a_placeholder() -> None:
    raw = "Analyse sur la pièce A, opération B, variables C, D et E."
    out, warns = prep.sanitize_synthesis_text(raw, [], [])
    low = out.lower()
    assert "pièce a" not in low
    assert warns


def test_intent_variables_line() -> None:
    line = prep._intent_variables_line(
        {"variables": ["CR90_INTRADOS_FORME", "CR10_INTRADOS_FORME"]}
    )
    assert "CR90" in line
    assert "CR10" in line
