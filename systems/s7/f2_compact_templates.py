"""
P7-F2 compact — gabarits texte certifiés (association, pas causalité).
"""

from __future__ import annotations

from typing import Any

from systems.s7 import f2_templates
from systems.s7.f2_templates import assert_no_causality_abuse, severity_display


_EXCLUSION_LABELS = {
    "effectif_insuffisant": "Effectif insuffisant",
    "valeur_manquante": "Valeur manquante",
    "pattern_yaml_non_respecte": "Hors pattern YAML",
    "groupe_parasite": "Groupe parasite (denylist)",
    "warning_s3_autre": "Avertissement S3",
}


def exclusion_reason_label(reason: str) -> str:
    return _EXCLUSION_LABELS.get(reason, reason)


def business_synthesis_lines(
    *,
    title: str,
    variable_tag: str,
    variable_label: str,
    tolerances: dict[str, Any] | None,
    factor_label: str,
    analysis_level_label: str,
    analysis_level: str = "measure",
) -> dict[str, Any]:
    lines: list[str] = [title]
    if analysis_level == "measure":
        lines.append(
            "Analyse au niveau mesure capteur — chaque point correspond "
            "à une mesure individuelle."
        )
    var_line = f"Variable analysée : {variable_tag}"
    if variable_label and variable_label != variable_tag:
        var_line += f" ({variable_label})"
    if tolerances:
        nominal = tolerances.get("nominal")
        if nominal is not None:
            var_line += f"   Nominal : {nominal:.3f}".replace(".", ",")
        interval = tolerances.get("interval_display")
        if interval:
            var_line += f"   Tolérance : {interval}"
    lines.append(var_line)
    lines.append(
        f"Facteur de comparaison : {factor_label}   Niveau d'analyse : {analysis_level_label}"
    )
    for line in lines:
        assert_no_causality_abuse(line)
    return {
        "title": title,
        "lines": lines,
        "variable_tag": variable_tag,
        "variable_label": variable_label,
        "factor_label": factor_label,
        "analysis_level_label": analysis_level_label,
        "tolerances": tolerances,
    }


def _row_metrics_phrase(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    parts: list[str] = []
    mean = row.get("mean")
    if mean is not None:
        try:
            parts.append(f"moyenne {_fmt_num(mean)}")
        except (TypeError, ValueError):
            pass
    pct = row.get("out_of_tolerance_rate")
    if pct is not None:
        try:
            parts.append(f"{float(pct):.1f} % hors tolérance".replace(".", ","))
        except (TypeError, ValueError):
            pass
    cpk = row.get("cpk")
    if cpk is not None:
        try:
            parts.append(f"Cpk {float(cpk):.2f}".replace(".", ","))
        except (TypeError, ValueError):
            pass
    ci = row.get("ci95_out_of_tolerance_rate")
    if isinstance(ci, dict):
        label = ci.get("label")
        if label:
            parts.append(f"IC95 % HT : {label}")
        elif ci.get("low") is not None and ci.get("high") is not None:
            parts.append(
                f"IC95 % HT : [{ci['low']} % ; {ci['high']} %]"
            )
    return ", ".join(parts)


def _fmt_num(value: Any, decimals: int = 3) -> str:
    return f"{float(value):.{decimals}f}".replace(".", ",")


def _referent_singular(unit: str, group_value: str) -> str:
    u = unit.strip().lower()
    if u == "matrice":
        return f"La matrice {group_value}"
    return f"Le {u} {group_value}"


def _referent_plural_label(unit: str) -> str:
    u = unit.strip().lower()
    if u == "matrice":
        return "Les matrices"
    return f"Les {u}s"


def conclusion_key_paragraphs(
    *,
    variable_label: str,
    worst_group: str,
    best_group: str | None,
    worst_pct: float | None,
    worst_cpk: float | None,
    factor_label: str,
    degenerate: bool,
    has_distinct_favorable: bool,
    favorable_strength: str = "none",
    favorable_row: dict[str, Any] | None = None,
) -> list[str]:
    if degenerate:
        text = (
            "Données insuffisantes pour comparer les groupes de façon fiable "
            "après application des filtres métier."
        )
        assert_no_causality_abuse(text)
        return [text]

    parts: list[str] = []
    if worst_pct is not None:
        parts.append(f"{worst_pct:.1f} % hors tolérance")
    if worst_cpk is not None:
        parts.append(f"Cpk {worst_cpk:.2f}")
    metrics = ", ".join(parts) if parts else "indicateurs défavorables"
    p1 = (
        f"Le groupe {worst_group} présente le profil le plus défavorable "
        f"({metrics}) parmi les groupes fiables retenus."
    )
    fav_metrics = _row_metrics_phrase(favorable_row)
    if has_distinct_favorable and best_group and best_group != worst_group:
        if favorable_strength == "robust":
            suffix = f" ({fav_metrics})" if fav_metrics else ""
            p2 = (
                f"À titre de contraste, le groupe {best_group} constitue la "
                f"référence favorable la plus robuste{suffix}."
            )
        else:
            suffix = f" ({fav_metrics})" if fav_metrics else ""
            p2 = (
                f"Référence favorable à confirmer : le groupe {best_group}"
                f"{suffix}."
            )
    else:
        p2 = (
            "Aucune référence favorable robuste n'est identifiable "
            "sur les données retenues."
        )
    p3 = (
        f"L'écart observé selon {factor_label} est associé à {variable_label} ; "
        "il ne permet pas à lui seul d'affirmer une causalité directe certaine."
    )
    out = [p1, p2, p3]
    for p in out:
        assert_no_causality_abuse(p)
    return out


def verdict_bullets_compact(
    *,
    verdict: Any,
    worst_group: str | None,
    worst_pct: float | None,
    worst_cpk: float | None,
) -> list[str]:
    bullets: list[str] = []
    if worst_group:
        detail: list[str] = []
        if worst_pct is not None:
            detail.append(f"{worst_pct:.1f} % HT")
        if worst_cpk is not None:
            detail.append(f"Cpk {worst_cpk:.2f}")
        suffix = f" ({', '.join(detail)})" if detail else ""
        bullets.append(f"Groupe prioritaire : {worst_group}{suffix}.")
    bullets.append(f"Verdict : {verdict.label}.")
    if getattr(verdict, "tone", None) == "point_attention":
        bullets.append("Point d'attention — suivi renforcé recommandé.")
    elif verdict.rationale:
        bullets.append(verdict.rationale.capitalize() + ".")
    for b in bullets:
        assert_no_causality_abuse(b)
    return bullets[:3]


def statistical_test_paragraphs(
    test: dict[str, Any] | None,
    *,
    factor_label: str,
    variable_label: str,
) -> list[str]:
    if not test:
        text = "Test de comparaison global non disponible pour cette analyse."
        assert_no_causality_abuse(text)
        return [text]

    method = str(test.get("methode_choisie") or test.get("test_name") or "Test global")
    p_display = str(test.get("p_value_display") or test.get("p_value") or "")
    sig = test.get("significatif")

    if sig:
        text = (
            f"{method} : différence statistique associée entre les groupes de "
            f"{factor_label} pour {variable_label} ({p_display}). "
            "Il s'agit d'une association statistique, pas d'une preuve de causalité."
        )
    else:
        text = (
            f"{method} : aucune différence statistique significative détectée "
            f"entre les groupes de {factor_label} ({p_display})."
        )
    assert_no_causality_abuse(text)
    return [text]


def business_reading_sections_compact(
    rows_reliable: list[dict[str, Any]],
    *,
    worst_row: dict[str, Any] | None,
    favorable_row: dict[str, Any] | None,
    favorable_strength: str,
    worse_direction: str,
    analysis_level: str,
    factor_label: str,
) -> list[dict[str, Any]]:
    """Au plus 3 sections : prioritaire / intermédiaires / favorable (ou absence)."""
    if not rows_reliable or not worst_row:
        return []

    ordered = sorted(rows_reliable, key=lambda r: int(r.get("rank") or 999))
    sections: list[dict[str, Any]] = []
    unit = factor_label.strip() or "Groupe"
    gv_w = str(worst_row.get("group_value", ""))
    metrics_w = _row_metrics_phrase(worst_row)
    p_w = (
        f"{_referent_singular(unit, gv_w)} concentre le profil le plus défavorable"
        f" ({metrics_w})." if metrics_w else
        f2_templates.business_reading_paragraph_critique(
            group_value=gv_w,
            pct=worst_row.get("out_of_tolerance_rate"),
            cpk=worst_row.get("cpk"),
            worse_direction=worse_direction,
        )
    )
    sections.append(
        {
            "tier": "prioritaire",
            "heading": f"{unit.capitalize()} prioritaire — {gv_w}",
            "paragraphs": [p_w],
        }
    )
    assert_no_causality_abuse(p_w)

    fav_gv = str((favorable_row or {}).get("group_value", ""))
    middle = [
        r
        for r in ordered
        if str(r.get("group_value", "")) not in (gv_w, fav_gv)
    ]
    if middle:
        snippets: list[str] = []
        for row in middle[:3]:
            gv = str(row.get("group_value", ""))
            m = _row_metrics_phrase(row)
            snippets.append(f"{gv} ({m})" if m else gv)
        joined = "; ".join(snippets)
        p_mid = (
            f"{_referent_plural_label(unit)} {joined} présentent un profil intermédiaire "
            "et méritent un suivi renforcé."
        )
        sections.append(
            {
                "tier": "intermediaire",
                "heading": f"{unit.capitalize()}s intermédiaires à surveiller",
                "paragraphs": [p_mid],
            }
        )
        assert_no_causality_abuse(p_mid)

    if favorable_strength == "robust" and favorable_row:
        gv_b = str(favorable_row.get("group_value", ""))
        metrics_b = _row_metrics_phrase(favorable_row)
        p_fav = (
            f"{_referent_singular(unit, gv_b)} constitue la référence favorable la plus "
            f"robuste ({metrics_b})."
            if metrics_b
            else f2_templates.business_reading_paragraph_favorable(
                group_value=gv_b,
                pct=favorable_row.get("out_of_tolerance_rate"),
                n=favorable_row.get("n"),
                analysis_level=analysis_level,
            )
        )
        sections.append(
            {
                "tier": "favorable",
                "heading": f"Référence favorable — {gv_b}",
                "paragraphs": [p_fav],
            }
        )
        assert_no_causality_abuse(p_fav)
    elif favorable_strength == "limited" and favorable_row:
        gv_b = str(favorable_row.get("group_value", ""))
        metrics_b = _row_metrics_phrase(favorable_row)
        p_lim = (
            f"Référence favorable à confirmer : {_referent_singular(unit, gv_b).lower()}"
            f" ({metrics_b})."
            if metrics_b
            else f"Référence favorable à confirmer : {_referent_singular(unit, gv_b).lower()}."
        )
        sections.append(
            {
                "tier": "favorable_limite",
                "heading": f"Référence favorable à confirmer — {gv_b}",
                "paragraphs": [p_lim],
            }
        )
        assert_no_causality_abuse(p_lim)
    else:
        p_none = (
            "Aucune référence favorable robuste n'est identifiable "
            "sur les données retenues."
        )
        sections.append(
            {
                "tier": "favorable_absent",
                "heading": "Référence favorable",
                "paragraphs": [p_none],
            }
        )
        assert_no_causality_abuse(p_none)

    return sections[:3]


def final_verdict_paragraphs_compact(
    *,
    hierarchy: list[str],
    worst_group: str,
    factor_label: str,
    verdict_label: str,
) -> list[str]:
    chain = ", ".join(hierarchy[:5]) if hierarchy else worst_group
    p1 = f"Verdict métier : {verdict_label}."
    p2 = f"Hiérarchie retenue (groupes fiables) : {chain}."
    p3 = (
        f"Orientation : concentrer l'investigation sur {worst_group} "
        f"sans imputer l'écart au seul facteur {factor_label}."
    )
    for p in (p1, p2, p3):
        assert_no_causality_abuse(p)
    return [p1, p2, p3]


def interpretation_limits_paragraphs_compact(
    *,
    base_text: str,
    analysis_level: str,
    factor_label: str,
    variable_label: str,
) -> list[str]:
    paragraphs = f2_templates.interpretation_limits_paragraphs(
        base_text=base_text,
        analysis_level=analysis_level,
        measure_annex_available=False,
    )
    extra = (
        f"Cette analyse met en évidence une association entre {factor_label} "
        f"et {variable_label} ; elle ne permet pas à elle seule d'affirmer "
        "une causalité directe certaine."
    )
    assert_no_causality_abuse(extra)
    if extra not in paragraphs:
        paragraphs.append(extra)
    return paragraphs
