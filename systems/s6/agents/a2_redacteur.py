"""
A2 — Rédaction recommandations P1/P2 (LLM 14b batch) ; templates P3/P4.
"""

from __future__ import annotations

import re

from systems.s5 import llm_client


def run(items: list[dict]) -> dict:
    try:
        llm_items = [i for i in items if i.get("use_llm")]
        template_items = [i for i in items if not i.get("use_llm")]

        for item in template_items:
            item["action"] = _template_action(item)

        if llm_items:
            _batch_redact(llm_items)

        for item in items:
            if not item.get("action"):
                item["action"] = _template_action(item)

        return {"error": None, "items": items}
    except Exception as exc:  # noqa: BLE001
        for item in items:
            if not item.get("action"):
                item["action"] = _template_action(item)
        return {"error": str(exc), "items": items}


def _template_action(item: dict) -> str:
    rag = ""
    if item.get("rag_excerpt"):
        rag = f" Référence procédure : {item['rag_excerpt'][:200]}."
    return (
        f"[{item['priorite']}] {item['action_type'].replace('_', ' ')} — "
        f"{item['cause_label']}. {item['justification']} "
        f"Responsable : {item['responsable']}. Délai : {item['delai']}.{rag}"
    )


def _batch_redact(items: list[dict]) -> None:
    numbered = "\n".join(
        f"{i + 1}. [{it['priorite']}] {it['action_type']} — {it['cause_label']}\n"
        f"   Faits : {it['justification']}\n"
        f"   Chiffres : {it.get('chiffres', {})}\n"
        f"   Délai imposé : {it['delai']}\n"
        f"   Responsable : {it['responsable']}"
        + (f"\n   Procédure : {it['rag_excerpt'][:300]}" if it.get("rag_excerpt") else "")
        for i, it in enumerate(items)
    )
    prompt = (
        "Tu rédiges des recommandations d'action pour l'industrie (qualité EN9100).\n"
        "Ne modifie aucun chiffre. Une ligne par numéro, format strict :\n"
        "1. <action impérative courte>\n\n"
        f"{numbered}\n\n"
        "Actions :"
    )
    texte = llm_client.chat(prompt, num_predict=min(900, 120 * len(items)))
    if texte:
        parsed = _parse_numbered(texte, len(items))
        if parsed and all(parsed):
            for i, it in enumerate(items):
                it["action"] = parsed[i]
            return

    for it in items:
        it["action"] = _template_action(it)


def _parse_numbered(text: str, expected: int) -> list[str | None]:
    by_num: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(?:N\.\s*)?(\d+)[.)]\s*(.+)$", line, re.IGNORECASE)
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
            if n not in by_num:
                by_num[n] = m.group(2).strip()
    return [by_num.get(i) for i in range(1, expected + 1)]
