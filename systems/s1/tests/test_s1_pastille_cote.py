"""
Tests S1 — désambiguïsation pastille extérieure / intérieure (passage, fournisseur, retaille).
"""

from __future__ import annotations

import pytest

from systems.s1.pipeline import S1Pipeline

TRACEABILITY_YAML = "configs/lisi_aerospace/client_config_traceability.yaml"
CLIENT_YAML = "configs/lisi_aerospace/client_config.yaml"

Q_PASSAGE_EXT = (
    "Comparer CR1 selon le numéro de passage de la pastille extérieure "
    "sur RD4L1A1C au filage"
)
Q_PASSAGE_INT = (
    "Comparer CR1 selon le numéro de passage de la pastille intérieure "
    "sur RD4L1A1C au filage"
)
Q_PASSAGE_AMBIGU = (
    "Comparer CR1 selon le numéro de passage de la pastille sur RD4L1A1C au filage"
)


@pytest.fixture(scope="module")
def s1_trace() -> S1Pipeline:
    return S1Pipeline(TRACEABILITY_YAML)


@pytest.fixture(scope="module")
def s1_client() -> S1Pipeline:
    return S1Pipeline(CLIENT_YAML)


class TestPastillePassageTraceability:
    def test_passage_exterieur_pas_e_seul(self, s1_trace: S1Pipeline) -> None:
        result = s1_trace.run(Q_PASSAGE_EXT)
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["intention"] == "comparaison_groupes"
        assert intent["piece"] == "RD4L1A1C"
        assert intent["operation"] == "FILAGE"
        assert intent["variables"] == ["CR1"]
        assert intent["group_by"] == "PAS_E_Numero_Passage"
        assert intent["clarification_needed"] is False

    def test_passage_interieur_pas_i_seul(self, s1_trace: S1Pipeline) -> None:
        result = s1_trace.run(Q_PASSAGE_INT)
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["variables"] == ["CR1"]
        assert intent["group_by"] == "PAS_I_Numero_Passage"
        assert intent["clarification_needed"] is False

    def test_passage_sans_cote_clarification(self, s1_trace: S1Pipeline) -> None:
        result = s1_trace.run(Q_PASSAGE_AMBIGU)
        assert result.get("error") is None
        intent = result["intent"]
        assert intent["clarification_needed"] is True
        assert "pastille_cote" in intent["clarification_manque"]
        assert intent["group_by"] is None


class TestPastilleFournisseurRetaille:
    def test_fournisseur_exterieur(self, s1_trace: S1Pipeline) -> None:
        result = s1_trace.run(
            "Comparer CR1 par fournisseur de la pastille extérieure sur RD4L1A1C au filage"
        )
        intent = result["intent"]
        assert intent["group_by"] == "PAS_E_Fournisseur"
        assert intent["clarification_needed"] is False

    def test_fournisseur_interieur(self, s1_trace: S1Pipeline) -> None:
        result = s1_trace.run(
            "Comparer CR1 par fournisseur de la pastille intérieure sur RD4L1A1C au filage"
        )
        intent = result["intent"]
        assert intent["group_by"] == "PAS_I_Fournisseur"
        assert intent["clarification_needed"] is False

    def test_retaille_exterieure(self, s1_trace: S1Pipeline) -> None:
        result = s1_trace.run(
            "Comparer CR1 selon la retaille de la pastille extérieure sur RD4L1A1C au filage"
        )
        intent = result["intent"]
        assert intent["group_by"] == "PAS_E_Niveau_Retaille"
        assert intent["clarification_needed"] is False

    def test_retaille_interieure(self, s1_trace: S1Pipeline) -> None:
        result = s1_trace.run(
            "Comparer CR1 selon la retaille de la pastille intérieure sur RD4L1A1C au filage"
        )
        intent = result["intent"]
        assert intent["group_by"] == "PAS_I_Niveau_Retaille"
        assert intent["clarification_needed"] is False


class TestPastilleCoteClientConfig:
    """Même règles sur client_config.yaml (config par défaut)."""

    def test_passage_ext_client_yaml(self, s1_client: S1Pipeline) -> None:
        result = s1_client.run(Q_PASSAGE_EXT)
        intent = result["intent"]
        assert intent["group_by"] == "PAS_E_Numero_Passage"
