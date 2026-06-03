"""
Interprétations LLM par graphique portrait — faits Python injectés, zéro calcul LLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.s5 import llm_client, prep

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def run(
    charts: list[dict],
    specialist_results: list[dict],
    intent: dict,
    context: "ClientContext",
) -> dict:
    try:
        interpretations: list[dict] = []
        for chart in charts:
            if not isinstance(chart, dict):
                continue
            ctype = str(chart.get("type", "")).lower()
            variable = str(chart.get("variable", ""))
            chart_id = str(chart.get("id", f"{ctype}_{variable}"))
            facts = prep.portrait_chart_facts_block(
                ctype, variable, specialist_results, intent, context
            )
            prompt = prep.portrait_chart_prompt(ctype, variable, facts, intent)
            texte = llm_client.chat(prompt, num_predict=300)
            if not texte or not prep.is_meaningful_chart_interpretation(texte, facts):
                texte = prep.portrait_chart_fallback(ctype, variable, facts)
            texte = prep.finalize_chart_interpretation(
                prep.strip_client_metric_jargon(texte)
            )
            if not prep.is_meaningful_text(texte):
                texte = prep.portrait_chart_fallback(ctype, variable, facts)
            interpretations.append(
                {
                    "specialist": f"chart_{ctype}",
                    "chart_id": chart_id,
                    "texte": texte.strip(),
                    "statut": "Accept",
                }
            )
        return {"error": None, "interpretations": interpretations}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "interpretations": []}
