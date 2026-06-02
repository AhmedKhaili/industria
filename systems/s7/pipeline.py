"""
Orchestration S7 — S3–S6 → PDF signé EN9100.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from systems.s1.client_context import ClientContext
from systems.s7 import prep
from systems.s7 import quality_gate
from systems.s7.agents import a1_assembler, a2_renderer, a3_signer, a4_validator
from systems.s7.document import ReportDocument
from systems.s7.report_port import render_pdf as default_render_pdf

if TYPE_CHECKING:
    pass

RenderFn = Callable[[ReportDocument], bytes]


def _trace_step(trace: list[dict], step: str, result: dict, t0: float, **extra: object) -> None:
    trace.append(
        {
            "step": step,
            "ok": result.get("error") is None,
            "duration_s": round(time.perf_counter() - t0, 2),
            **extra,
        }
    )


class S7Pipeline:
    def __init__(self, yaml_path: str) -> None:
        self.yaml_path = yaml_path
        self.ctx = ClientContext.load(yaml_path)

    def run(
        self,
        question_originale: str,
        intent: dict,
        s3_output: dict,
        s4_output: dict,
        s5_output: dict,
        s6_output: dict,
        profile: str = "technicien",
        *,
        report_renderer: RenderFn | None = None,
        timestamp: str | None = None,
        df_propre: object = None,
    ) -> dict:
        trace: list[dict] = []
        warnings: list[str] = []
        try:
            if intent.get("clarification_needed"):
                return self._empty_error("Intent incomplet — S7 impossible", trace)

            cfg = prep.rapport_pdf_config(self.ctx)
            ts = timestamp or prep.utc_timestamp()
            render_fn = report_renderer or default_render_pdf

            t0 = time.perf_counter()
            a1 = a1_assembler.run(
                question_originale,
                intent,
                s3_output,
                s4_output,
                s5_output,
                s6_output,
                self.ctx,
                profile,
                timestamp=ts,
                df_propre=df_propre,
            )
            _trace_step(trace, "a1", a1, t0)
            if a1.get("error") or a1.get("document") is None:
                return self._empty_error(a1.get("error") or "Assemblage échoué", trace)

            document: ReportDocument = a1["document"]

            t0 = time.perf_counter()
            qg = quality_gate.run(
                question_originale,
                intent,
                s3_output,
                s5_output,
                s6_output,
                document,
                profile,
                cfg,
            )
            _trace_step(
                trace,
                "quality_gate",
                {"error": None if qg.get("publishable") else "blocked"},
                t0,
                blocking=len(qg.get("blocking") or []),
            )
            if qg.get("blocking"):
                msg = "QualityGate : " + "; ".join(qg["blocking"])
                warnings.extend(qg.get("warnings", []))
                return self._empty_error(msg, trace, warnings)

            t0 = time.perf_counter()
            a4 = a4_validator.run(document, self.ctx, profile, s3_output, s6_output)
            _trace_step(trace, "a4", a4, t0, n_warnings=len(a4.get("warnings", [])))
            warnings.extend(a4.get("warnings", []))
            if a4.get("error"):
                warnings.append(f"A4 : {a4['error']}")

            t0 = time.perf_counter()
            reports_dir = Path(str(cfg.get("sauvegarder_dans", "reports/")))
            if not reports_dir.is_absolute():
                reports_dir = Path.cwd() / reports_dir
            a3 = a3_signer.run(
                document,
                question_originale,
                intent,
                s3_output,
                s5_output,
                s6_output,
                timestamp=ts,
                reports_dir=reports_dir,
                slug=prep.slug_piece_op(intent),
            )
            _trace_step(trace, "a3", a3, t0)
            if a3.get("error"):
                return self._empty_error(a3["error"], trace, warnings)

            t0 = time.perf_counter()
            a2 = a2_renderer.run(document, render_fn)
            _trace_step(trace, "a2", a2, t0, pdf_size=len(a2.get("pdf_bytes") or b""))
            if a2.get("error"):
                return self._empty_error(a2["error"], trace, warnings)

            meta = dict(document.meta)
            meta["sha256"] = a3["sha256"]

            return {
                "pdf_bytes": a2["pdf_bytes"],
                "sha256": a3["sha256"],
                "metadata": meta,
                "sidecar_path": a3.get("sidecar_path", ""),
                "warnings": warnings,
                "pipeline_trace": trace,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return self._empty_error(str(exc), trace, warnings)

    @staticmethod
    def _empty_error(
        message: str,
        trace: list[dict],
        warnings: list[str] | None = None,
    ) -> dict:
        return {
            "pdf_bytes": b"",
            "sha256": "",
            "metadata": {},
            "sidecar_path": "",
            "warnings": warnings or [],
            "pipeline_trace": trace,
            "error": message,
        }
