"""
Orchestration S6 — métriques S3 + interprétations S5 → recommandations actionnelles.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from systems.s1.client_context import ClientContext
from systems.s5 import llm_client
from systems.s6.agents import a1_dispatcher, a2_redacteur, a3_rag, a4_synthesizer
from systems.s6.rag_port import StubRagPort

if TYPE_CHECKING:
    from systems.s6.rag_port import RagPort


def _trace_step(trace: list[dict], step: str, result: dict, t0: float, **extra: object) -> None:
    trace.append(
        {
            "step": step,
            "ok": result.get("error") is None,
            "duration_s": round(time.perf_counter() - t0, 2),
            **llm_client.pop_step_stats(),
            **extra,
        }
    )


class S6Pipeline:
    def __init__(self, yaml_path: str) -> None:
        self.yaml_path = yaml_path
        self.ctx = ClientContext.load(yaml_path)

    def run(
        self,
        intent: dict,
        s3_output: dict,
        s5_output: dict,
        profile: str = "technicien",
        rag_port: "RagPort | None" = None,
    ) -> dict:
        trace: list[dict] = []
        try:
            if intent.get("clarification_needed"):
                return self._empty_error("Intent incomplet — S6 impossible", trace)

            specialist_results = list(s3_output.get("specialist_results") or [])
            s5_warnings = list(s5_output.get("warnings") or [])

            llm_client.reset_step_stats()
            t0 = time.perf_counter()
            ranking = s3_output.get("group_ranking") or {}
            if not ranking:
                ms = s3_output.get("metrics_summary") or {}
                ranking = ms.get("group_ranking") if isinstance(ms, dict) else {}
            a1 = a1_dispatcher.run(
                specialist_results,
                intent,
                self.ctx,
                profile,
                group_ranking=ranking,
            )
            _trace_step(trace, "a1", a1, t0, n_items=len(a1.get("items", [])))
            if a1.get("error"):
                return self._empty_error(a1["error"], trace)

            items = list(a1["items"])

            t0 = time.perf_counter()
            a3 = a3_rag.run(items, self.ctx, rag_port or StubRagPort())
            _trace_step(trace, "a3", a3, t0, rag_used=a3.get("rag_used", False))
            if a3.get("error"):
                return self._empty_error(a3["error"], trace)
            items = list(a3["items"])
            warnings = s5_warnings + list(a3.get("warnings", []))

            t0 = time.perf_counter()
            a2 = a2_redacteur.run(items)
            _trace_step(
                trace,
                "a2",
                a2,
                t0,
                llm_items=sum(1 for i in items if i.get("use_llm")),
            )
            if a2.get("error"):
                warnings.append(f"A2 : {a2['error']}")
            items = list(a2["items"])

            t0 = time.perf_counter()
            a4 = a4_synthesizer.run(items, self.ctx, profile, intent)
            _trace_step(trace, "a4", a4, t0, llm_used=a4.get("llm_used", False))
            if a4.get("error"):
                return self._empty_error(a4["error"], trace)
            warnings.extend(a4.get("warnings", []))

            recommandations = [
                {
                    "priorite": it["priorite"],
                    "action": it.get("action", ""),
                    "responsable": it["responsable"],
                    "delai": it["delai"],
                    "justification": it.get("justification", ""),
                }
                for it in items
            ]

            return {
                "recommandations": recommandations,
                "synthese_action": a4.get("synthese_action", ""),
                "rag_used": bool(a3.get("rag_used")),
                "warnings": warnings,
                "pipeline_trace": trace,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return self._empty_error(str(exc), trace)

    @staticmethod
    def _empty_error(message: str, trace: list[dict]) -> dict:
        return {
            "recommandations": [],
            "synthese_action": "",
            "rag_used": False,
            "warnings": [],
            "pipeline_trace": trace,
            "error": message,
        }
