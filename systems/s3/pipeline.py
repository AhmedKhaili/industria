"""
Orchestration S3 — df_propre + intent → métriques structurées.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from systems.s1.client_context import ClientContext
from systems.s3 import dispatcher, executor, group_ranking, judge
from systems.stats_format import enrich_specialist_results_display

if TYPE_CHECKING:
    pass


class S3Pipeline:
    def __init__(self, yaml_path: str) -> None:
        self.yaml_path = yaml_path
        self.ctx = ClientContext.load(yaml_path)

    def run(self, intent: dict, df_propre: pd.DataFrame) -> dict:
        trace: list[dict] = []
        try:
            if intent.get("clarification_needed"):
                return {
                    "specialist_results": [],
                    "group_ranking": {},
                    "metrics_summary": {},
                    "families_executed": [],
                    "analysis_family_warnings": [],
                    "warnings": [],
                    "pipeline_trace": trace,
                    "error": "Intent S1 incomplet — clarification requise avant S3",
                }

            disp = dispatcher.dispatch(intent)
            family_warnings = list(disp.get("analysis_family_warnings") or [])
            trace.append(
                {
                    "step": "dispatcher",
                    "ok": disp.get("error") is None,
                    "families": disp.get("analysis_families") or [],
                    "warnings": family_warnings,
                }
            )
            if disp.get("error"):
                return self._empty_error(disp["error"], trace)

            families_executed = list(disp.get("analysis_families") or [])
            pipeline_warnings: list[str] = []

            exec_res = executor.run_all(
                df_propre, intent, self.ctx, disp["specialists"]
            )
            trace.append({"step": "executor", "ok": exec_res.get("error") is None})
            if exec_res.get("error"):
                return self._empty_error(exec_res["error"], trace)

            judged = judge.validate_results(exec_res["specialist_results"])
            trace.append({"step": "judge", "ok": judged.get("error") is None})
            if judged.get("error"):
                return self._empty_error(judged["error"], trace)

            results = enrich_specialist_results_display(
                list(judged["specialist_results"])
            )
            metrics_summary = judge.build_metrics_summary(results)
            ranking = group_ranking.compute_worst_group(
                df_propre, intent, self.ctx, results
            )
            if ranking:
                metrics_summary["group_ranking"] = ranking
            if families_executed:
                metrics_summary["families_executed"] = families_executed
            if family_warnings:
                metrics_summary["analysis_family_warnings"] = family_warnings
                for item in family_warnings:
                    pipeline_warnings.append(
                        "P6 dispatcher fallback legacy "
                        f"({item.get('intention')}): {item.get('fallback_reason')}"
                    )

            return {
                "specialist_results": results,
                "group_ranking": ranking,
                "metrics_summary": metrics_summary,
                "families_executed": families_executed,
                "analysis_family_warnings": family_warnings,
                "warnings": pipeline_warnings + list(judged.get("warnings", [])),
                "pipeline_trace": trace,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return self._empty_error(str(exc), trace)

    @staticmethod
    def _empty_error(message: str, trace: list[dict]) -> dict:
        return {
            "specialist_results": [],
            "group_ranking": {},
            "metrics_summary": {},
            "families_executed": [],
            "analysis_family_warnings": [],
            "warnings": [],
            "pipeline_trace": trace,
            "error": message,
        }
