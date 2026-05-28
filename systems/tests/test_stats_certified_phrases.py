"""Phrases certifiées P3 — normalité et loi candidate."""

from __future__ import annotations

from systems.stats_format import (
    certified_loi_candidate_phrase,
    certified_normalite_phrase,
    contains_forbidden_loi_wording,
)


def test_normalite_phrase_formats() -> None:
    assert "non normale" in certified_normalite_phrase(
        "non_normale", "Shapiro-Wilk", 0.98, 0.023
    )
    assert "p = 0,023" in certified_normalite_phrase(
        "non_normale", "Shapiro-Wilk", 0.98, 0.023
    )
    assert "p < 0,001" in certified_normalite_phrase(
        "non_normale", "Anderson-Darling", 12.4, 0.0001
    )


def test_normalite_phrase_forbidden_wording() -> None:
    phrase = certified_normalite_phrase("normale", "Shapiro-Wilk", None, 0.12)
    assert not contains_forbidden_loi_wording(phrase)
    assert "loi probable" not in phrase.lower()


def test_loi_candidate_phrase() -> None:
    phrase = certified_loi_candidate_phrase("log_normale", -234.5)
    assert "meilleur ajustement selon AIC" in phrase
    assert "log-normale" in phrase
    assert "loi probable" not in phrase.lower()
