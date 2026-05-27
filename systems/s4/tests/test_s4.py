"""
Tests S4 — graphiques et descriptions tabulaires (LISI, S1→S4).
"""

from __future__ import annotations

import pytest

from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s4.pipeline import S4Pipeline

YAML_PATH = "configs/lisi_aerospace/client_config.yaml"
MIN_PNG_BYTES = 500


@pytest.fixture(scope="module")
def s4_pipeline() -> S4Pipeline:
    return S4Pipeline(YAML_PATH)


def _run_through_s3(question: str) -> tuple[dict, object, dict]:
    s1 = S1Pipeline(YAML_PATH)
    intent = s1.run(question)["intent"]
    assert intent is not None
    s2 = S2Pipeline(YAML_PATH)
    s2_out = s2.run(intent)
    assert s2_out.get("error") is None
    df = s2_out["df_propre"]
    s3 = S3Pipeline(YAML_PATH)
    s3_out = s3.run(intent, df)
    assert s3_out.get("error") is None
    return intent, df, s3_out


class TestS4PipelineLisi:
    def test_comparaison_boxplot(self, s4_pipeline: S4Pipeline) -> None:
        intent, df, s3_out = _run_through_s3(
            "Compare la forme intrados de M2L1A1C entre les matrices"
        )
        result = s4_pipeline.run(intent, df, s3_out)
        assert result.get("error") is None
        box = next(
            (c for c in result["charts"] if c.get("type") == "boxplot"),
            None,
        )
        assert box is not None
        assert box.get("png_bytes")
        assert len(box["png_bytes"]) > MIN_PNG_BYTES

    def test_conformite_histogram(self, s4_pipeline: S4Pipeline) -> None:
        intent, df, s3_out = _run_through_s3(
            "Les pieces M2L1A1C sont-elles conformes au filage ?"
        )
        result = s4_pipeline.run(intent, df, s3_out)
        assert result.get("error") is None
        hist = next(
            (c for c in result["charts"] if c.get("type") == "histogram"),
            None,
        )
        assert hist is not None
        assert len(hist["png_bytes"]) > MIN_PNG_BYTES

    def test_tendance_timeseries(self, s4_pipeline: S4Pipeline) -> None:
        intent, df, s3_out = _run_through_s3("Tendance du vrillage de RD4L1A1C")
        result = s4_pipeline.run(intent, df, s3_out)
        assert result.get("error") is None
        ts = next(
            (c for c in result["charts"] if c.get("type") == "timeseries"),
            None,
        )
        assert ts is not None
        assert len(ts["png_bytes"]) > MIN_PNG_BYTES

    def test_description_tabulaire_non_vide(self, s4_pipeline: S4Pipeline) -> None:
        intent, df, s3_out = _run_through_s3(
            "Les pieces M2L1A1C sont-elles conformes au filage ?"
        )
        result = s4_pipeline.run(intent, df, s3_out)
        assert result.get("error") is None
        assert result.get("descriptions_tabulaires", "").strip()
        assert len(result.get("tables", [])) >= 1

    def test_png_bytes_non_vide(self, s4_pipeline: S4Pipeline) -> None:
        intent, df, s3_out = _run_through_s3(
            "Les pieces M2L1A1C sont-elles conformes au filage ?"
        )
        result = s4_pipeline.run(intent, df, s3_out)
        assert result.get("error") is None
        for chart in result["charts"]:
            assert chart.get("png_bytes")
            assert len(chart["png_bytes"]) > MIN_PNG_BYTES
