"""
R1 — Interprétation par spécialiste (LLM 14b + fallback Python).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.s5 import llm_client, prep

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def run(
    specialist_results: list[dict],
    intent: dict | None = None,
    context: "ClientContext | None" = None,
) -> dict:
    try:
        intent = intent or {}
        force_python = context is not None and prep.zero_llm_synthesis(context)
        interpretations: list[dict] = []
        for result in specialist_results:
            agent = prep.canonical_agent(result.get("agent"))
            if result.get("status") == "skipped":
                texte = prep.python_fallback_interpretation(
                    result, specialist_results, intent
                )
                interpretations.append(
                    {
                        "specialist": agent,
                        "texte": texte,
                        "statut": "fallback",
                        "source_result": result,
                    }
                )
                continue

            if force_python:
                texte = prep.python_fallback_interpretation(
                    result, specialist_results, intent
                )
                interpretations.append(
                    {
                        "specialist": agent,
                        "texte": texte,
                        "statut": "fallback",
                        "source_result": result,
                    }
                )
                continue

            prompt = prep.format_specialist_prompt(result)
            texte = llm_client.chat(prompt)
            if not texte:
                texte = prep.python_fallback_interpretation(
                    result, specialist_results, intent
                )
                statut = "fallback"
            else:
                statut = "pending"

            interpretations.append(
                {
                    "specialist": agent,
                    "texte": texte,
                    "statut": statut,
                    "source_result": result,
                }
            )

        return {"error": None, "interpretations": interpretations}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "interpretations": []}
