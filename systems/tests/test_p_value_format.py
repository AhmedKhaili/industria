"""Formatage p-value — zéro affichage trompeur 0,0000 dans specialist_results."""

from __future__ import annotations

import json
import re

import pytest

from systems.stats_format import (
    enrich_specialist_results_display,
    format_p_value,
)


def test_format_p_value_below_threshold() -> None:
    assert format_p_value(1e-15) == "p < 0,001"
    assert format_p_value(0.0005) == "p < 0,001"


def test_format_p_value_three_decimals() -> None:
    assert format_p_value(0.02341) == "p = 0,023"
    assert format_p_value(0.05) == "p = 0,050"


def test_specialist_results_never_show_misleading_p_display() -> None:
    results = [
        {
            "agent": "anova_kruskal",
            "status": "success",
            "result": {
                "p_value": 1e-20,
                "significatif": True,
                "methode_choisie": "Kruskal-Wallis",
                "alpha": 0.05,
            },
        },
        {
            "agent": "dunn_posthoc",
            "status": "success",
            "result": {
                "paires_significatives": [
                    {
                        "groupe_a": "G1",
                        "groupe_b": "G2",
                        "p_value": 1e-12,
                        "significatif": True,
                    }
                ],
            },
        },
    ]
    enrich_specialist_results_display(results)
    blob = json.dumps(results, ensure_ascii=False)
    assert "0.0000" not in blob
    assert "0,0000" not in blob
    anova = results[0]["result"]
    assert anova["p_value_display"] == "p < 0,001"
    assert "p < 0,001" in anova["significance_phrase"]
    pair = results[1]["result"]["paires_significatives"][0]
    assert pair["p_value_display"] == "p < 0,001"
    assert "0.0000" not in pair["libelle"]
    for row in results:
        payload = row.get("result") or {}
        for key, val in payload.items():
            if isinstance(val, str) and re.search(r"0[,.]0000?", val):
                if "p <" not in val.lower():
                    pytest.fail(f"Affichage trompeur {key}={val!r}")
