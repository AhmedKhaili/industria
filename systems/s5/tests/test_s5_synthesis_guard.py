"""Garde-fou synthèse client — fragments cassés (Python pur, zéro LLM)."""

from __future__ import annotations

import re

from systems.s5.prep import polish_client_text, strip_broken_sentences


def test_kruskal_enfin_fragment_removed() -> None:
    raw = (
        "Analyse solide sur CR90 (Cpk = 0.643). "
        "Le test Kruskal-Wallis ( Enfin, le"
    )
    out = polish_client_text(raw)
    assert "Kruskal-Wallis ( Enfin" not in out
    assert "Enfin, le" not in out
    assert "CR90 (Cpk = 0.643)" in out


def test_enfin_comma_le_removed() -> None:
    raw = "Différences significatives (p < 0,001). Puis, Enfin, le"
    out = polish_client_text(raw)
    assert ", Enfin, le" not in out
    assert "p < 0,001)" in out


def test_valid_parentheses_preserved() -> None:
    raw = (
        "Capabilité critique (Cpk = 0.643) et comparaison (p < 0,001) "
        "entre matrices."
    )
    out = polish_client_text(raw)
    assert "(Cpk = 0.643)" in out
    assert "(p < 0,001)" in out
    assert out.count("(") == out.count(")")


def test_le_de_plus_enfin_removed() -> None:
    raw = (
        "Actions correctives immédiates. "
        "Le De plus, le Enfin, il est à noter que la capabilité dépasse le seuil de 1,33."
    )
    out = polish_client_text(raw)
    assert "Enfin" not in out
    assert "De plus, le" not in out
    assert out.endswith("immédiates.")


def test_no_trailing_determiner() -> None:
    for tail in ("le", "Le", "la", "les", "un", "une", "de", "du", "des"):
        raw = f"Procédé conforme. Dernière phrase valide. {tail}"
        out = polish_client_text(raw)
        assert not re.search(rf"\b{re.escape(tail)}\s*$", out, re.I)


def test_unclosed_paren_truncates_to_last_sentence() -> None:
    raw = "Première phrase ok. Deuxième avec (Cpk = 1.0 et suite cassée"
    out = strip_broken_sentences(raw)
    assert "(" not in out or out.count("(") == out.count(")")
    assert out.endswith("ok.") or "ok." in out
