"""
P2 — intentions portrait_statistique, diagnostic_causal, analyse_complete (LISI).
"""

from __future__ import annotations

import json

import pytest

from systems.s1.pipeline import S1Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"


@pytest.fixture
def s1() -> S1Pipeline:
    return S1Pipeline(YAML_PATH)


def _intent(s1: S1Pipeline, question: str) -> dict:
    out = s1.run(question)
    assert out.get("error") is None, out
    intent = out["intent"]
    assert intent is not None
    assert not intent.get("clarification_needed"), (
        f"clarification inattendue : {intent.get('clarification_manque')}"
    )
    return intent


def _intent_text_dump(intent: dict) -> str:
    return json.dumps(intent, ensure_ascii=False).lower()


class TestS1P2IntentionsLisi:
    def test_portrait_cr90_equator(self, s1: S1Pipeline) -> None:
        intent = _intent(s1, "Analyse-moi CR90_INTRADOS_FORME sur M2L1A1C")
        assert intent["intention"] == "portrait_statistique"
        assert intent["operation"] == "EQUATOR"
        assert intent["piece"] == "M2L1A1C"
        assert "CR90_INTRADOS_FORME" in intent["variables"]

    def test_diagnostic_causal_forme_intrados(self, s1: S1Pipeline) -> None:
        intent = _intent(
            s1, "Quels facteurs influencent la forme intrados de M2L1A1C ?"
        )
        assert intent["intention"] == "diagnostic_causal"
        assert intent["group_by"] == "Ref_Matrice"
        assert intent["operation"] == "EQUATOR"
        assert any("INTRADOS_FORME" in v for v in intent["variables"])

    def test_analyse_complete_veine_equator(self, s1: S1Pipeline) -> None:
        intent = _intent(
            s1, "Analyse complète de la veine sur M2L1A1C à EQUATOR"
        )
        assert intent["intention"] == "analyse_complete"
        assert intent["operation"] == "EQUATOR"
        assert intent["piece"] == "M2L1A1C"
        assert intent["variables"], "variables veine attendues"
        assert all(
            str(v).startswith("VEINE_SCAN_") for v in intent["variables"]
        ), intent["variables"]

    def test_formage_resolves_equator(self, s1: S1Pipeline) -> None:
        intent = _intent(s1, "Portrait statistique au formage de M2L1A1C")
        assert intent["operation"] == "EQUATOR"
        assert intent["intention"] == "portrait_statistique"

    def test_causent_absent_from_intent_values(self, s1: S1Pipeline) -> None:
        questions = [
            "Quels facteurs influencent la forme intrados de M2L1A1C ?",
            "Analyse complète de la veine sur M2L1A1C à EQUATOR",
            "Analyse-moi CR90_INTRADOS_FORME sur M2L1A1C",
        ]
        for q in questions:
            intent = _intent(s1, q)
            assert "causent" not in _intent_text_dump(intent)

    def test_session_continuation_piece_only(self, s1: S1Pipeline) -> None:
        first = _intent(
            s1, "Analyse complète de la veine sur M2L1A1C à EQUATOR"
        )
        second = _intent(s1, "et pour M3L1B ?")
        assert second["intention"] == first["intention"]
        assert second["piece"] == "M3L1B"
        assert second["operation"] == first["operation"]
        assert second["variables"] == first["variables"]
