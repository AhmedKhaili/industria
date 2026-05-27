"""
A4 — Validateur contrat_rapport YAML (warnings uniquement).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from systems.s7 import prep

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext
    from systems.s7.document import ReportDocument


def run(
    document: "ReportDocument",
    context: "ClientContext",
    profile: str,
    s3_output: dict,
    s6_output: dict,
) -> dict:
    warnings: list[str] = []
    try:
        contrat = context.get_contrat_rapport()
        types = document.block_types()

        if "verdict" not in types[:3]:
            warnings.append("Contrat : verdict GO/NO-GO absent des premières sections")

        specialist_results = list(s3_output.get("specialist_results") or [])
        has_cpk_agent = any(
            str(r.get("agent", "")).lower() == "cp_cpk" and r.get("status") == "success"
            for r in specialist_results
        )
        metrics_block = document.find("metrics_table")
        has_metric_rows = bool(
            metrics_block
            and (
                metrics_block.data.get("tables")
                or metrics_block.data.get("rows")
            )
        )
        if has_cpk_agent and not has_metric_rows:
            warnings.append("Contrat : métriques Cpk absentes du tableau")

        charts = document.find("charts")
        n_charts = len((charts.data.get("items") if charts else []) or [])
        if n_charts == 0:
            warnings.append("Contrat : aucun graphique intégré au rapport")

        recos = document.find("recommendations")
        n_reco = len((recos.data.get("items") if recos else []) or [])
        if n_reco < 1:
            warnings.append("Contrat : aucune recommandation actionnable")

        min_c = prep.min_cpk(specialist_results)
        if min_c is not None and min_c < 1.33:
            p12 = [
                r
                for r in s6_output.get("recommandations") or []
                if str(r.get("priorite", "")).upper() in ("P1", "P2")
            ]
            if not p12:
                warnings.append(
                    "Contrat : Cpk < 1.33 sans recommandation P1/P2"
                )

        if profile == "operateur":
            text = document.all_text().lower()
            for term in ("p-value", "p value", "cpk"):
                if re.search(rf"\b{re.escape(term)}\b", text):
                    warnings.append(f"Contrat opérateur : terme interdit présent ({term})")

        for item in (charts.data.get("items") if charts else []) or []:
            if item.get("error"):
                warnings.append(f"Graphique en erreur : {item.get('error')}")

        _ = contrat  # réservé extensions futures (doit_contenir / ne_doit_jamais)
        return {"warnings": warnings, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"warnings": warnings, "error": str(exc)}
