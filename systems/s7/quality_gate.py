"""
QualityGate S7 — bloque un PDF client si contradiction ou jargon interne.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader

from systems.s7 import prep

if TYPE_CHECKING:
    from systems.s7.document import ReportDocument

_CLIENT_JARGON = [
    re.compile(r"\bdescriptive\b", re.I),
    re.compile(r"\bnormality\b", re.I),
    re.compile(r"\bdistribution_fit\b", re.I),
    re.compile(r"\bAIC\s*=", re.I),
    re.compile(r"\bBIC\s*=", re.I),
    re.compile(r"\bLLM\b", re.I),
    re.compile(r"\bfallback\b", re.I),
    re.compile(r"écart\s+LLM", re.I),
    re.compile(r"données\s+certifiées", re.I),
    re.compile(r"intent\s+S\d", re.I),
    re.compile(r"YAML\s+client", re.I),
    re.compile(r"\bRef_Matrice\b"),
    re.compile(r"warning\s+système", re.I),
    re.compile(r"fidélité\s+interprétation", re.I),
    re.compile(r"\banova_kruskal\b", re.I),
    re.compile(r"\bcp_cpk\b"),
    re.compile(r"\bdunn_posthoc\b"),
]

_CONTRA_EN9100 = [
    re.compile(r"conforme aux normes", re.I),
    re.compile(r"sup[eé]rieur.*seuil.*1[,.]33", re.I),
    re.compile(r"atteint le seuil EN9100", re.I),
    re.compile(r"performance globale conforme", re.I),
]


def _apply_f2_narratif_gate(
    document: "ReportDocument | None",
    cfg: dict,
    blocking: list[str],
    warnings: list[str],
) -> None:
    if not document:
        return
    render_mode = str((document.meta or {}).get("render_mode", "")).lower()
    if render_mode != "narratif_metier":
        return
    ck = document.find("conclusion_key")
    if not ck or not (ck.data.get("paragraphs") or ck.data.get("facts")):
        msg = "conclusion_key absente ou vide en mode narratif_metier F2"
        if prep.is_client_mode(cfg):
            blocking.append(msg)
        else:
            warnings.append(msg)
    limits = document.find("interpretation_limits")
    if not limits or not limits.data.get("paragraphs"):
        msg = "interpretation_limits absente en mode narratif_metier F2"
        if prep.is_client_mode(cfg):
            blocking.append(msg)
        else:
            warnings.append(msg)
    if prep.text_contains_forbidden_causality(document.all_text()):
        blocking.append(
            "Vocabulaire causal interdit dans le rapport narratif F2 "
            "(cause / prouve / démontre une causalité)"
        )


def run(
    question_originale: str,
    intent: dict,
    s3_output: dict,
    s5_output: dict,
    s6_output: dict,
    document: "ReportDocument",
    profile: str,
    cfg: dict,
) -> dict[str, Any]:
    """Retourne blocking[], warnings[], publishable bool."""
    blocking: list[str] = []
    warnings: list[str] = []
    if not prep.is_client_mode(cfg):
        _apply_f2_narratif_gate(document, cfg, blocking, warnings)
        return {
            "blocking": blocking,
            "warnings": warnings,
            "publishable": len(blocking) == 0,
        }

    specialist_results = list(s3_output.get("specialist_results") or [])
    min_c = prep.min_cpk(specialist_results)
    synthese = prep.strip_client_synthesis(
        str(s5_output.get("synthese") or ""), min_c
    )

    if prep.synthesis_contradicts_cpk(synthese, min_c):
        blocking.append(
            "Synthèse contradictoire : affirmation de conformité EN9100 alors que Cpk < 1,33"
        )

    exec_block = document.find("executive") if document else None
    exec_text = ""
    if exec_block:
        exec_text = " ".join(
            str(exec_block.data.get(k, "") or "")
            for k in ("synthese_s5", "synthese_s6", "cpk_synthesis")
        )
        if prep.synthesis_contradicts_cpk(exec_text, min_c):
            blocking.append(
                "Résumé exécutif contradictoire avec les Cpk certifiés (< 1,33)"
            )

    body = document.all_text() if document else ""
    full = f"{synthese}\n{exec_text}\n{body}".strip()
    for pat in _CLIENT_JARGON:
        if pat.search(full):
            blocking.append(f"Jargon interne interdit dans le rapport client : {pat.pattern}")

    if re.search(r"\bIntention\b", full, re.I) and re.search(
        r"comparaison_groupes", full, re.I
    ):
        blocking.append("Champ Intention (jargon interne) visible dans le PDF client")

    if re.search(r"\broot\s+cause\b", full, re.I):
        blocking.append("Expression « root cause » interdite dans le PDF client")

    if re.search(r",\s*\)", full):
        blocking.append("Parenthèse orpheline détectée dans le texte client")

    from systems.s5.prep import _sentence_is_broken

    for sentence in re.split(r"(?<=[.!?…])\s+", full):
        if _sentence_is_broken(sentence.strip()):
            blocking.append("Phrase cassée détectée dans le rapport client")
            break

    if re.search(r"Kruskal-Wallis\s*\(\s+Enfin", full, re.I):
        blocking.append("Fragment « Kruskal-Wallis ( Enfin » dans le rapport client")

    exec_block = document.find("executive") if document else None
    if exec_block:
        exec_txt = " ".join(
            str(exec_block.data.get(k, "") or "")
            for k in ("synthese_s5", "synthese_s6", "cpk_synthesis")
        )
        if exec_txt.count("(") != exec_txt.count(")"):
            blocking.append("Parenthèses non équilibrées dans le résumé exécutif")

    if min_c is not None and min_c < 1.33:
        p12 = [
            r
            for r in s6_output.get("recommandations") or []
            if str(r.get("priorite", "")).upper() in ("P1", "P2")
        ]
        if not p12:
            blocking.append("Cpk < 1,33 sans recommandation P1/P2")

    charts = document.find("charts") if document else None
    n_charts = len((charts.data.get("items") if charts else []) or [])
    # Placeholder / analyse sans graphique : ne pas bloquer si aucun spécialiste exécuté
    if n_charts < 1 and specialist_results and not blocking:
        blocking.append("Aucun graphique dans le rapport client")

    pdf_empty = not body.strip()
    if pdf_empty:
        blocking.append("Document PDF vide")

    if not question_originale.strip():
        blocking.append("Question originale absente")

    rapport_type = str((document.meta or {}).get("rapport_type", "simple")).lower()
    if rapport_type == "complet":
        max_pages = prep.max_pages_complet(cfg)
        try:
            from io import BytesIO

            from systems.s7.renderer_stub import render_pdf

            pdf_bytes = render_pdf(document)
            n_pages = len(PdfReader(BytesIO(pdf_bytes)).pages)
            if n_pages > max_pages:
                blocking.append(
                    f"Rapport complet dépasse {max_pages} pages ({n_pages} pages)"
                )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Contrôle nombre de pages ignoré : {exc}")

    _apply_f2_narratif_gate(document, cfg, blocking, warnings)

    publishable = len(blocking) == 0
    return {"blocking": blocking, "warnings": warnings, "publishable": publishable}
