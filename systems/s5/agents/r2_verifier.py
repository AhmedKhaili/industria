"""
R2 — Vérification fidélité des chiffres (Python pur).
"""

from __future__ import annotations

import re

from systems.s5 import llm_client, prep


def run(
    interpretations: list[dict],
    specialist_results: list[dict] | None = None,
    intent: dict | None = None,
) -> dict:
    try:
        verified: list[dict] = []
        for item in interpretations:
            entry = dict(item)
            texte = entry.get("texte", "")
            result = entry.get("source_result") or {}
            refs = prep.reference_numbers_for_result(result)

            if entry.get("statut") == "fallback":
                entry["statut"] = "Accept"
                verified.append(entry)
                continue

            numbers = prep.extract_numbers_from_text(texte)
            worst = "Accept"
            reject_motif: dict | None = None
            for num in numbers:
                status, _rel = prep.verify_number_against_refs(num, refs)
                if status == "Reject":
                    worst = "Reject"
                    reject_motif = _motif_reject(num, refs)
                    break
                if status == "Review" and worst != "Reject":
                    worst = "Review"

            if worst == "Reject":
                entry["texte"] = prep.python_fallback_interpretation(
                    result, specialist_results, intent
                )
                entry["statut"] = "reject"
                if reject_motif:
                    entry["motif_reject"] = reject_motif
            elif worst == "Review":
                corrected = _regenerate_with_environ(entry, result)
                entry["texte"] = corrected
                entry["statut"] = "Review"
            else:
                entry["statut"] = "Accept"

            entry.pop("source_result", None)
            verified.append(entry)

        score = prep.compute_fidelity_score(verified)
        return {"error": None, "interpretations": verified, "fidelite_score": score}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "interpretations": [], "fidelite_score": 0.0}


def _motif_reject(trouve: float, refs: dict[str, float]) -> dict:
    """Chiffre LLM vs référence Python la plus proche."""
    if not refs:
        return {"trouve": trouve, "attendu": None, "reference": None}
    best_key: str | None = None
    best_ref: float | None = None
    best_rel: float | None = None
    for key, ref in refs.items():
        if ref == 0:
            rel = abs(trouve - ref)
        else:
            rel = abs(trouve - ref) / abs(ref)
        if best_rel is None or rel < best_rel:
            best_rel = rel
            best_key = key
            best_ref = ref
    return {"trouve": trouve, "attendu": best_ref, "reference": best_key}


def _regenerate_with_environ(entry: dict, result: dict) -> str:
    """Une régénération R1 avec consigne « environ »."""
    prompt = (
        prep.format_specialist_prompt(result)
        + "\n\nLe texte précédent avait des approximations. "
        "Reformule en préfixant les valeurs incertaines par « environ »."
    )
    texte = llm_client.chat(prompt, temperature=0.1)
    if texte:
        return texte
    base = entry.get("texte", "")
    return re.sub(
        r"(\d+(?:[.,]\d+)?)",
        r"environ \1",
        base,
        count=3,
    )
