"""
Tests S1 sur configuration LISI réelle.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from systems.s1.pipeline import S1Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"
GENERIC_YAML_PATH = "configs/test_generic/client_config.yaml"


@pytest.fixture(scope="module")
def pipeline() -> S1Pipeline:
    return S1Pipeline(YAML_PATH)


class TestS1:
    def test_1_conformite_explicite(self, pipeline: S1Pipeline) -> None:
        result = pipeline.run(
            "Les pièces M2L1A1C sont-elles conformes au filage ?"
        )
        assert result.get("error") is None
        intent = result["intent"]
        assert intent is not None
        assert intent["intention"] == "conformite"
        assert intent["piece"] == "M2L1A1C"
        assert intent["operation"] == "FILAGE"
        assert intent["clarification_needed"] is False

    def test_2_operation_implicite_depuis_facteur(self, pipeline: S1Pipeline) -> None:
        result = pipeline.run(
            "La matrice a-t-elle un impact sur la forme intrados de M2L1B ?"
        )
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["intention"] == "comparaison_groupes"
        assert intent["piece"] == "M2L1B"
        assert intent["operation"] == "EQUATOR"
        assert intent["group_by"] == "Ref_Matrice"
        assert intent["clarification_needed"] is False

    def test_3_multi_facteurs(self, pipeline: S1Pipeline) -> None:
        result = pipeline.run(
            "Qui d entre la matrice et le four impacte le plus M2L1B ?"
        )
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["intention"] == "comparaison_groupes"
        assert intent["piece"] == "M2L1B"
        assert intent["operation"] == "EQUATOR"
        assert isinstance(intent["group_by"], list)
        assert "Ref_Matrice" in intent["group_by"]
        assert "Numero Machine" in intent["group_by"]
        assert intent["clarification_needed"] is False

    def test_4_expression_temporelle(self, pipeline: S1Pipeline) -> None:
        result = pipeline.run(
            "Est-ce que nos pastilles depuis 2 mois sont bonnes sur M2L1A1C ?"
        )
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["intention"] == "conformite"
        assert intent["piece"] == "M2L1A1C"
        assert intent["operation"] == "FILAGE"
        assert "Date_debut" in intent["filtres"]
        date_debut = datetime.strptime(intent["filtres"]["Date_debut"], "%Y-%m-%d")
        expected = datetime.now() - timedelta(days=60)
        assert abs((date_debut - expected).days) <= 1
        assert intent["clarification_needed"] is False

    def test_5_clarification_piece_absente(self, pipeline: S1Pipeline) -> None:
        result = pipeline.run(
            "Est-ce que le fournisseur a un impact sur la qualité ?"
        )
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["clarification_needed"] is True
        assert result["clarification"] is not None
        assert len(result["clarification"]["propositions"]) > 0


@pytest.fixture(scope="module")
def generic_pipeline() -> S1Pipeline:
    return S1Pipeline(GENERIC_YAML_PATH)


class TestS1GenericClient:
    def test_piece_pattern_from_yaml(self, generic_pipeline: S1Pipeline) -> None:
        result = generic_pipeline.run("Les pieces P-A100 sont conformes a l usinage ?")
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["piece"] == "P-A100"
        assert intent["operation"] == "USINAGE"
        assert intent["intention"] == "conformite"
        assert intent["clarification_needed"] is False

    def test_unknown_piece_generic_pattern(self, generic_pipeline: S1Pipeline) -> None:
        result = generic_pipeline.run("Conformite de P-Z999 au usinage")
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["clarification_needed"] is True
        assert "piece_inconnue" in intent["clarification_manque"]
        assert intent.get("piece_inconnue") == "P-Z999"
