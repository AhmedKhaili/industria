"""
Tests P7-F2a — builders JSON group_descriptive → 9 blocs (sans PDF).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from systems.s1.client_context import ClientContext
from systems.s7 import f2_report_blocks, f2_templates
from systems.s7.f2_report_blocks import collect_all_numeric_values

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "group_descriptive_f2_sample.json"
)
GENERIC_YAML = str(
    Path(__file__).resolve().parents[3] / "configs/test_generic/client_config.yaml"
)

_EXPECTED_BLOCKS = frozenset(
    {
        "conclusion_key",
        "business_context",
        "key_indicators",
        "group_comparison_table",
        "how_to_read_cpk",
        "statistical_reliability",
        "business_reading",
        "final_verdict",
        "interpretation_limits",
    }
)

_CAUSALITY_RE = re.compile(
    r"\b(cause|causent|prouve|démontre une causalité|demontre une causalite)\b",
    re.I,
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ctx() -> ClientContext:
    return ClientContext.load(GENERIC_YAML)


@pytest.fixture(scope="module")
def bundle(fixture_payload: dict, ctx: ClientContext):
    s3 = {"group_descriptive": fixture_payload["group_descriptive"]}
    intent = fixture_payload["intent"]
    return f2_report_blocks.build_f2_bundle(s3, intent, ctx)


def test_bundle_not_skipped(bundle: f2_report_blocks.F2ReportBundle) -> None:
    assert bundle.skipped_reason is None
    assert bundle.source_level == "aggregated_unit"


def test_nine_blocks_present(bundle: f2_report_blocks.F2ReportBundle) -> None:
    assert set(bundle.blocks.keys()) == _EXPECTED_BLOCKS


def test_select_aggregated_over_measure(fixture_payload: dict) -> None:
    blocks = fixture_payload["group_descriptive"]
    primary, annex, sel = f2_report_blocks.select_group_descriptive_blocks(
        blocks, "DIA_01"
    )
    assert primary is not None
    assert primary["level"] == "aggregated_unit"
    assert annex is not None
    assert annex["level"] == "measure"
    assert sel["measure_annex_available"] is True


def test_skipped_when_no_group_descriptive() -> None:
    out = f2_report_blocks.build_f2_bundle({}, {"intention": "comparaison_groupes"})
    assert out.skipped_reason == "no_group_descriptive"
    assert out.blocks == {}


def test_conclusion_facts_match_s3(bundle: f2_report_blocks.F2ReportBundle) -> None:
    s3_rows = bundle.blocks["conclusion_key"]
    facts = s3_rows["facts"]
    assert facts[0]["value"] == 100.0
    assert facts[0]["group"] == "M2"
    worst_row = next(
        r
        for r in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["group_descriptive"][
            0
        ]["rows"]
        if r["rank"] == 1
    )
    assert facts[0]["value"] == worst_row["out_of_tolerance_rate"]


def test_comparison_table_order(bundle: f2_report_blocks.F2ReportBundle) -> None:
    table = bundle.blocks["group_comparison_table"]
    ranks = [r["rank"] for r in table["rows"]]
    assert ranks == [1, 2]
    assert table["rows"][0]["group_value"] == "M2"
    assert table["rows"][0]["out_of_tolerance_rate"] == 100.0


def test_key_indicators_cpk_from_s3(bundle: f2_report_blocks.F2ReportBundle) -> None:
    rows = bundle.blocks["key_indicators"]["rows"]
    cpk_row = next(r for r in rows if "Cpk" in r["label"])
    assert cpk_row["raw"] == 0.75


def test_how_to_read_cpk_uses_yaml_thresholds(
    bundle: f2_report_blocks.F2ReportBundle,
) -> None:
    block = bundle.blocks["how_to_read_cpk"]
    assert block["cpk_present_in_analysis"] is True
    assert block["case_note"] and "0.75" in block["case_note"]
    sources = {t["source"] for t in block["thresholds"]}
    assert "recommandations.seuils_cpk.p1_sous" in sources
    text = " ".join(block["paragraphs"])
    assert "norme officielle" not in text.lower()
    assert "configuration client" in text.lower()


def test_statistical_reliability_ci95_copy(bundle: f2_report_blocks.F2ReportBundle) -> None:
    rel = bundle.blocks["statistical_reliability"]
    m2 = next(g for g in rel["groups"] if g["group_value"] == "M2")
    assert m2["ci95_mean"]["low"] == 19.99
    assert rel["measure_annex_note"]


def test_provenance_numeric_subset(
    bundle: f2_report_blocks.F2ReportBundle, fixture_payload: dict
) -> None:
    primary = fixture_payload["group_descriptive"][0]
    allowed = collect_all_numeric_values(primary)

    def gather_display_nums(obj: object, path: str = "") -> list[float]:
        nums: list[float] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("raw", "raw_n", "value") and isinstance(v, (int, float)):
                    nums.append(float(v))
                elif k.endswith("_display"):
                    continue
                else:
                    nums.extend(gather_display_nums(v, f"{path}.{k}"))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                nums.extend(gather_display_nums(item, f"{path}[{i}]"))
        return nums

    for block_name, block in bundle.blocks.items():
        for num in gather_display_nums(block):
            assert num in allowed or num in {0.0, 1.0, 1.33, 1.67}, (
                f"{block_name}: {num} not in S3"
            )


def test_no_causality_in_generated_paragraphs(
    bundle: f2_report_blocks.F2ReportBundle,
) -> None:
    texts: list[str] = []

    def walk(obj: object) -> None:
        if isinstance(obj, str):
            if len(obj) > 40 and "paragraph" in str(type(obj)):
                pass
            texts.append(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("paragraphs", "case_note", "footnote", "limits_paragraph"):
                    if isinstance(v, str):
                        texts.append(v)
                    elif isinstance(v, list):
                        texts.extend(str(x) for x in v)
                elif k == "heading":
                    texts.append(str(v))
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for name in (
        "conclusion_key",
        "business_reading",
        "final_verdict",
    ):
        walk(bundle.blocks[name])

    for block in bundle.blocks["how_to_read_cpk"]["paragraphs"]:
        texts.append(block)

    for text in texts:
        if "interprétation_limits" in text:
            continue
        assert not _CAUSALITY_RE.search(text), text


def test_diagnostic_causal_intention_eligible() -> None:
    assert f2_report_blocks.is_f2_intention_eligible(
        {"intention": "diagnostic_causal", "group_by": "Machine"}
    )


def test_analyse_complete_requires_group_by() -> None:
    assert not f2_report_blocks.is_f2_intention_eligible(
        {"intention": "analyse_complete"}
    )
    assert f2_report_blocks.is_f2_intention_eligible(
        {"intention": "analyse_complete", "group_by": "Machine"}
    )


def test_templates_forbid_causality_words() -> None:
    with pytest.raises(ValueError):
        f2_templates.assert_no_causality_abuse("La matrice cause le défaut.")


def test_abusive_causality_prudent_limits_text_passes() -> None:
    ok = (
        "Cette analyse ne permet pas d'affirmer une causalité directe certaine "
        "entre le facteur et la mesure."
    )
    assert not f2_templates.text_contains_abusive_causality(ok)


def test_abusive_causality_positive_phrase_blocked() -> None:
    assert f2_templates.text_contains_abusive_causality("La matrice cause le défaut.")
