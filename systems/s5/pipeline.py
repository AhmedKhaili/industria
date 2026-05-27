"""
Orchestration S5 — S3 + S4 → interprétations vérifiées + synthèse.
"""

from __future__ import annotations

import time

from systems.s1.client_context import ClientContext
from systems.s5 import llm_client, prep
from systems.s5.agents import (
    r1_interpreter,
    r2_verifier,
    r3_graph_interpreter,
    r4_coherence,
    r5_corrector,
    r6_synthesizer,
    r7_checker,
)


def _trace_step(trace: list[dict], step: str, result: dict, t0: float, **extra: object) -> None:
    entry: dict = {
        "step": step,
        "ok": result.get("error") is None,
        "duration_s": round(time.perf_counter() - t0, 2),
        **llm_client.pop_step_stats(),
        **extra,
    }
    trace.append(entry)


class S5Pipeline:
    def __init__(self, yaml_path: str) -> None:
        self.yaml_path = yaml_path
        self.ctx = ClientContext.load(yaml_path)

    def run(
        self,
        intent: dict,
        s3_output: dict,
        s4_output: dict,
        profile: str = "technicien",
    ) -> dict:
        trace: list[dict] = []
        try:
            if intent.get("clarification_needed"):
                return self._empty_error("Intent incomplet — S5 impossible", trace)

            specialist_results = list(s3_output.get("specialist_results") or [])
            descriptions = prep.descriptions_list(s4_output)

            llm_client.reset_step_stats()
            t0 = time.perf_counter()
            r1 = r1_interpreter.run(specialist_results)
            _trace_step(
                trace,
                "r1",
                r1,
                t0,
                llm_fallbacks=sum(
                    1 for it in r1.get("interpretations", []) if it.get("statut") == "fallback"
                ),
            )
            if r1.get("error"):
                return self._empty_error(r1["error"], trace)

            t0 = time.perf_counter()
            r2 = r2_verifier.run(r1["interpretations"])
            _trace_step(trace, "r2", r2, t0)

            if r2.get("error"):
                return self._empty_error(r2["error"], trace)

            interpretations = list(r2["interpretations"])
            fidelite_score = float(r2.get("fidelite_score", 0.0))
            reject_warnings = [
                f"Interprétation automatique indisponible pour {it.get('specialist', 'spécialiste')} "
                "— données brutes affichées"
                for it in interpretations
                if it.get("statut") == "reject"
            ]

            if descriptions:
                t0 = time.perf_counter()
                r3 = r3_graph_interpreter.run(descriptions)
                graph_items = list(r3.get("graph_interpretations", []))
                _trace_step(
                    trace,
                    "r3",
                    r3,
                    t0,
                    descriptions=len(descriptions),
                    llm_fallbacks=sum(1 for it in graph_items if it.get("statut") == "fallback"),
                )
                if r3.get("error"):
                    return self._empty_error(r3["error"], trace)
                interpretations.extend(graph_items)

            t0 = time.perf_counter()
            r4 = r4_coherence.run(interpretations, specialist_results)
            _trace_step(trace, "r4", r4, t0)

            warnings = reject_warnings + list(r4.get("warnings", []))
            interpretations = list(r4["interpretations"])

            t0 = time.perf_counter()
            r5 = r5_corrector.run(interpretations, warnings)
            _trace_step(trace, "r5", r5, t0)
            interpretations = list(r5["interpretations"])

            t0 = time.perf_counter()
            r6 = r6_synthesizer.run(interpretations, self.ctx, profile, intent)
            _trace_step(trace, "r6", r6, t0, llm_used=bool(r6.get("llm_used", False)))
            if r6.get("error"):
                return self._empty_error(r6["error"], trace)

            t0 = time.perf_counter()
            r7 = r7_checker.run(r6["synthese"], self.ctx, profile)
            _trace_step(trace, "r7", r7, t0)
            warnings.extend(r7.get("warnings", []))

            fidelite_score = prep.compute_fidelity_score(interpretations)

            return {
                "interpretations": [
                    {k: v for k, v in it.items() if k != "source_result"}
                    for it in interpretations
                ],
                "synthese": r7.get("synthese", r6["synthese"]),
                "fidelite_score": fidelite_score,
                "warnings": warnings,
                "pipeline_trace": trace,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return self._empty_error(str(exc), trace)

    @staticmethod
    def _empty_error(message: str, trace: list[dict]) -> dict:
        return {
            "interpretations": [],
            "synthese": "",
            "fidelite_score": 0.0,
            "warnings": [],
            "pipeline_trace": trace,
            "error": message,
        }
