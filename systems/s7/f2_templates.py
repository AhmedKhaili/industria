"""
P7-F2 — gabarits de texte certifiés (association, pas causalité).
"""

from __future__ import annotations

import re
from typing import Any

_PRUDENT_CAUSALITY_PATTERNS = [
    re.compile(r"ne\s+permet\s+pas\s+d'affirmer\s+une\s+causalit", re.I),
    re.compile(r"ne\s+démontre\s+pas\s+une\s+causalit", re.I),
    re.compile(r"ne\s+demontre\s+pas\s+une\s+causalit", re.I),
    re.compile(r"ne\s+prouve\s+pas", re.I),
    re.compile(r"ne\s+.{0,50}?pas\s+.{0,30}?causalit", re.I),
    re.compile(r"association.*pas\s+causalit", re.I),
    re.compile(r"pas\s+causalit[ée]\s+certaine", re.I),
    re.compile(r"ne\s+prouve\s+pas\s+une\s+relation\s+de\s+cause", re.I),
]

_ABUSIVE_CAUSALITY_PATTERNS = [
    re.compile(r"\b\w+\s+cause\s+(?:le|la|les|l'|un|une|du|des|d')\b", re.I),
    re.compile(r"\bcausent\b", re.I),
    re.compile(r"\bprouve\s+que\b", re.I),
    re.compile(r"\bdémontre\s+que\b", re.I),
    re.compile(
        r"\b(?:prouve|démontre|demontre)\s+une\s+causalit[ée]\s+directe\s+certaine\b",
        re.I,
    ),
    re.compile(r"\bresponsable\s+de\b", re.I),
    re.compile(r"\bà\s+l'origine\s+de\b", re.I),
    re.compile(r"\bimpact\s+direct\s+certain\b", re.I),
    re.compile(
        r"\brelation\s+de\s+cause\s+à\s+effet\s+démontrée\b",
        re.I,
    ),
    re.compile(
        r"\brelation\s+de\s+cause\s+a\s+effet\s+demontrée\b",
        re.I,
    ),
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def _sentence_is_prudent_on_causality(sentence: str) -> bool:
    return any(p.search(sentence) for p in _PRUDENT_CAUSALITY_PATTERNS)


def _sentence_has_abusive_causality(sentence: str) -> bool:
    s = sentence.strip()
    if not s:
        return False
    if _sentence_is_prudent_on_causality(s):
        return False
    return any(p.search(s) for p in _ABUSIVE_CAUSALITY_PATTERNS)


def text_contains_abusive_causality(text: str) -> bool:
    """True si une formulation causale positive abusive est détectée."""
    for sentence in _SENTENCE_SPLIT.split(text):
        if _sentence_has_abusive_causality(sentence):
            return True
    if "\n" in text:
        for line in text.splitlines():
            if _sentence_has_abusive_causality(line):
                return True
    return False


def assert_no_causality_abuse(text: str) -> None:
    if text_contains_abusive_causality(text):
        raise ValueError("Formulation interdite (causalité abusive positive)")


_SEVERITY_DISPLAY = {
    "critique": "Critique",
    "surveillance": "Surveillance",
    "favorable": "Favorable",
}


def severity_display(label: str | None) -> str:
    if not label:
        return "—"
    return _SEVERITY_DISPLAY.get(str(label).lower(), str(label).capitalize())


def conclusion_paragraphs(
    *,
    variable: str,
    worst_group: str,
    best_group: str,
    worst_pct: float | None,
    worst_cpk: float | None,
    group_by_label: str,
) -> list[str]:
    parts: list[str] = []
    if worst_pct is not None:
        parts.append(f"{worst_pct:.1f} % hors tolérance")
    if worst_cpk is not None:
        parts.append(f"Cpk {worst_cpk:.2f}")
    metrics = ", ".join(parts) if parts else "indicateurs défavorables"
    p1 = (
        f"La variable {variable} présente un comportement plus défavorable pour le "
        f"groupe {worst_group} ({metrics}) que pour {best_group}."
    )
    p2 = (
        f"L'écart observé entre {group_by_label} est associé à la variable analysée ; "
        "il ne permet pas à lui seul d'affirmer un lien direct certain entre ce facteur "
        "et la mesure."
    )
    for p in (p1, p2):
        assert_no_causality_abuse(p)
    return [p1, p2]


def business_context_paragraph(
    *,
    variable: str,
    group_by_label: str,
    analysis_level_label: str,
) -> str:
    text = (
        f"Analyse de {variable} ventilée par {group_by_label}, "
        f"au niveau {analysis_level_label}."
    )
    assert_no_causality_abuse(text)
    return text


def hors_tolerance_definition(analysis_level: str) -> str:
    if analysis_level == "aggregated_unit":
        return (
            "Une unité métier est hors tolérance lorsque sa valeur agrégée "
            "(ex. moyenne des mesures de l'unité) est en dehors de l'intervalle LTI–LTS."
        )
    return (
        "Une mesure est hors tolérance lorsque sa valeur est en dehors "
        "de l'intervalle LTI–LTS."
    )


def business_reading_paragraph_critique(
    *,
    group_value: str,
    pct: float | None,
    cpk: float | None,
    worse_direction: str,
) -> str:
    bits: list[str] = []
    if pct is not None:
        bits.append(f"le taux hors tolérance le plus élevé ({pct:.1f} %)")
    if cpk is not None:
        bits.append(f"un Cpk de {cpk:.2f}")
    detail = " et ".join(bits) if bits else "des indicateurs défavorables"
    direction_hint = ""
    if worse_direction == "upper":
        direction_hint = " vis-à-vis des limites hautes"
    elif worse_direction == "lower":
        direction_hint = " vis-à-vis des limites basses"
    text = (
        f"Le groupe {group_value} se distingue par {detail}{direction_hint}, "
        "ce qui correspond au classement le plus défavorable de cette analyse."
    )
    assert_no_causality_abuse(text)
    return text


def business_reading_paragraph_favorable(
    *,
    group_value: str,
    pct: float | None,
    n: int | None,
    analysis_level: str,
) -> str:
    unit = "unités" if analysis_level == "aggregated_unit" else "mesures"
    pct_txt = f"{pct:.1f} % hors tolérance" if pct is not None else "un profil plus favorable"
    n_txt = f" (n = {n} {unit})" if n is not None else ""
    text = (
        f"Le groupe {group_value} constitue la référence la plus favorable "
        f"({pct_txt}){n_txt}."
    )
    assert_no_causality_abuse(text)
    return text


def business_reading_paragraph_surveillance(group_value: str, rank: int | None) -> str:
    rank_txt = f" (rang {rank})" if rank is not None else ""
    text = (
        f"Le groupe {group_value} présente un profil intermédiaire{rank_txt} "
        "et mérite une surveillance renforcée."
    )
    assert_no_causality_abuse(text)
    return text


def final_verdict_paragraphs(
    *,
    hierarchy: list[str],
    worst_group: str,
    group_by_label: str,
) -> list[str]:
    chain = ", ".join(hierarchy) if hierarchy else worst_group
    p1 = f"Hiérarchie retenue : {chain}."
    p2 = (
        f"Orientation : concentrer l'investigation qualité sur {worst_group} "
        f"(contrôle renforcé, revue des séries concernées) sans imputer l'écart "
        f"au seul facteur {group_by_label}."
    )
    for p in (p1, p2):
        assert_no_causality_abuse(p)
    return [p1, p2]


def interpretation_limits_paragraphs(
    *,
    base_text: str,
    analysis_level: str,
    measure_annex_available: bool,
) -> list[str]:
    """base_text provient de S3 (non filtré) ; les ajouts sont validés anti-causalité."""
    paragraphs = [base_text.strip()] if base_text.strip() else []
    generated: list[str] = []
    if analysis_level == "measure":
        generated.append(
            "Analyse au niveau mesure capteur : chaque point correspond à une "
            "mesure individuelle ; la variabilité intra-unité métier n'est pas "
            "isolée dans ce rapport."
        )
        generated.append(
            "Les taux hors tolérance et Cpk affichés portent sur les mesures "
            "brutes, et non sur des unités métier agrégées."
        )
    elif analysis_level == "aggregated_unit":
        generated.append(
            "Analyse au niveau unité métier agrégée : les indicateurs portent "
            "sur des unités regroupées (ex. ordre de fabrication, lot)."
        )
        generated.append(
            "Le taux hors tolérance principal affiché concerne les unités "
            "métier agrégées."
        )
        if measure_annex_available:
            generated.append(
                "Un détail au niveau mesure brute peut être consulté en annexe "
                "lorsqu'il est disponible dans la sortie S3."
            )
    for p in generated:
        assert_no_causality_abuse(p)
    return paragraphs + generated


def reliability_limits_paragraph(analysis_level: str) -> str:
    if analysis_level == "measure":
        return (
            "Les intervalles de confiance traduisent l'incertitude liée à l'effectif "
            "au niveau mesure ; prudence si effectif faible ou avertissements associés."
        )
    return (
        "Les intervalles de confiance traduisent l'incertitude liée au nombre "
        "d'unités métier ; prudence si effectif faible ou avertissements associés."
    )
