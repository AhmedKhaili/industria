"""
Tests d'intégration S1 — cas limites, mémoire de session, clarifications.
"""

from __future__ import annotations

import pytest

from systems.s1.pipeline import S1Pipeline

LISI_YAML = "configs/lisi_aerospace/client_config.yaml"
GENERIC_YAML = "configs/test_generic/client_config.yaml"


@pytest.fixture
def fresh_lisi() -> S1Pipeline:
    return S1Pipeline(LISI_YAML)


@pytest.fixture
def fresh_generic() -> S1Pipeline:
    return S1Pipeline(GENERIC_YAML)


class TestS1Clarifications:
    def test_piece_inconnue_message(self, fresh_lisi: S1Pipeline) -> None:
        result = fresh_lisi.run("Conformite du M9Z3X au filage")
        intent = result["intent"]
        clarif = result["clarification"]
        assert result.get("error") is None
        assert intent["clarification_needed"] is True
        assert intent["clarification_manque"] == ["piece_inconnue"]
        assert intent.get("piece_inconnue") == "M9Z3X"
        assert clarif is not None
        assert "M9Z3X" in clarif["question_clarification"]
        assert "n'existe pas" in clarif["question_clarification"]

    def test_piece_seule_demande_intention_et_operation(
        self, fresh_lisi: S1Pipeline
    ) -> None:
        result = fresh_lisi.run("M2L1A1C")
        intent = result["intent"]
        assert intent["piece"] == "M2L1A1C"
        assert intent["intention"] is None
        assert intent["operation"] is None
        assert set(intent["clarification_manque"]) == {"intention", "operation"}

    def test_multi_operation_ambigue(self, fresh_lisi: S1Pipeline) -> None:
        result = fresh_lisi.run(
            "Compare la forme intrados et lepaisseur centrale de M2L1A1C"
        )
        intent = result["intent"]
        assert intent["piece"] == "M2L1A1C"
        assert intent["operation"] is None
        assert intent["clarification_needed"] is True
        assert "operation" in intent["clarification_manque"]

    def test_hors_sujet_sans_ancrage(self, fresh_lisi: S1Pipeline) -> None:
        result = fresh_lisi.run("Quelle est la météo demain ?")
        intent = result["intent"]
        assert intent["clarification_needed"] is True
        assert "hors_sujet" in intent["clarification_manque"]


class TestS1CompareAndTags:
    def test_compare_deux_pieces(self, fresh_lisi: S1Pipeline) -> None:
        result = fresh_lisi.run("Compare M2L1A1C et M2L1B au filage")
        intent = result["intent"]
        assert intent["intention"] == "comparaison_groupes"
        assert intent["piece"] == ["M2L1A1C", "M2L1B"]
        assert intent["operation"] == "FILAGE"
        assert intent["clarification_needed"] is False

    def test_tag_veine_scan_infer_equator(self, fresh_lisi: S1Pipeline) -> None:
        result = fresh_lisi.run(
            "Montre moi le VEINE_SCAN_1_MAX_INTRADOS de M2L1A1C"
        )
        intent = result["intent"]
        assert intent["piece"] == "M2L1A1C"
        assert intent["operation"] == "EQUATOR"
        assert "VEINE_SCAN_1_MAX_INTRADOS" in intent["variables"]

    def test_typo_o_filage_et_lepaisseur(self, fresh_lisi: S1Pipeline) -> None:
        result = fresh_lisi.run(
            "slt jveux voir si le cpk est bo sur M4L1B o filage"
        )
        intent = result["intent"]
        assert intent["operation"] == "FILAGE"
        assert intent["piece"] == "M4L1B"
        assert intent["clarification_needed"] is False


class TestS1SessionMemory:
    def test_continuation_operation(self, fresh_lisi: S1Pipeline) -> None:
        r1 = fresh_lisi.run("Cpk du M4L1A1C au filage")
        assert r1["intent"]["intention"] == "conformite"
        assert r1["intent"]["clarification_needed"] is False

        r2 = fresh_lisi.run("et a lequator ?")
        intent = r2["intent"]
        assert intent["intention"] == "conformite"
        assert intent["piece"] == "M4L1A1C"
        assert intent["operation"] == "EQUATOR"
        assert intent["clarification_needed"] is False

    def test_continuation_piece(self, fresh_lisi: S1Pipeline) -> None:
        fresh_lisi.run("Les pieces M2L1A1C sont conformes au filage ?")
        r2 = fresh_lisi.run("et pour M2L1B")
        intent = r2["intent"]
        assert intent["intention"] == "conformite"
        assert intent["piece"] == "M2L1B"
        assert intent["operation"] == "FILAGE"

    def test_piece_seule_ne_pas_continuer_session(
        self, fresh_lisi: S1Pipeline
    ) -> None:
        fresh_lisi.run("Cpk du M4L1A1C au filage")
        r2 = fresh_lisi.run("M2L1A1C")
        intent = r2["intent"]
        assert intent["intention"] is None
        assert "intention" in intent["clarification_manque"]


class TestS1GenericIntegration:
    def test_controle_operation(self, fresh_generic: S1Pipeline) -> None:
        result = fresh_generic.run("Rugosite de P-A100 au controle")
        intent = result["intent"]
        assert intent["piece"] == "P-A100"
        assert intent["operation"] == "CONTROLE"

    def test_second_piece_model(self, fresh_generic: S1Pipeline) -> None:
        result = fresh_generic.run("Conformite P-B200 a l usinage")
        intent = result["intent"]
        assert intent["piece"] == "P-B200"
        assert intent["operation"] == "USINAGE"
