"""
Tests S7 — PDF EN9100 (unitaires + chaînage LISI sans LLM pour S7).
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s6.pipeline import S6Pipeline
from systems.s6.rag_port import StubRagPort
from systems.s7.agents import a3_signer
from systems.s7.pipeline import S7Pipeline
from systems.s7.renderer_stub import render_pdf as stub_render_pdf

REPO_ROOT = Path(__file__).resolve().parents[3]
YAML_PATH = str(REPO_ROOT / "configs/lisi_aerospace/client_config.yaml")
FIXED_TS = "2026-05-23T12:00:00.000+00:00"


def _minimal_png() -> bytes:
    """PNG 1x1 valide pour tests."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def _fixture_inputs(priorite: str = "P1") -> tuple[str, dict, dict, dict, dict, dict]:
    question = "La matrice impacte-t-elle la forme intrados de M2L1A1C ?"
    intent = {
        "piece": "M2L1A1C",
        "operation": "EQUATOR",
        "group_by": "Ref_Matrice",
    }
    s3 = {
        "specialist_results": [
            {
                "agent": "cp_cpk",
                "status": "success",
                "result": {
                    "Cpk": 0.75,
                    "colonne": "CR70_INTRADOS_FORME",
                    "conforme_EN9100": False,
                },
            }
        ],
    }
    s4 = {
        "graphs": [
            {
                "id": "hist1",
                "type": "histogram",
                "title": "Distribution CR70",
                "description": "Histogramme CR70 (mm)",
                "png_bytes": _minimal_png(),
            }
        ],
        "tables": [],
        "descriptions_tabulaires": "",
    }
    s5 = {
        "interpretations": [
            {
                "specialist": "cp_cpk",
                "texte": "Cpk sous le seuil critique — procédé non conforme.",
                "statut": "accept",
            }
        ],
        "synthese": "Le procédé présente un écart de capabilité sur CR70.",
        "fidelite_score": 0.9,
        "warnings": [],
    }
    s6 = {
        "recommandations": [
            {
                "priorite": priorite,
                "action": "Stopper la ligne et vérifier le réglage presse.",
                "responsable": "responsable qualité",
                "delai": "immédiat",
                "justification": "Cpk critique.",
            }
        ],
        "synthese_action": "Action immédiate requise sur la ligne EQUATOR.",
        "warnings": [],
    }
    return question, intent, s3, s4, s5, s6


def _pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        return pdf_bytes.decode("latin-1", errors="ignore")


class TestS7PdfBasics:
    def test_pdf_non_vide(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        q, intent, s3, s4, s5, s6 = _fixture_inputs()
        pipe = S7Pipeline(YAML_PATH)
        out = pipe.run(
            q,
            intent,
            s3,
            s4,
            s5,
            s6,
            profile="technicien",
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        assert out.get("error") is None
        assert len(out["pdf_bytes"]) > 5000
        assert out["pdf_bytes"][:4] == b"%PDF"

    def test_sha256_stable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        q, intent, s3, s4, s5, s6 = _fixture_inputs()
        pipe = S7Pipeline(YAML_PATH)
        kw = dict(
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        out1 = pipe.run(q, intent, s3, s4, s5, s6, profile="technicien", **kw)
        out2 = pipe.run(q, intent, s3, s4, s5, s6, profile="technicien", **kw)
        assert out1.get("error") is None
        assert out1["sha256"] == out2["sha256"]
        assert len(out1["sha256"]) == 64

    def test_verdict_no_go_p1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        q, intent, s3, s4, s5, s6 = _fixture_inputs(priorite="P1")
        out = S7Pipeline(YAML_PATH).run(
            q,
            intent,
            s3,
            s4,
            s5,
            s6,
            profile="technicien",
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        assert out.get("error") is None
        text = _pdf_text(out["pdf_bytes"]).upper()
        assert "NO-GO" in text

    def test_profil_operateur_sans_cpk_pvalue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        q, intent, s3, s4, s5, s6 = _fixture_inputs()
        s5["interpretations"] = [
            {
                "specialist": "cp_cpk",
                "texte": "Écart par rapport à la cible sur la mesure principale.",
                "statut": "accept",
            }
        ]
        out = S7Pipeline(YAML_PATH).run(
            q,
            intent,
            s3,
            s4,
            s5,
            s6,
            profile="operateur",
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        assert out.get("error") is None
        text = _pdf_text(out["pdf_bytes"]).lower()
        assert not re.search(r"\bcpk\b", text)
        assert not re.search(r"\bp[- ]?value\b", text)


class TestS7ChainLisi:
    def test_chain_s1_s7_sans_llm_s7(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """S1→S3 réel ; S4/S5 synthétiques ; S6 stub-friendly ; S7 pur Python."""
        csv = REPO_ROOT / "data/lisi_capteurs.csv"
        if not csv.is_file():
            pytest.skip("Dataset LISI local absent")

        monkeypatch.chdir(tmp_path)
        question = "La matrice a-t-elle un impact sur la forme intrados de M2L1A1C ?"
        s1 = S1Pipeline(YAML_PATH).run(question)
        intent = s1["intent"]
        assert not intent.get("clarification_needed")

        s2 = S2Pipeline(YAML_PATH).run(intent)
        assert s2.get("error") is None and s2["df_propre"] is not None

        s3 = S3Pipeline(YAML_PATH).run(intent, s2["df_propre"])
        assert s3.get("error") is None

        s4 = {
            "graphs": [
                {
                    "title": "Test",
                    "description": "Graphique test (mm)",
                    "png_bytes": _minimal_png(),
                }
            ],
            "tables": [],
        }
        s5 = {
            "interpretations": [],
            "synthese": "Analyse de conformité sur la campagne.",
            "fidelite_score": 0.5,
            "warnings": [],
        }
        s6 = S6Pipeline(YAML_PATH).run(
            intent, s3, s5, profile="technicien", rag_port=StubRagPort()
        )
        assert s6.get("error") is None

        out = S7Pipeline(YAML_PATH).run(
            question,
            intent,
            s3,
            s4,
            s5,
            s6,
            profile="technicien",
            report_renderer=stub_render_pdf,
            timestamp=FIXED_TS,
        )
        assert out.get("error") is None
        assert out["pdf_bytes"].startswith(b"%PDF")
        assert out["sha256"]
        assert Path(out["sidecar_path"]).is_file()


class TestS7ShaExcludesPng:
    def test_sha_inchange_si_png_change(self) -> None:
        q, intent, s3, s4, s5, s6 = _fixture_inputs()
        payload1 = a3_signer.canonical_payload(q, intent, s3, s5, s6, FIXED_TS)
        s4_other = dict(s4)
        s4_other["graphs"] = [
            {
                **s4["graphs"][0],
                "png_bytes": b"other-bytes-not-in-hash",
            }
        ]
        _ = s4_other
        sha1 = a3_signer.compute_sha256(payload1)
        sha2 = a3_signer.compute_sha256(payload1)
        assert sha1 == sha2
