"""
Tests unitaires S1Parsing et chargement s1_parsing depuis le YAML S0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s1.parsing import S1Parsing, piece_pattern_from_modeles

LISI_YAML = "configs/lisi_aerospace/client_config.yaml"
GENERIC_YAML = "configs/test_generic/client_config.yaml"


@pytest.fixture(scope="module")
def lisi_ctx() -> ClientContext:
    return ClientContext.load(LISI_YAML)


@pytest.fixture(scope="module")
def generic_ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


class TestClientContextParsing:
    def test_lisi_loads_piece_patterns(self, lisi_ctx: ClientContext) -> None:
        assert len(lisi_ctx.s1_piece_patterns) >= 1
        assert "FILAGE" in lisi_ctx.s1_operations_synonymes
        assert "filage" in lisi_ctx.s1_operations_synonymes["FILAGE"]

    def test_generic_loads_different_patterns(self, generic_ctx: ClientContext) -> None:
        assert generic_ctx.operations_actives == ["USINAGE", "CONTROLE"]
        codes = S1Parsing(generic_ctx).extract_piece_codes("Conformite P-A100")
        assert codes == ["P-A100"]

    def test_fallback_pattern_from_modeles(self, tmp_path: Path) -> None:
        yaml_text = """
client: {nom: T}
dataset:
  colonnes: {}
  operations_actives: [OP1]
  modeles_actifs: [ABC-01, XYZ-99]
entites:
  facteurs_analyse: {}
  groupes_variables: {}
  intentions: {}
pieces:
  ABC-01:
    description: x
    operations:
      OP1:
        tags: {T1: {lti: 0, lts: 1, nominal: 0.5}}
"""
        path = tmp_path / "client_config.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        ctx = ClientContext.load(str(path))
        assert len(ctx.s1_piece_patterns) == 1
        found = S1Parsing(ctx).resolve_valid_pieces("Analyse ABC-01")
        assert found == ["ABC-01"]


class TestS1ParsingLisi:
    def test_extract_multiple_pieces(self, lisi_ctx: ClientContext) -> None:
        parsing = S1Parsing(lisi_ctx)
        assert parsing.resolve_valid_pieces("Compare M2L1A1C et M2L1B au filage") == [
            "M2L1A1C",
            "M2L1B",
        ]

    def test_unknown_piece_code(self, lisi_ctx: ClientContext) -> None:
        parsing = S1Parsing(lisi_ctx)
        assert parsing.extract_unknown_piece_codes("Conformite du M9Z3X au filage") == [
            "M9Z3X"
        ]
        assert parsing.resolve_valid_pieces("Conformite du M9Z3X au filage") == []

    def test_operation_synonyms(self, lisi_ctx: ClientContext) -> None:
        parsing = S1Parsing(lisi_ctx)
        assert parsing.operation_in_question("cpk au filage") == "FILAGE"
        assert parsing.operation_in_question("et a lequator") == "EQUATOR"
        assert parsing.operation_in_question("lfilage sur m2l1a1c") == "FILAGE"

    def test_equator_not_in_intrados(self, lisi_ctx: ClientContext) -> None:
        parsing = S1Parsing(lisi_ctx)
        assert parsing.operation_in_question("forme intrados de m2l1a1c") is None

    def test_is_piece_only(self, lisi_ctx: ClientContext) -> None:
        parsing = S1Parsing(lisi_ctx)
        assert parsing.is_piece_only("m2l1a1c") is True
        assert parsing.is_piece_only("conformite m2l1a1c") is False

    def test_continuation_helpers(self, lisi_ctx: ClientContext) -> None:
        parsing = S1Parsing(lisi_ctx)
        assert parsing.match_continuation_piece("et pour M2L1B") == "M2L1B"
        assert parsing.match_continuation_operation("et au equator") == "EQUATOR"
        assert parsing.operation_in_question("et a lequator") == "EQUATOR"
        assert parsing.match_continuation_piece("conformite m2l1a1c") is None


class TestS1ParsingGeneric:
    def test_generic_piece_pattern(self, generic_ctx: ClientContext) -> None:
        parsing = S1Parsing(generic_ctx)
        assert parsing.resolve_valid_pieces("P-B200 au controle") == ["P-B200"]
        assert parsing.extract_unknown_piece_codes("P-Z999 au usinage") == ["P-Z999"]

    def test_generic_operation_synonyms(self, generic_ctx: ClientContext) -> None:
        parsing = S1Parsing(generic_ctx)
        assert parsing.operation_in_question("a l usinage") == "USINAGE"
        assert parsing.operation_in_question("au controle") == "CONTROLE"


class TestPiecePatternFromModeles:
    def test_empty_modeles(self) -> None:
        assert piece_pattern_from_modeles([]) == r"\b([A-Z0-9][A-Z0-9_-]{2,})\b"

    def test_escapes_special_chars(self) -> None:
        pattern = piece_pattern_from_modeles(["P-A100"])
        assert "P-A100" in pattern or "P\\-A100" in pattern
