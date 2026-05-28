"""
Pré-formatage des entrées S5 — zéro dict brut envoyé au LLM.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from systems.stats_format import (
    certified_loi_candidate_phrase,
    certified_normalite_phrase,
    certified_significance_phrase,
    format_p_value,
    strip_bad_p_value_phrases,
)

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_AGENT_ALIASES = {
    "CpCpkSpecialist": "cp_cpk",
    "AnovaKruskalSpecialist": "anova_kruskal",
    "MannKendallSpecialist": "mann_kendall",
    "ZScoreSpecialist": "zscore",
    "SpcSpecialist": "spc",
    "EwmaCusumSpecialist": "ewma_cusum",
    "RegressionSpecialist": "regression",
}


def canonical_agent(agent: str | None) -> str:
    if not agent:
        return ""
    return _AGENT_ALIASES.get(agent, str(agent).strip().lower())


_DEFAULT_SYNTHESE_INTERDITS = [
    "analysis_context",
    "cpk_summary",
    "anova_summary",
    "trend_summary",
    "descriptions_tabulaires",
    "specialist_results",
    "metrics_summary",
    "pipeline_trace",
    "intent S1",
    "intent S0",
    "YAML client",
    "YAML",
    "tableau présente",
    "pipeline",
    "fallback",
    "LLM",
]

_SYNTHESE_PHRASE_PATTERNS = [
    re.compile(r"intent\s+S\d", re.I),
    re.compile(r"YAML\s+client", re.I),
    re.compile(r"le\s+tableau\s+présente", re.I),
    re.compile(r"tandis\s+que\s+le\s+confirme", re.I),
    re.compile(r"données\s+certifiées", re.I),
    re.compile(r"écart\s+LLM", re.I),
]

_SPECIALIST_LABELS = {
    "cp_cpk": "Capabilité processus (Cp/Cpk)",
    "anova_kruskal": "Comparaison de groupes",
    "mann_kendall": "Tendance",
    "zscore": "Anomalies",
    "spc": "SPC",
    "ewma_cusum": "Surveillance EWMA/CUSUM",
    "regression": "Régression",
    "graphique": "Graphique",
}

_ISOLATED_SENTENCE_WORD = re.compile(
    r"^(Le|La|Un|Une|Les|Des|Du|De|L)$",
    re.IGNORECASE,
)

_TRAILING_DETERMINER = re.compile(
    r"\b(?:le|la|les|un|une|des|du|de|l)\s*$",
    re.IGNORECASE,
)

# Parenthèses métier valides — ne pas confondre avec « ( Enfin »
_VALID_OPEN_PAREN = re.compile(
    r"\(\s*(?:"
    r"Cpk|Cp|p\s*[<>=]|n\s*=|CR\d|O\d|"
    r"\d+(?:[.,]\d+)?"
    r")",
    re.IGNORECASE,
)

_DEFECT_FRAGMENT_PATTERNS = [
    re.compile(r"\(\s+Enfin\b", re.I),
    re.compile(r",\s*Enfin\s*,\s*le\b", re.I),
    re.compile(r"\s+Enfin\s*,\s*le\b", re.I),
    re.compile(r"\ble\s+Enfin\s*,\s*il\b", re.I),
    re.compile(r"\bLe\s+De\s+plus\s*,\s*le\b", re.I),
    re.compile(r"\bEnfin\s*,\s*il\s+est\b", re.I),
    re.compile(r"est,\s*répondant ainsi au seuil EN9100[^.]*\.?", re.I),
    re.compile(r",\s*répondant ainsi au seuil EN9100[^.]*\.?", re.I),
    re.compile(
        r"Les graphiques indiquent que la capabilité sur les \d+ variables est,\s*répondant[^.]*\.?",
        re.I,
    ),
    re.compile(r"Kruskal-Wallis\s*\(\s+Enfin", re.I),
    re.compile(
        r"\(\s+(?!p\s*[<>=]|Cpk|Cp\s*=|n\s*=|CR\d|O\d|\d)"
        r"[A-Za-zÀ-ÿ]",
        re.I,
    ),
]


def strip_orphan_parentheses(text: str) -> str:
    """Nettoie parenthèses orphelines (ex. « CR70, ) »)."""
    out = str(text or "")
    out = re.sub(r",\s*\)", ")", out)
    out = re.sub(r"\(\s*,", "(", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r"\s+,\s*\)", ")", out)
    out = re.sub(r"\s+,\s*\.", ".", out)
    return out


def _paren_counts_balanced(segment: str) -> bool:
    return segment.count("(") == segment.count(")")


def _has_unclosed_paren(segment: str) -> bool:
    depth = 0
    for ch in segment:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return True
    return depth > 0


def _earliest_defect_index(text: str) -> int | None:
    """Position du premier fragment défectueux (tronquer avant)."""
    s = str(text or "")
    if not s:
        return None
    earliest: int | None = None
    for pat in _DEFECT_FRAGMENT_PATTERNS:
        m = pat.search(s)
        if m:
            pos = m.start()
            if earliest is None or pos < earliest:
                earliest = pos
    if _has_unclosed_paren(s):
        depth = 0
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
                if depth == 1 and i > 0:
                    tail = s[i : i + 12]
                    if not _VALID_OPEN_PAREN.match(tail):
                        if earliest is None or i < earliest:
                            earliest = i
            elif ch == ")":
                depth -= 1
    return earliest


def _truncate_to_last_complete_sentence(text: str) -> str:
    """Garde le texte jusqu'au dernier point/exclamation/interrogation complet."""
    s = str(text or "").strip()
    if not s:
        return ""
    ends = list(re.finditer(r"[.!?…](?:\s+|$)", s))
    if ends:
        return s[: ends[-1].end()].strip()
    return ""


def truncate_defective_tail(text: str) -> str:
    """
    Supprime tout fragment après le dernier point valide si défaut détecté.
    Ne reformule pas — coupe uniquement.
    """
    s = str(text or "").strip()
    if not s:
        return ""
    defect_at = _earliest_defect_index(s)
    if defect_at is not None and defect_at > 0:
        s = s[:defect_at].rstrip(" ,;:")
        s = _truncate_to_last_complete_sentence(s)
    if _TRAILING_DETERMINER.search(s):
        s = _TRAILING_DETERMINER.sub("", s).strip()
        s = _truncate_to_last_complete_sentence(s)
    if _has_unclosed_paren(s) or not _paren_counts_balanced(s):
        s = _truncate_to_last_complete_sentence(s)
    return s.strip()


def _sentence_is_broken(sentence: str) -> bool:
    s = sentence.strip()
    if not s:
        return True
    if re.search(r",\s*$", s):
        return True
    if re.search(r"\best,\s*\.?\s*$", s, re.IGNORECASE):
        return True
    if _earliest_defect_index(s) is not None:
        return True
    if _has_unclosed_paren(s) or not _paren_counts_balanced(s):
        return True
    if _TRAILING_DETERMINER.search(s):
        return True
    if re.search(r"\(\s+Enfin\b", s, re.I):
        return True
    if re.search(r",\s*Enfin\s*,\s*le\b", s, re.I):
        return True
    if re.search(r"\ble\s+Enfin\b", s, re.I):
        return True
    if re.search(r"\bLe\s+De\s+plus\b", s, re.I):
        return True
    if re.search(r"\bEnfin\s*,\s*il\b", s, re.I):
        return True
    if re.search(r"est,\s*répondant", s, re.I):
        return True
    if re.search(r"variables est,\s*répondant", s, re.I):
        return True
    words = re.findall(r"[\wÀ-ÿ]+", s)
    if len(words) == 1 and _ISOLATED_SENTENCE_WORD.match(words[0]):
        return True
    return False


def strip_broken_sentences(text: str) -> str:
    """Supprime les phrases cassées — pas de remplacement LLM."""
    raw = truncate_defective_tail(str(text or ""))
    if not raw:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", raw)
    kept = [p.strip() for p in parts if p.strip() and not _sentence_is_broken(p.strip())]
    out = strip_orphan_parentheses(" ".join(kept).strip())
    return truncate_defective_tail(out)


def polish_client_text(text: str) -> str:
    """Nettoyage final texte visible PDF client."""
    out = strip_orphan_parentheses(str(text or ""))
    out = truncate_defective_tail(out)
    out = strip_broken_sentences(out)
    out = re.sub(r"\broot\s+cause\b", "analyse des causes racines", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip()
    if _TRAILING_DETERMINER.search(out):
        out = truncate_defective_tail(_TRAILING_DETERMINER.sub("", out).strip())
    return out


def synthese_forbidden_terms(context: "ClientContext") -> list[str]:
    """Termes techniques internes interdits dans la synthèse PDF (YAML recommandations)."""
    raw = context.get_recommandations()
    extra = raw.get("synthese_interdits", []) if isinstance(raw, dict) else []
    terms = list(_DEFAULT_SYNTHESE_INTERDITS)
    for t in extra:
        if t and str(t) not in terms:
            terms.append(str(t))
    return terms


def specialist_label(specialist: str | None) -> str:
    key = canonical_agent(specialist) or str(specialist or "").strip().lower()
    return _SPECIALIST_LABELS.get(key, "Analyse")


def sanitize_synthesis_text(
    text: str,
    internal_terms: list[str],
    profile_forbidden: list[str],
) -> tuple[str, list[str]]:
    """Retire jargon interne et termes interdits profil."""
    warnings: list[str] = []
    out = str(text or "")
    for term in internal_terms + list(profile_forbidden):
        t = str(term).strip()
        if not t:
            continue
        pattern = re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)
        if pattern.search(out):
            warnings.append(f"Terme retiré de la synthèse : {t}")
            out = pattern.sub("", out)
    out = strip_bad_p_value_phrases(out)
    out = polish_client_text(out)
    for pat in _SYNTHESE_PHRASE_PATTERNS:
        if pat.search(out):
            warnings.append(f"Formulation retirée de la synthèse : {pat.pattern}")
            out = pat.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,;])", r"\1", out)
    return out, warnings


def certified_phrase_from_results(
    specialist: str | None,
    specialist_results: list[dict] | None,
) -> str | None:
    """Libellé Python pour R6 — le LLM ne reformule pas la p-value."""
    agent = canonical_agent(specialist)
    for row in specialist_results or []:
        if row.get("status") != "success":
            continue
        if canonical_agent(row.get("agent")) != agent:
            continue
        payload = row.get("result") or {}
        if not isinstance(payload, dict):
            continue
        if agent == "anova_kruskal":
            phrase = payload.get("significance_phrase")
            if phrase:
                return str(phrase).strip()
            return certified_significance_phrase(
                payload.get("p_value"),
                payload.get("significatif"),
                methode=str(payload.get("methode_choisie", "Kruskal-Wallis")),
            )
    return None


def build_synthesis_corpus(
    interpretations: list[dict],
    specialist_results: list[dict] | None = None,
) -> str:
    """Corpus R6 — libellés métier, pas d'identifiants techniques."""
    blocks: list[str] = []
    for it in interpretations:
        label = specialist_label(it.get("specialist"))
        cert = certified_phrase_from_results(it.get("specialist"), specialist_results)
        texte = str(it.get("texte", "") or "").strip()
        if cert:
            blocks.append(f"- {label} : {cert}")
        elif texte:
            blocks.append(f"- {label} : {texte}")
    return "\n".join(blocks)


_META_CUT_PATTERNS = [
    re.compile(r"(?i)explications\s+des\s+modifications"),
    re.compile(r"(?i)\*\*explications\s+des\s+modifications"),
    re.compile(r"(?i)texte\s+original\s*:"),
    re.compile(r"(?i)\*\*avertissements\s+syst[eè]me\s*:\*\*"),
]
_META_LINE_PATTERNS = [
    re.compile(r"(?i)^\s*\d+\.\s+\*\*"),
    re.compile(r"(?i)^\s*[-*]\s+interprétation\s+automatique\s+indisponible"),
]


def strip_llm_meta_from_interpretation(text: str) -> str:
    """Retire le bavardage de correction LLM (R5) — jamais dans un PDF client."""
    if not text:
        return ""
    out = text.strip()
    lead = re.search(r"(?is)voici\s+le\s+texte\s+corrig[^:]*:\s*(?:---\s*)?", out)
    if lead:
        out = out[lead.end() :].strip()
    else:
        out = re.sub(
            r"(?is)^\s*voici\s+le\s+texte\s+corrig[^.\n]*[.\n]?\s*[-—]*\s*",
            "",
            out,
        )
    out = re.sub(r"(?is)^\s*---\s*", "", out)
    for pat in _META_CUT_PATTERNS:
        m = pat.search(out)
        if m:
            out = out[: m.start()].strip()
    out = re.sub(
        r"(?i)interprétation\s+automatique\s+indisponible\s+pour\s+cp_cpk[^.]*\.?\s*",
        "",
        out,
    )
    lines: list[str] = []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in _META_LINE_PATTERNS):
            break
        lines.append(stripped)
    out = " ".join(lines) if lines else out
    return re.sub(r"\s{2,}", " ", out).strip()


def looks_like_llm_meta_artifact(text: str) -> bool:
    low = text.lower()
    return any(
        m in low
        for m in (
            "explications des modifications",
            "voici le texte corrig",
            "texte original :",
            "précision de la p-value",
            "formatage et lisibilité",
        )
    )


def profile_config(context: "ClientContext", profile: str) -> dict:
    profils = context.profils or {}
    default = profils.get("technicien", {})
    if not isinstance(default, dict):
        default = {}
    cfg = profils.get(profile, default)
    return cfg if isinstance(cfg, dict) else default


def descriptions_list(s4_output: dict) -> list[str]:
    items: list[str] = []
    raw = s4_output.get("descriptions_tabulaires", "")
    if isinstance(raw, list):
        items.extend(str(d).strip() for d in raw if d)
    elif isinstance(raw, str) and raw.strip():
        items.extend(p.strip() for p in raw.split("\n\n") if p.strip())
    for table in s4_output.get("tables") or []:
        desc = table.get("description") if isinstance(table, dict) else None
        tid = table.get("id", "tableau") if isinstance(table, dict) else "tableau"
        if desc:
            items.append(f"Tableau {tid} : {desc}")
    for graph in s4_output.get("graphs", s4_output.get("charts", [])) or []:
        if not isinstance(graph, dict):
            continue
        desc = graph.get("description")
        gtype = graph.get("type", "graphique")
        title = graph.get("title", gtype)
        if desc:
            items.append(f"Graphique {title} ({gtype}) : {desc}")
    return items


_R2_NUMERIC_KEYS: dict[str, tuple[str, ...]] = {
    "descriptive": (
        "moyenne",
        "mediane",
        "ecart_type",
        "variance",
        "skewness",
        "kurtosis",
        "min",
        "max",
        "q1",
        "q3",
        "iqr",
        "pct_hors_lti_lts",
        "centrage",
    ),
    "normality": ("statistique", "shapiro_stat", "shapiro_p", "ad_stat", "ks_stat", "ks_p", "p_value"),
    "distribution_fit": ("aic_min", "bic_min"),
}

_LOI_SYNONYMS: dict[str, tuple[str, ...]] = {
    "normale": ("normale", "gaussienne", "gaussien"),
    "log_normale": ("log-normale", "log normale", "lognormale", "log normale"),
    "weibull": ("weibull",),
    "exponentielle": ("exponentielle", "exponential"),
    "uniforme": ("uniforme", "uniform"),
}


def flatten_numbers(obj: Any, prefix: str = "") -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.extend(flatten_numbers(v, key))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(flatten_numbers(v, f"{prefix}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        try:
            out.append((prefix, float(obj)))
        except (TypeError, ValueError):
            pass
    return out


def reference_numbers_for_result(result: dict) -> dict[str, float]:
    """Nombres de référence pour un résultat spécialiste (champs P3 R2)."""
    refs: dict[str, float] = {}
    payload = result.get("result") or {}
    if not isinstance(payload, dict):
        return refs
    agent = canonical_agent(result.get("agent"))
    allowed = _R2_NUMERIC_KEYS.get(agent)
    if allowed:
        for key in allowed:
            val = payload.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                try:
                    fval = float(val)
                    refs[f"{agent}.{key}"] = fval
                    refs[key] = fval
                except (TypeError, ValueError):
                    pass
        return refs
    for key, val in flatten_numbers(payload):
        refs[f"{agent}.{key}"] = val
        refs[key.split(".")[-1]] = val
    return refs


def _laws_mentioned_in_text(text: str) -> set[str]:
    low = str(text or "").lower()
    found: set[str] = set()
    for loi_id, patterns in _LOI_SYNONYMS.items():
        if any(p in low for p in patterns):
            found.add(loi_id)
    return found


def verify_r2_qualitative(text: str, result: dict) -> str | None:
    """
    Vérifications qualitatives R2 (P3).
    Retourne 'Reject' ou None.
    """
    from systems.stats_format import contains_forbidden_loi_wording

    if contains_forbidden_loi_wording(text):
        return "Reject"

    agent = canonical_agent(result.get("agent"))
    payload = result.get("result") or {}
    if agent == "distribution_fit" and result.get("status") == "success":
        loi_py = payload.get("loi_retenue") or payload.get("loi_candidate_aic")
        if loi_py:
            mentioned = _laws_mentioned_in_text(text)
            if mentioned and loi_py not in mentioned:
                return "Reject"

    if agent == "normality" and result.get("status") == "success":
        verdict = str(payload.get("verdict_normalite", "")).lower()
        low = text.lower()
        claims_normal = any(
            x in low
            for x in (
                "compatible avec une loi normale",
                "distribution normale",
                "est normale",
                "loi normale",
                " normale (",
            )
        ) and "non normale" not in low and "non-normale" not in low
        claims_non = any(
            x in low
            for x in (
                "non normale",
                "non-normale",
                "écart significatif à la normale",
                "pas normale",
            )
        )
        if verdict == "non_normale" and claims_normal and not claims_non:
            return "Reject"
        if verdict == "normale" and claims_non and not claims_normal:
            return "Reject"

    return None


def zero_llm_synthesis(context: "ClientContext") -> bool:
    """Opt-in YAML explicite — jamais activé automatiquement."""
    return bool(context.get_synthese_s5_config().get("zero_llm_synthese", False))


def multi_variable_duration_warning(
    intent: dict,
    context: "ClientContext",
) -> str | None:
    """Avertissement informatif si beaucoup de variables (pas de changement de mode)."""
    cfg = context.get_synthese_s5_config()
    seuil = int(
        cfg.get(
            "avertissement_si_variables_gt",
            cfg.get("mode_si_variables_gt", 3),
        )
    )
    n_vars = len(intent.get("variables") or [])
    if n_vars > seuil:
        return (
            f"Analyse de {n_vars} variables détectée — "
            "le traitement peut prendre plus de temps que prévu."
        )
    return None


def assemble_synthesis_python(
    interpretations: list[dict],
    intent: dict,
    specialist_results: list[dict] | None = None,
) -> str:
    """Synthèse 100 % Python — corpus de fallbacks certifiés."""
    piece = intent.get("piece")
    operation = intent.get("operation")
    intention = intent.get("intention", "analyse")
    intro = (
        f"Synthèse {intention} sur {piece} ({operation}) : "
        if piece and operation
        else "Synthèse : "
    )
    blocks: list[str] = []
    for it in interpretations:
        texte = str(it.get("texte", "") or "").strip()
        if not texte or _looks_like_field_dump(texte):
            continue
        blocks.append(texte)
    if not blocks:
        return "Synthèse non disponible — résultats techniques ci-dessus."
    body = " ".join(blocks[:12])
    return polish_client_text(f"{intro}{body}")


def _looks_like_field_dump(text: str) -> bool:
    """Détecte une concaténation brute « clé : valeur »."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) < 3:
        return False
    dump_like = sum(1 for ln in lines if re.match(r"^[a-z_]+\s*[:=]", ln, re.I))
    return dump_like >= max(2, len(lines) // 2)


def format_specialist_prompt(result: dict) -> str:
    """Texte prêt pour R1 — chiffres clés + unités + seuils."""
    agent = canonical_agent(result.get("agent"))
    status = result.get("status", "")
    if status != "success":
        return (
            f"Spécialiste : {agent}\n"
            f"Statut calcul : {status}\n"
            f"Message : {result.get('error') or result.get('result', {}).get('reason', 'non disponible')}\n"
            "Rédige une phrase factuelle courte pour l'utilisateur."
        )

    p = result.get("result") or {}
    lines = [f"Spécialiste : {agent}", "Données certifiées Python (ne modifie aucun chiffre) :"]

    if agent == "cp_cpk":
        interp = p.get("interpretation_Cpk", "")
        lines.extend(
            [
                f"- Variable / cote : {p.get('colonne', 'N/A')}",
                f"- Cpk = {p.get('Cpk')}",
                f"- Cp = {p.get('Cp')}",
                f"- Conforme EN9100 (seuil Cpk >= 1,33) : {p.get('conforme_EN9100')}",
                f"- Diagnostic processus : {interp}",
                f"- Hors limites % : {p.get('hors_limites_pct')}",
                f"- n = {p.get('n')}",
            ]
        )
        lines.append(
            "\nConsigne métier : explique dispersion, centrage et conformité "
            "(ex. dispersion excessive, centrage à revoir, procédé sous contrôle). "
            "Ne te contente pas de recopier Cpk = …"
        )
    elif agent == "anova_kruskal":
        phrase = p.get("significance_phrase") or certified_significance_phrase(
            p.get("p_value"),
            p.get("significatif"),
            methode=str(p.get("methode_choisie", "Kruskal-Wallis")),
        )
        lines.extend(
            [
                f"- Méthode : {p.get('methode_choisie')}",
                f"- Libellé certifié (citer tel quel) : {phrase}",
                f"- Affichage p-value : {p.get('p_value_display', format_p_value(p.get('p_value')))}",
                f"- Significatif (alpha={p.get('alpha', 0.05)}) : {p.get('significatif')}",
            ]
        )
        lines.append(
            "\nConsigne : ne reformule JAMAIS la p-value "
            "(interdit : « environ 0 », « p = 0,000 », « 0,0000 »)."
        )
    elif agent == "mann_kendall":
        lines.extend(
            [
                f"- Variable : {p.get('colonne', 'N/A')}",
                f"- Tendance : {p.get('tendance')}",
                f"- Affichage p-value : {p.get('p_value_display', format_p_value(p.get('p_value')))}",
                f"- Pente Sen = {p.get('sen_slope')}",
            ]
        )
    elif agent == "descriptive":
        lines.extend(
            [
                f"- Variable : {p.get('colonne', 'N/A')}",
                f"- n = {p.get('n')}",
                f"- moyenne = {p.get('moyenne')} mm",
                f"- médiane = {p.get('mediane')} mm",
                f"- écart-type = {p.get('ecart_type')} mm",
                f"- skewness = {p.get('skewness')}",
                f"- kurtosis = {p.get('kurtosis')}",
            ]
        )
    elif agent == "normality":
        phrase = p.get("normalite_phrase") or certified_normalite_phrase(
            p.get("verdict_normalite"),
            p.get("test_utilise"),
            p.get("statistique"),
            p.get("p_value"),
            p_value_display=p.get("p_value_display"),
        )
        lines.extend(
            [
                f"- Variable : {p.get('colonne', 'N/A')}",
                f"- Libellé certifié (citer tel quel) : {phrase}",
                f"- verdict_normalite = {p.get('verdict_normalite')}",
            ]
        )
    elif agent == "distribution_fit":
        loi = p.get("loi_retenue") or p.get("loi_candidate_aic")
        phrase = p.get("interpretation_loi") or certified_loi_candidate_phrase(
            loi, p.get("aic_min")
        )
        lines.extend(
            [
                f"- Variable : {p.get('colonne', 'N/A')}",
                f"- loi_retenue = {loi}",
                f"- Libellé certifié (citer tel quel) : {phrase}",
                f"- aic_min = {p.get('aic_min')}",
            ]
        )
        lines.append(
            "\nConsigne : ne jamais écrire « loi probable » ou « loi possible »."
        )
    elif agent == "zscore":
        lines.extend(
            [
                f"- Anomalies détectées : {p.get('nb_anomalies', p.get('nombre_anomalies'))}",
                f"- Pourcentage anomalies : {p.get('pourcentage_anomalies')}",
            ]
        )
    else:
        for key, val in list(p.items())[:12]:
            if isinstance(val, (int, float, str, bool)) or val is None:
                lines.append(f"- {key} = {val}")

    if agent != "cp_cpk":
        lines.append(
            "\nConsigne : rédige 2 à 4 phrases en français, langage clair, "
            "en citant les chiffres EXACTEMENT comme ci-dessus."
        )
    return "\n".join(lines)


def friendly_group_label(group_col: str | None, intent: dict | None = None) -> str:
    """Libellé métier pour la colonne de groupement (pas de Ref_Matrice en client)."""
    name = str(group_col or "").strip()
    if name in ("Ref_Matrice", "ref_matrice"):
        return "matrices"
    if intent:
        gb = intent.get("group_by")
        if gb == "Ref_Matrice" or gb == ["Ref_Matrice"]:
            return "matrices"
    return name.replace("_", " ").lower() if name else "groupes"


def _dunn_pairs_summary(specialist_results: list[dict] | None, max_pairs: int = 4) -> str:
    for row in specialist_results or []:
        if row.get("status") != "success":
            continue
        if canonical_agent(row.get("agent")) != "dunn_posthoc":
            continue
        paires = (row.get("result") or {}).get("paires_significatives") or []
        labels: list[str] = []
        for pair in paires[:max_pairs]:
            if not isinstance(pair, dict):
                continue
            ga = pair.get("groupe_a", "")
            gb = pair.get("groupe_b", "")
            if ga and gb:
                labels.append(f"{ga} vs {gb}")
        if labels:
            return ", ".join(labels)
    return ""


def enriched_descriptive_interpretation(result: dict, intent: dict | None = None) -> str:
    """Fallback portrait descriptif (Python pur, auditable)."""
    p = result.get("result") or {}
    col = p.get("colonne", "la mesure")
    n = p.get("n")
    moy = p.get("moyenne")
    med = p.get("mediane")
    sigma = p.get("ecart_type")
    pct = p.get("pct_hors_lti_lts")
    centrage = p.get("centrage")
    parts = [
        f"Portrait de {col} (n={n}) : moyenne {moy} mm, médiane {med} mm, "
        f"écart-type {sigma} mm."
    ]
    if pct is not None:
        parts.append(f"{pct} % des mesures hors tolérances LTI/LTS.")
    if centrage is not None:
        parts.append(f"Centrage relatif {centrage} (par rapport au nominal).")
    disp = p.get("interpretation_dispersion")
    if disp and disp not in parts[-1]:
        parts.append(str(disp))
    _ = intent
    return polish_client_text(" ".join(parts))


def enriched_normality_interpretation(result: dict) -> str:
    """Fallback normalité — verdict Python uniquement."""
    p = result.get("result") or {}
    col = p.get("colonne", "la mesure")
    phrase = p.get("normalite_phrase") or certified_normalite_phrase(
        p.get("verdict_normalite"),
        p.get("test_utilise"),
        p.get("statistique"),
        p.get("p_value"),
        p_value_display=p.get("p_value_display"),
    )
    n = p.get("n")
    return polish_client_text(f"{col} : {phrase} (n={n}).")


def enriched_distribution_fit_interpretation(result: dict) -> str:
    """Fallback ajustement de loi — jamais « loi probable »."""
    p = result.get("result") or {}
    col = p.get("colonne", "la mesure")
    loi = p.get("loi_retenue") or p.get("loi_candidate_aic")
    interp = p.get("interpretation_loi") or certified_loi_candidate_phrase(
        loi, p.get("aic_min")
    )
    return polish_client_text(f"{col} : {interp}.")


def enriched_anova_interpretation(
    result: dict,
    specialist_results: list[dict] | None = None,
    intent: dict | None = None,
) -> str:
    """Interprétation ANOVA/Kruskal complète (fallback R1/R2 — auditable)."""
    p = result.get("result") or {}
    methode = str(p.get("methode_choisie", "Kruskal-Wallis"))
    stat_name = str(p.get("test_stat_name", "H"))
    stat_val = p.get("test_stat")
    p_disp = p.get("p_value_display") or format_p_value(p.get("p_value"))
    phrase = p.get("significance_phrase") or certified_significance_phrase(
        p.get("p_value"),
        p.get("significatif"),
        methode=methode,
    )
    group_label = friendly_group_label(p.get("colonne_groupe"), intent)
    variables = intent.get("variables") if intent else None
    if variables:
        vars_clean = [str(v).strip() for v in variables[:5] if v and str(v).strip()]
        vars_txt = ", ".join(vars_clean[:4])
        if len(vars_clean) > 4:
            vars_txt += ", …"
    else:
        target = p.get("colonne_cible")
        vars_txt = str(target) if target else "les variables analysées"

    lead = f"{methode}"
    if stat_val is not None:
        lead += f" {stat_name}={stat_val}"
    body = f"{lead}, {phrase} entre les {group_label} ({vars_txt})."
    paires = _dunn_pairs_summary(specialist_results)
    if paires:
        body += f" Paires significatives (Dunn) : {paires}."
    elif not p.get("significatif"):
        body += " Aucune différence significative retenue."
    return polish_client_text(body.strip())


def python_fallback_interpretation(
    result: dict,
    specialist_results: list[dict] | None = None,
    intent: dict | None = None,
) -> str:
    """Résumé Python si LLM indisponible."""
    agent = canonical_agent(result.get("agent"))
    if result.get("status") != "success":
        reason = result.get("error") or (result.get("result") or {}).get("reason", "")
        return f"Analyse {agent} : calcul non disponible ({reason})."

    p = result.get("result") or {}
    if agent == "cp_cpk":
        cpk = p.get("Cpk")
        conforme = p.get("conforme_EN9100")
        col = p.get("colonne", "")
        interp = str(p.get("interpretation_Cpk", "") or "").strip()
        try:
            cpk_f = float(cpk)
        except (TypeError, ValueError):
            cpk_f = None
        if cpk_f is not None and cpk_f < 1.0:
            metier = (
                f"Sur {col}, la capabilité est critique (Cpk = {cpk}) : "
                "dispersion et centrage insuffisants — action corrective immédiate."
            )
        elif cpk_f is not None and cpk_f < 1.33:
            metier = (
                f"Sur {col}, le procédé est en limite (Cpk = {cpk}) : "
                "réduire la dispersion ou recentrer sur la cible nominale."
            )
        elif conforme:
            metier = f"Sur {col}, le procédé est sous contrôle (Cpk = {cpk})."
        else:
            metier = f"Sur {col}, Cpk = {cpk} : conformité EN9100 à confirmer."
        if interp and interp.lower() not in metier.lower():
            metier = f"{metier} {interp}"
        return metier.strip()
    if agent == "dunn_posthoc":
        paires = p.get("paires_significatives") or []
        if not paires:
            return p.get("interpretation", "Aucune paire significative au post-hoc Dunn.")
        top = paires[:3]
        parts = [x.get("libelle", "") for x in top if x.get("libelle")]
        return " ".join(parts) + (f" (+{len(paires) - len(top)} autre(s) paire(s))" if len(paires) > len(top) else "")
    if agent == "anova_kruskal":
        return enriched_anova_interpretation(result, specialist_results, intent)
    if agent == "descriptive":
        return enriched_descriptive_interpretation(result, intent)
    if agent == "normality":
        return enriched_normality_interpretation(result)
    if agent == "distribution_fit":
        return enriched_distribution_fit_interpretation(result)
    if agent == "mann_kendall":
        p_disp = p.get("p_value_display") or format_p_value(p.get("p_value"))
        return (
            f"Tendance sur {p.get('colonne')} : {p.get('tendance')} "
            f"({p_disp}, pente Sen = {p.get('sen_slope')})."
        )
    return f"Résultat {agent} : " + ", ".join(
        f"{k}={v}" for k, v in list(p.items())[:6] if isinstance(v, (int, float, str))
    )


def format_graph_prompt(description: str, index: int) -> str:
    return (
        f"Graphique n°{index + 1}\n"
        f"Description certifiée :\n{description}\n\n"
        "Rédige 1 à 2 phrases expliquant ce que montre le graphique, "
        "sans inventer de chiffres absents de la description."
    )


def extract_numbers_from_text(text: str) -> list[float]:
    found: list[float] = []
    for m in re.finditer(r"-?\d+(?:[.,]\d+)?", text):
        s = m.group().replace(",", ".")
        try:
            found.append(float(s))
        except ValueError:
            continue
    return found


def verify_number_against_refs(value: float, refs: dict[str, float]) -> tuple[str, float | None]:
    """Retourne (Accept|Review|Reject, meilleur écart relatif)."""
    if not refs:
        return "Accept", None
    best_rel = None
    matched = False
    for ref in refs.values():
        if ref == 0:
            if abs(value - ref) < 1e-6:
                matched = True
                best_rel = 0.0
            continue
        rel = abs(value - ref) / abs(ref)
        if rel <= 0.01:
            return "Accept", rel
        if best_rel is None or rel < best_rel:
            best_rel = rel
        if rel <= 0.05:
            matched = True
    if matched and best_rel is not None:
        return "Review", best_rel
    if best_rel is not None and best_rel > 0.05:
        return "Reject", best_rel
    return "Reject", best_rel


def compute_fidelity_score(interpretations: list[dict]) -> float:
    if not interpretations:
        return 0.0
    scores = []
    for item in interpretations:
        st = item.get("statut", "")
        if st == "Accept":
            scores.append(1.0)
        elif st == "Review":
            scores.append(0.75)
        elif st == "fallback":
            scores.append(0.9)
        else:
            scores.append(0.3)
    return round(sum(scores) / len(scores), 3)
