"""
Orchestration S4 — métriques S3 + df_propre → graphiques + tableaux.
"""

from __future__ import annotations

import pandas as pd

from systems.s1.client_context import ClientContext
from systems.s4 import chart_builder, dispatcher, table_builder


class S4Pipeline:
    def __init__(self, yaml_path: str) -> None:
        self.yaml_path = yaml_path
        self.ctx = ClientContext.load(yaml_path)

    def run(
        self,
        intent: dict,
        df_propre: pd.DataFrame,
        s3_output: dict,
    ) -> dict:
        trace: list[dict] = []
        try:
            if intent.get("clarification_needed"):
                return self._empty_error("Intent S1 incomplet — clarification requise avant S4", trace)

            specialist_results = list(s3_output.get("specialist_results") or [])
            metrics_summary = dict(s3_output.get("metrics_summary") or {})

            disp = dispatcher.dispatch(intent)
            trace.append({"step": "dispatcher", "ok": disp.get("error") is None})
            if disp.get("error"):
                return self._empty_error(disp["error"], trace)

            charts_res = chart_builder.build_charts(
                df_propre, intent, self.ctx, disp["chart_types"]
            )
            trace.append({"step": "chart_builder", "ok": charts_res.get("error") is None})
            if charts_res.get("error"):
                return self._empty_error(charts_res["error"], trace)

            tables_res = table_builder.build_tables(
                intent, self.ctx, specialist_results, metrics_summary
            )
            trace.append({"step": "table_builder", "ok": tables_res.get("error") is None})
            if tables_res.get("error"):
                return self._empty_error(tables_res["error"], trace)

            warnings: list[str] = list(s3_output.get("warnings") or [])
            graphs = list(charts_res.get("charts") or [])
            for chart in graphs:
                if chart.get("error"):
                    warnings.append(f"Graphique {chart.get('id')}: {chart['error']}")

            return {
                "graphs": graphs,
                "charts": graphs,
                "tables": tables_res["tables"],
                "descriptions_tabulaires": tables_res["descriptions_tabulaires"],
                "warnings": warnings,
                "pipeline_trace": trace,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return self._empty_error(str(exc), trace)

    @staticmethod
    def _empty_error(message: str, trace: list[dict]) -> dict:
        return {
            "graphs": [],
            "charts": [],
            "tables": [],
            "descriptions_tabulaires": "",
            "warnings": [],
            "pipeline_trace": trace,
            "error": message,
        }
