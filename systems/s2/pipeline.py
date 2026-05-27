"""
Orchestration S2 — intent.json → df_propre.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from systems.s1.client_context import ClientContext
from systems.s2 import cleaner, loader, partitioner, pivotter, validator
from systems.s2.loader import MAX_VAGUE_ROWS, is_vague_intent

if TYPE_CHECKING:
    pass


class S2Pipeline:
    def __init__(self, yaml_path: str) -> None:
        self.yaml_path = yaml_path
        self.ctx = ClientContext.load(yaml_path)

    def run(self, intent: dict) -> dict:
        trace: list[dict] = []
        try:
            if intent.get("clarification_needed"):
                return {
                    "df_propre": None,
                    "df_anomalies": pd.DataFrame(),
                    "cleaning_stats": {},
                    "clarification_needed": True,
                    "clarification_manque": intent.get("clarification_manque", []),
                    "pipeline_trace": trace,
                    "error": "Intent S1 incomplet — clarification requise avant S2",
                }

            part = partitioner.ensure_partitions(self.yaml_path, self.ctx)
            trace.append({"step": "partitioner", "ok": part.get("error") is None})
            if part.get("error"):
                return self._error(part["error"], trace)

            if is_vague_intent(intent):
                count_res = partitioner.count_rows_vague_scope(self.yaml_path, self.ctx)
                trace.append({"step": "vague_row_count", "ok": count_res.get("error") is None})
                if count_res.get("error"):
                    return self._error(count_res["error"], trace)
                if count_res.get("row_count", 0) > MAX_VAGUE_ROWS:
                    return {
                        "df_propre": None,
                        "df_anomalies": pd.DataFrame(),
                        "cleaning_stats": {},
                        "clarification_needed": True,
                        "clarification_manque": ["piece", "operation"],
                        "row_count": count_res["row_count"],
                        "pipeline_trace": trace,
                        "error": None,
                    }

            load_res = loader.load_partition(self.yaml_path, self.ctx, intent)
            trace.append({"step": "loader", "ok": load_res.get("error") is None})
            if load_res.get("error"):
                return self._error(load_res["error"], trace)

            df = load_res["df"]
            if df is None or df.empty:
                return self._error("Partition vide après chargement", trace)

            time_res = loader.apply_temporal_filter(df, self.ctx, intent)
            trace.append({"step": "temporal_filter", "ok": time_res.get("error") is None})
            if time_res.get("error"):
                return self._error(time_res["error"], trace)
            df = time_res["df"]

            clean_res = cleaner.run(df, self.ctx)
            trace.append({"step": "cleaner", "ok": clean_res.get("error") is None})
            if clean_res.get("error"):
                return self._error(clean_res["error"], trace)

            pivot_res = pivotter.run(clean_res["df"], self.ctx, intent)
            trace.append({"step": "pivotter", "ok": pivot_res.get("error") is None})
            if pivot_res.get("error"):
                return self._error(pivot_res["error"], trace)

            val_res = validator.run(pivot_res["df"], self.ctx, intent)
            trace.append({"step": "validator", "ok": val_res.get("valid") is True})
            if not val_res.get("valid"):
                return self._error(val_res.get("error", "Validation échouée"), trace)

            cleaning_stats = dict(clean_res["cleaning_stats"])
            if val_res.get("colonnes_vides_ignorees"):
                cleaning_stats["colonnes_vides_ignorees"] = val_res["colonnes_vides_ignorees"]

            return {
                "df_propre": pivot_res["df"],
                "df_anomalies": clean_res["df_anomalies"],
                "cleaning_stats": cleaning_stats,
                "clarification_needed": False,
                "clarification_manque": [],
                "validation": val_res,
                "pipeline_trace": trace,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), trace)

    @staticmethod
    def _error(message: str, trace: list[dict]) -> dict:
        return {
            "df_propre": None,
            "df_anomalies": pd.DataFrame(),
            "cleaning_stats": {},
            "clarification_needed": False,
            "clarification_manque": [],
            "pipeline_trace": trace,
            "error": message,
        }
