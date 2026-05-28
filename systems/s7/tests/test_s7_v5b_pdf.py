"""Qualité PDF client v5b — phrases, Intention, root cause, parenthèses."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from systems.s5.prep import (
    polish_client_text,
    strip_broken_sentences,
    strip_orphan_parentheses,
)
from systems.s7 import prep
from systems.s7.renderer_stub import _abbrev_cpk_variable

REPO = Path(__file__).resolve().parents[3]
V5C = REPO / "rapport_lisi_v5c.pdf"


def test_strip_broken_and_orphan() -> None:
    raw = "Procédé conforme, Le graphique montre un écart. Le"
    out = polish_client_text(raw)
    assert not out.endswith(",")
    assert not re.search(r"\bLe\s*$", out)
    assert strip_orphan_parentheses("liste (CR70, )") == "liste (CR70)"


def test_kruskal_wallis_enfin_guard() -> None:
    raw = (
        "Variables critiques (Cpk = 0.643). "
        "Le test Kruskal-Wallis ( Enfin, le"
    )
    out = polish_client_text(raw)
    assert "Kruskal-Wallis ( Enfin" not in out
    assert "(Cpk = 0.643)" in out


def test_abbrev_cpk_variable() -> None:
    assert _abbrev_cpk_variable("CR10_INTRADOS_FORME") == "CR10_INTR._FORME"


def test_filter_intention_row() -> None:
    tables = [
        {
            "title": "Contexte d'analyse",
            "columns": ["Champ", "Valeur"],
            "rows": [
                ["Intention", "comparaison_groupes"],
                ["Pièce", "M2L1A1C"],
            ],
        }
    ]
    out = prep.filter_client_metric_tables(tables)
    labels = [r[0] for r in out[0]["rows"]]
    assert "Intention" not in labels


@pytest.mark.skipif(not V5C.is_file(), reason="rapport_lisi_v5c.pdf absent — lancer generate")
def test_v5c_pdf_client_quality() -> None:
    text = "\n".join(
        p.extract_text() or "" for p in PdfReader(str(V5C)).pages
    )
    low = text.lower()
    assert "root cause" not in low
    assert "comparaison_groupes" not in low
    assert not re.search(r",\s*\)", text)
    assert "intention" not in low or "comparaison" not in low
    p2 = PdfReader(str(V5C)).pages[1].extract_text() or ""
    assert "Kruskal-Wallis ( Enfin" not in text
    assert ", Enfin, le" not in text
    assert "Enfin" not in p2
    assert "De plus, le" not in p2
    assert p2.count("(") == p2.count(")")
    for sent in re.split(r"(?<=[.!?…])\s+", p2):
        s = sent.strip()
        if len(s) < 4:
            continue
        assert not s.endswith(","), f"phrase finissant par virgule : {s!r}"
        assert not re.search(r"\best,\s*$", s, re.I)
        assert s.count("(") == s.count(")"), f"parenthèses non équilibrées : {s!r}"
