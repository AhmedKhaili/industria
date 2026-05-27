"""
R5 — Correction ciblée des sections Review (LLM 14b).
"""

from __future__ import annotations

from systems.s5 import llm_client, prep


def run(interpretations: list[dict], warnings: list[str]) -> dict:
    try:
        corrected: list[dict] = []
        for item in interpretations:
            entry = dict(item)
            if entry.get("statut") not in ("Review", "Reject"):
                corrected.append(entry)
                continue

            prompt = (
                "Corrige ce texte d'analyse industrielle. "
                "Conserve les chiffres certifiés, améliore la clarté.\n\n"
                f"Texte original :\n{entry.get('texte', '')}\n\n"
                f"Avertissements système : {'; '.join(warnings[:3])}\n\n"
                "Texte corrigé :"
            )
            texte = llm_client.chat(prompt, temperature=0.1)
            if texte:
                entry["texte"] = texte
                entry["statut"] = "Accept"
            corrected.append(entry)

        return {"error": None, "interpretations": corrected}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "interpretations": interpretations}
