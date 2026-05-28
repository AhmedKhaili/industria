"""
Tests S5 — interprétation Cpk métier (point E).
"""

from __future__ import annotations

from systems.s5 import prep


def test_cpk_fallback_metier_sous_seuil() -> None:
    text = prep.python_fallback_interpretation(
        {
            "agent": "cp_cpk",
            "status": "success",
            "result": {
                "colonne": "CR70_INTRADOS_FORME",
                "Cpk": 0.75,
                "conforme_EN9100": False,
                "interpretation_Cpk": "Non capable - action corrective",
            },
        }
    )
    assert "CR70" in text
    assert "0.75" in text
    assert "dispersion" in text.lower() or "centrage" in text.lower()


def test_cpk_prompt_includes_metier_consigne() -> None:
    prompt = prep.format_specialist_prompt(
        {
            "agent": "cp_cpk",
            "status": "success",
            "result": {"colonne": "CR1", "Cpk": 1.1, "conforme_EN9100": False},
        }
    )
    assert "dispersion" in prompt.lower()
    assert "centrage" in prompt.lower()
