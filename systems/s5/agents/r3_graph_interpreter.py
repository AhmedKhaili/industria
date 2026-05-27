"""
R3 — Interprétation des graphiques (descriptions texte uniquement).
Regroupe les descriptions par lot ; repli item par item si le lot échoue.
"""

from __future__ import annotations

import re

from systems.s5 import llm_client, prep

_BATCH_MAX = 4


def run(descriptions: list[str]) -> dict:
    try:
        interpretations: list[dict] = []
        idx = 0
        while idx < len(descriptions):
            batch = descriptions[idx : idx + _BATCH_MAX]
            interpretations.extend(_interpret_batch(batch, idx))
            idx += len(batch)

        return {"error": None, "graph_interpretations": interpretations}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "graph_interpretations": []}


def _interpret_batch(batch: list[str], offset: int) -> list[dict]:
    if len(batch) == 1:
        return [_interpret_one(batch[0], offset)]

    numbered = "\n".join(f"{i + 1}. {d[:500]}" for i, d in enumerate(batch))
    prompt = (
        "Descriptions certifiées de graphiques/tableaux industriels.\n"
        "Pour chaque numéro, rédige UNE phrase courte en français "
        "(ne invente aucun chiffre absent de la description).\n\n"
        f"{numbered}\n\n"
        "Réponds avec exactement une ligne par numéro, format strict :\n"
        "1. <phrase>\n2. <phrase>\n"
    )
    texte = llm_client.chat(prompt, num_predict=min(900, 90 * len(batch)))
    if texte:
        parsed = _parse_numbered_response(texte, len(batch))
        if parsed and all(parsed):
            return [
                {
                    "specialist": "graphique",
                    "texte": parsed[i],
                    "statut": "Accept",
                }
                for i in range(len(batch))
            ]
        if parsed and any(parsed):
            out: list[dict] = []
            for i, desc in enumerate(batch):
                if parsed[i]:
                    out.append(
                        {
                            "specialist": "graphique",
                            "texte": parsed[i],
                            "statut": "Accept",
                        }
                    )
                else:
                    out.append(_interpret_one(desc, offset + i))
            return out

    return [_interpret_one(desc, offset + i) for i, desc in enumerate(batch)]


def _interpret_one(desc: str, _offset: int) -> dict:
    prompt = prep.format_graph_prompt(desc, _offset)
    texte = llm_client.chat(prompt, num_predict=200)
    if texte:
        return {"specialist": "graphique", "texte": texte.strip(), "statut": "Accept"}
    return _fallback_item(desc)


def _fallback_item(desc: str) -> dict:
    return {
        "specialist": "graphique",
        "texte": f"Graphique : {desc[:300]}",
        "statut": "fallback",
    }


def _parse_numbered_response(text: str, expected: int) -> list[str | None]:
    """Extrait les phrases numérotées 1..expected (None si manquant)."""
    by_num: dict[int, str] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(?:N\.\s*)?(\d+)[.)]\s*(.+)$", line, re.IGNORECASE)
        if m:
            by_num[int(m.group(1))] = m.group(2).strip()
            continue
        m = re.match(r"^[-*•]\s*(?:N\.\s*)?(\d+)[.)]\s*(.+)$", line, re.IGNORECASE)
        if m:
            by_num[int(m.group(1))] = m.group(2).strip()

    if len(by_num) < expected:
        flat = " ".join(text.splitlines())
        for m in re.finditer(
            r"(?:^|\s)(?:N\.\s*)?(\d+)[.)]\s*(.+?)(?=\s+(?:N\.\s*)?\d+[.)]|\s*$)",
            flat,
            re.IGNORECASE,
        ):
            n = int(m.group(1))
            if 1 <= n <= expected and n not in by_num:
                by_num[n] = m.group(2).strip()

    return [by_num.get(i) for i in range(1, expected + 1)]
