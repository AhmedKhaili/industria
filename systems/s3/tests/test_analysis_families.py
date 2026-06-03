"""
Tests P6 phase 1 — classification des familles d'analyse S3.
"""

from __future__ import annotations

import pytest

from systems.s3 import analysis_families
from systems.s3.analysis_families import (
    FAMILY_ORDER,
    FAMILY_QUALI_QUANTI,
    FAMILY_QUANTI_QUANTI,
    FAMILY_TEMPORAL_SPC,
    FAMILY_UNIVARIATE,
)
from systems.s3.dispatcher import INTENTION_SPECIALISTS, _specialists_for_intention, dispatch


class TestFamilyOrder:
    def test_seven_families_in_course_order(self) -> None:
        assert len(FAMILY_ORDER) == 7
        assert FAMILY_ORDER[0] == FAMILY_UNIVARIATE
        assert FAMILY_ORDER[-1] == FAMILY_TEMPORAL_SPC


class TestClassifyAnalysisFamilies:
    def test_portrait_single_family_f1(self) -> None:
        intent = {
            "intention": "portrait_statistique",
            "variables": ["CR90_INTRADOS_FORME"],
            "piece": "M2L1A1C",
        }
        plans = analysis_families.classify_analysis_families(intent)
        assert len(plans) == 1
        assert plans[0].family_id == FAMILY_UNIVARIATE
        assert plans[0].target_variables == ["CR90_INTRADOS_FORME"]

    def test_comparaison_f2(self) -> None:
        intent = {
            "intention": "comparaison_groupes",
            "variables": ["CR90_INTRADOS_FORME"],
            "group_by": "Ref_Matrice",
        }
        plans = analysis_families.classify_analysis_families(intent)
        assert [p.family_id for p in plans] == [FAMILY_QUALI_QUANTI]

    def test_analyse_complete_f1_f3_f2_with_group(self) -> None:
        intent = {
            "intention": "analyse_complete",
            "variables": ["CR10_INTRADOS_FORME", "CR90_INTRADOS_FORME"],
            "group_by": "Ref_Matrice",
        }
        plans = analysis_families.classify_analysis_families(intent)
        ids = [p.family_id for p in plans]
        assert FAMILY_UNIVARIATE in ids
        assert FAMILY_QUANTI_QUANTI in ids
        assert FAMILY_QUALI_QUANTI in ids

    def test_unknown_intention_empty(self) -> None:
        assert analysis_families.classify_analysis_families({"intention": "inconnu"}) == []


class TestSpecialistsEquivalence:
    """derived specialists_from_plans doit égaler le mapping legacy."""

    @pytest.mark.parametrize(
        "intention,extra",
        [
            ("portrait_statistique", {"variables": ["CR90_INTRADOS_FORME"]}),
            ("comparaison_groupes", {"variables": ["CR90_INTRADOS_FORME"], "group_by": "Ref_Matrice"}),
            ("diagnostic_causal", {"variables": ["CR90_INTRADOS_FORME"], "group_by": "Ref_Matrice"}),
            ("conformite", {"variables": ["CR90_INTRADOS_FORME"], "piece": "M2L1A1C"}),
            ("tendance", {"variables": ["VRILAGE"], "piece": "RD4L1A1C"}),
            ("anomalie", {"variables": ["CR90_INTRADOS_FORME"]}),
            (
                "analyse_complete",
                {
                    "variables": ["CR10_INTRADOS_FORME", "CR90_INTRADOS_FORME"],
                    "group_by": "Ref_Matrice",
                },
            ),
            (
                "analyse_complete",
                {"variables": ["CR90_INTRADOS_FORME"]},
            ),
        ],
    )
    def test_plans_match_legacy_specialists(self, intention: str, extra: dict) -> None:
        intent = {"intention": intention, **extra}
        legacy = _specialists_for_intention(intention, intent)
        plans = analysis_families.classify_analysis_families(intent)
        derived = analysis_families.specialists_from_plans(plans)
        assert derived == legacy, (intention, legacy, derived)

    def test_dispatch_returns_same_specialists_as_legacy(self) -> None:
        intent = {
            "intention": "portrait_statistique",
            "variables": ["CR90_INTRADOS_FORME"],
        }
        out = dispatch(intent)
        assert out["error"] is None
        legacy = _specialists_for_intention("portrait_statistique", intent)
        assert out["specialists"] == legacy
        assert out["analysis_families"]
        assert out["analysis_families"][0]["family_id"] == FAMILY_UNIVARIATE
        assert out["analysis_family_warnings"] == []

    def test_dispatch_no_warning_when_derived_equals_legacy(self) -> None:
        intent = {
            "intention": "comparaison_groupes",
            "variables": ["CR90_INTRADOS_FORME"],
            "group_by": "Ref_Matrice",
        }
        out = dispatch(intent)
        assert out["analysis_family_warnings"] == []
        assert all(not row.get("warnings") for row in out["analysis_families"])

    def test_dispatch_fallback_warning_on_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        intent = {
            "intention": "portrait_statistique",
            "variables": ["CR90_INTRADOS_FORME"],
        }
        legacy = _specialists_for_intention("portrait_statistique", intent)

        def _wrong(_plans: list) -> list[str]:
            return ["cp_cpk"]

        monkeypatch.setattr(analysis_families, "specialists_from_plans", _wrong)
        out = dispatch(intent)
        assert out["specialists"] == legacy
        assert len(out["analysis_family_warnings"]) == 1
        warn = out["analysis_family_warnings"][0]
        assert warn["intention"] == "portrait_statistique"
        assert warn["derived_specialists"] == ["cp_cpk"]
        assert warn["legacy_specialists"] == legacy
        assert warn["fallback_reason"] == "derived_specialists_mismatch_legacy"
        assert out["analysis_families"][0]["warnings"]
        assert warn in out["analysis_families"][0]["warnings"]

    def test_all_intention_keys_covered(self) -> None:
        for intention in INTENTION_SPECIALISTS:
            intent = {"intention": intention, "variables": ["X"]}
            if intention == "comparaison_groupes":
                intent["group_by"] = "Ref_Matrice"
            plans = analysis_families.classify_analysis_families(intent)
            assert plans, f"Aucun plan pour {intention}"
            derived = analysis_families.specialists_from_plans(plans)
            legacy = _specialists_for_intention(intention, intent)
            assert derived == legacy, intention
