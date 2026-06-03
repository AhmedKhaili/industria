"""
Pré-formatage S7 — verdict, profils, métriques (zéro LLM).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from systems.stats_format import format_p_value

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}

_DEFAULT_RAPPORT_PDF = {
    "version": "4.0",
    "industria_version": "v4.0",
    "mode": "internal_debug",
    "reference_prefix": "RPT",
    "max_graphiques_directeur": 3,
    "max_graphiques_technicien": 12,
    "max_graphiques_operateur": 8,
    "max_graphiques_client": 3,
    "max_graphiques_complet": 8,
    "max_pages_complet": 12,
    "max_recommandations_client": 4,
    "f2_narratif_enabled": False,
    "f2_compact_enabled": False,
    "sauvegarder_dans": "reports/",
    "bandeau_defaut_couleur": "#1565C0",
    "boxplots_prioritaires": [],
    "cpk_couleurs": {
        "critique": {"max": 1.0, "fond": "#FFEBEE"},
        "limite": {"min": 1.0, "max": 1.33, "fond": "#FFF3E0"},
        "conforme": {"min": 1.33, "fond": "#E8F5E9"},
    },
    "verdict_bandeaux": {
        "NO_GO": {
            "fond": "#C62828",
            "texte": "#FFFFFF",
            "libelle": "NO-GO — Action corrective requise",
        },
        "NO_GO_OPERATIONNEL": {
            "fond": "#C62828",
            "texte": "#FFFFFF",
            "libelle": "NO-GO — Intervention urgente requise",
        },
        "SURVEILLANCE": {
            "fond": "#F57F17",
            "texte": "#FFFFFF",
            "libelle": "SURVEILLANCE — Suivi renforcé",
        },
        "GO": {
            "fond": "#2E7D32",
            "texte": "#FFFFFF",
            "libelle": "GO — Processus conforme",
        },
    },
    "verdict_libelles": {
        "GO": "GO — Procédé sous contrôle",
        "NO_GO": "NO-GO — Action corrective requise",
        "NO_GO_OPERATIONNEL": "NO-GO opérationnel — Intervention urgente",
        "SURVEILLANCE": "SURVEILLANCE — Suivi renforcé",
    },
}

_SPECIALIST_CLIENT_LABELS = {
    "anova_kruskal": "Comparaison de groupes",
    "cp_cpk": "Capabilité processus",
    "dunn_posthoc": "Comparaison post-hoc (Dunn)",
    "mann_kendall": "Tendance",
    "zscore": "Anomalies",
}

_CONTRA_EN9100 = [
    re.compile(r"conforme aux normes", re.I),
    re.compile(r"sup[eé]rieur.*seuil.*1[,.]33", re.I),
    re.compile(r"sup[eé]rieur[eé]?\s+à\s+1[,.]33", re.I),
    re.compile(r"capabilit[eé]\s+sur\s+les\s+\d+\s+variables\s+sup[eé]rieur", re.I),
    re.compile(r"atteint le seuil EN9100", re.I),
    re.compile(r"performance globale conforme", re.I),
    re.compile(r"respectant le seuil EN9100", re.I),
    re.compile(r"respecte le seuil EN9100", re.I),
    re.compile(r"répondant au seuil EN9100", re.I),
    re.compile(r"répondant ainsi au seuil EN9100", re.I),
    re.compile(r"est,\s*répondant ainsi au seuil", re.I),
    re.compile(r"est,\s*répondant au seuil EN9100", re.I),
]

_CLIENT_STRIP_PATTERNS = [
    re.compile(r"intent\s+S\d[^.]*\.?", re.I),
    re.compile(r"YAML\s+client[^.]*\.?", re.I),
    re.compile(r"le\s+tableau\s+présente[^.]*\.?", re.I),
    re.compile(r"tandis\s+que\s+le\s+graphique[^.]*\.?", re.I),
    re.compile(r"graphique\s+n[°o]\s*\d+[^.]*\.?", re.I),
    *_CONTRA_EN9100,
]

_OPERATEUR_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcpk\b", re.I), "indice de capabilité"),
    (re.compile(r"\bcp\b", re.I), "capabilité"),
    (re.compile(r"\bp[- ]?value\b", re.I), "significativité"),
    (re.compile(r"\banova\b", re.I), "comparaison de groupes"),
    (re.compile(r"\bkruskal\b", re.I), "comparaison de groupes"),
    (re.compile(r"\bz[- ]?score\b", re.I), "valeur anormale"),
    (re.compile(r"\bécart[- ]type\b", re.I), "dispersion"),
    (re.compile(r"\bshapiro\b", re.I), "test de normalité"),
    (re.compile(r"\bσ\b"), "écart"),
    (re.compile(r"\bucl\b", re.I), "limite haute"),
    (re.compile(r"\blcl\b", re.I), "limite basse"),
]

_GRAPH_ONLY_RE = re.compile(r"^graphique\s*:", re.I)


_RENDER_MODES = frozenset({"audit_en9100", "narratif_metier"})


def is_f2_narratif_enabled(cfg: dict) -> bool:
    """P7-F2 narratif long — désactivé par défaut (expérimental gelé)."""
    return bool(cfg.get("f2_narratif_enabled", False))


def is_f2_compact_enabled(cfg: dict) -> bool:
    """P7-F2 compact façon vrillage — désactivé par défaut jusqu'à Phase C."""
    return bool(cfg.get("f2_compact_enabled", False))


def f2_compact_config(cfg: dict) -> dict[str, Any]:
    """Sous-config rapport_pdf.f2_compact (seuils filtrage présentation)."""
    raw = cfg.get("f2_compact")
    return dict(raw) if isinstance(raw, dict) else {}


def resolve_render_mode(intent: dict, cfg: dict) -> str:
    """Mode de rendu PDF — défaut audit_en9100."""
    explicit = str(intent.get("rapport_mode") or "").strip()
    if explicit in _RENDER_MODES:
        return explicit
    default = str(cfg.get("default_mode", "audit_en9100")).strip()
    if default in _RENDER_MODES:
        return default
    return "audit_en9100"


def text_contains_forbidden_causality(text: str) -> bool:
    """Formulations causales positives abusives (pas les limites prudente/négatives)."""
    from systems.s7.f2_templates import text_contains_abusive_causality

    return text_contains_abusive_causality(text)


def rapport_pdf_config(context: "ClientContext") -> dict:
    raw = context.get_rapport_pdf()
    cfg = dict(_DEFAULT_RAPPORT_PDF)
    for key, val in raw.items():
        if key in ("verdict_libelles", "verdict_bandeaux", "cpk_couleurs") and isinstance(val, dict):
            merged = dict(cfg.get(key, {}))
            merged.update(val)
            cfg[key] = merged
        else:
            cfg[key] = val
    return cfg


def is_client_mode(cfg: dict) -> bool:
    return str(cfg.get("mode", "internal_debug")).lower() in (
        "client",
        "client_quality",
        "client-facing",
        "client_facing",
    )


_COMPLET_INTENTIONS = frozenset(
    {"portrait_statistique", "analyse_complete", "diagnostic_causal"}
)

_LOI_CLIENT_LABELS = {
    "normale": "normale",
    "log_normale": "log-normale",
    "weibull": "Weibull",
    "exponentielle": "exponentielle",
    "uniforme": "uniforme",
}


def resolve_rapport_type(intent: dict) -> str:
    """simple = layout v5c ; complet = portrait + sections étendues (P4)."""
    explicit = str(intent.get("rapport_type") or "").strip().lower()
    if explicit in ("complet", "complete", "full"):
        return "complet"
    if explicit == "simple":
        return "simple"
    intention = str(intent.get("intention") or "").strip().lower()
    if intention in _COMPLET_INTENTIONS:
        return "complet"
    return "simple"


def max_graphiques_complet(cfg: dict) -> int:
    return int(cfg.get("max_graphiques_complet", 5))


def max_pages_complet(cfg: dict) -> int:
    return int(cfg.get("max_pages_complet", 12))


def _canonical_s3_agent(agent: str | None) -> str:
    name = str(agent or "").strip()
    mapping = {
        "CpCpkSpecialist": "cp_cpk",
        "DescriptiveSpecialist": "descriptive",
        "NormalitySpecialist": "normality",
        "DistributionFitSpecialist": "distribution_fit",
        "AnovaKruskalSpecialist": "anova_kruskal",
        "DunnPosthocSpecialist": "dunn_posthoc",
    }
    return mapping.get(name, name.lower())


def normality_client_verdict(verdict: str | None) -> str:
    v = str(verdict or "").strip().lower()
    if v == "normale":
        return "Normale"
    if v == "non_normale":
        return "Non normale"
    return "Indéterminé"


def client_loi_retenue_phrase(loi: str | None) -> str:
    """Libellé client — sans AIC/BIC bruts."""
    if not loi:
        return "Ajustement de loi non disponible"
    label = _LOI_CLIENT_LABELS.get(str(loi).strip().lower(), str(loi).replace("_", "-"))
    return f"Meilleur ajustement : {label}"


def _fmt_num(val: Any, decimals: int = 3) -> str:
    if val is None:
        return "N/A"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return sanitize_text(str(val))
    formatted = f"{f:.{decimals}f}".replace(".", ",")
    return formatted


def _pct_cell(val: Any) -> str:
    if val is None:
        return "N/A"
    return f"{_fmt_num(val, 1)} %"


def portrait_metrics_snapshot(specialist_results: list[dict]) -> dict[str, Any]:
    """Agrège % hors tol et Cpk min pour verdict portrait (Python pur)."""
    max_pct_hors = 0.0
    has_pct = False
    min_cpk: float | None = None
    min_cpk_col = ""
    for item in specialist_results:
        if item.get("status") != "success":
            continue
        agent = _canonical_s3_agent(item.get("agent"))
        res = item.get("result") or {}
        if not isinstance(res, dict):
            continue
        if agent == "descriptive":
            pct = res.get("pct_hors_lti_lts")
            if pct is not None:
                has_pct = True
                max_pct_hors = max(max_pct_hors, float(pct))
        elif agent == "cp_cpk":
            cpk = res.get("Cpk", res.get("cpk"))
            if cpk is not None:
                try:
                    v = float(cpk)
                except (TypeError, ValueError):
                    continue
                if min_cpk is None or v < min_cpk:
                    min_cpk = v
                    min_cpk_col = str(res.get("colonne", ""))
    return {
        "max_pct_hors_tol": max_pct_hors if has_pct else None,
        "min_cpk": min_cpk,
        "min_cpk_colonne": min_cpk_col,
    }


def portrait_verdict_from_metrics(
    specialist_results: list[dict],
    cfg: dict,
) -> tuple[str, str, dict, str]:
    """
    Verdict layout portrait — indépendant des recommandations S6.
    1. % hors tol > 0 → NO-GO
    2. Cpk < 1,33 si disponible → NO-GO
    3. Sinon → GO
    """
    snap = portrait_metrics_snapshot(specialist_results)
    pct = snap.get("max_pct_hors_tol")
    min_cpk = snap.get("min_cpk")

    no_go = False
    if pct is not None and float(pct) > 0:
        no_go = True
    if min_cpk is not None and float(min_cpk) < 1.33:
        no_go = True

    if no_go:
        key = "NO_GO"
        if min_cpk is not None and float(min_cpk) < 1.0:
            prio = "P1"
        elif pct is not None and float(pct) > 10:
            prio = "P1"
        else:
            prio = "P2"
    else:
        key = "GO"
        prio = "P4"

    return key, verdict_label(prio if no_go else "P4", cfg), verdict_banner(key, cfg), prio


def build_portrait_variables(specialist_results: list[dict]) -> list[dict]:
    """Une fiche par variable — descriptive + normalité + loi (sans jargon agent)."""
    cards: dict[str, dict[str, Any]] = {}

    def _card(col: str) -> dict[str, Any]:
        return cards.setdefault(
            col,
            {
                "variable": col,
                "n": None,
                "moyenne": None,
                "mediane": None,
                "ecart_type": None,
                "min": None,
                "max": None,
                "q1": None,
                "q3": None,
                "skewness": None,
                "kurtosis": None,
                "pct_sous_lti": None,
                "pct_au_dessus_lts": None,
                "pct_hors_tol": None,
                "cp": None,
                "cpk": None,
                "cpk_adj": None,
                "cpk_adj_label": "",
                "lti": None,
                "lts": None,
                "loi_id": "",
                "loi_params": {},
                "ic95_label": None,
                "iqr": None,
                "cv_pct": None,
                "nb_outliers": None,
                "p5": None,
                "p95": None,
                "verdict_normalite": "",
                "loi_retenue": "",
            },
        )

    for item in specialist_results:
        if item.get("status") != "success":
            continue
        agent = _canonical_s3_agent(item.get("agent"))
        res = item.get("result") or {}
        if not isinstance(res, dict):
            continue
        col = str(res.get("colonne") or "").strip()
        if not col:
            continue
        card = _card(col)
        if agent == "descriptive":
            card["n"] = res.get("n")
            card["moyenne"] = res.get("moyenne")
            card["mediane"] = res.get("mediane")
            card["ecart_type"] = res.get("ecart_type")
            card["min"] = res.get("min")
            card["max"] = res.get("max")
            card["q1"] = res.get("q1")
            card["q3"] = res.get("q3")
            card["skewness"] = res.get("skewness")
            card["kurtosis"] = res.get("kurtosis")
            card["pct_sous_lti"] = res.get("pct_sous_lti")
            card["pct_au_dessus_lts"] = res.get("pct_au_dessus_lts")
            card["pct_hors_tol"] = res.get("pct_hors_lti_lts")
            card["lti"] = res.get("lti")
            card["lts"] = res.get("lts")
            card["ic95_label"] = res.get("ic95_label")
            card["iqr"] = res.get("iqr")
            card["cv_pct"] = res.get("cv_pct")
            card["nb_outliers"] = res.get("nb_outliers")
            card["p5"] = res.get("p5")
            card["p95"] = res.get("p95")
        elif agent == "normality":
            card["verdict_normalite"] = normality_client_verdict(res.get("verdict_normalite"))
        elif agent == "distribution_fit":
            loi = res.get("loi_retenue") or res.get("loi_candidate_aic")
            card["loi_id"] = str(loi or "")
            card["loi_params"] = dict(res.get("parametres") or {})
            card["loi_retenue"] = client_loi_retenue_phrase(loi)
        elif agent == "cp_cpk":
            card["cpk"] = res.get("Cpk", res.get("cpk"))
            card["cp"] = res.get("Cp", res.get("cp"))

    from systems.stats.portrait_metrics import compute_adjusted_cpk

    out: list[dict] = []
    for col, card in cards.items():
        loi_id = str(card.get("loi_id") or "")
        lti, lts = card.get("lti"), card.get("lts")
        if (
            loi_id
            and loi_id != "normale"
            and lti is not None
            and lts is not None
            and float(lts) > float(lti)
        ):
            cpk_adj, cpk_lbl = compute_adjusted_cpk(
                float(lti), float(lts), loi_id, card.get("loi_params") or {}
            )
            if cpk_adj is not None:
                card["cpk_adj"] = cpk_adj
                card["cpk_adj_label"] = cpk_lbl

        rows = [
            ["Effectif (n)", _fmt_num(card.get("n"), 0)],
            ["Moyenne", _fmt_num(card.get("moyenne"))],
            ["Médiane", _fmt_num(card.get("mediane"))],
            ["Écart-type", _fmt_num(card.get("ecart_type"))],
            ["IC 95 % (moyenne)", str(card.get("ic95_label") or "N/A")],
            ["Min", _fmt_num(card.get("min"))],
            ["Max", _fmt_num(card.get("max"))],
            ["Q1", _fmt_num(card.get("q1"))],
            ["Q3", _fmt_num(card.get("q3"))],
            ["IQR", _fmt_num(card.get("iqr"))],
            ["Asymétrie", _fmt_num(card.get("skewness"))],
            ["Aplatissement", _fmt_num(card.get("kurtosis"))],
            ["CV %", _pct_cell(card.get("cv_pct")) if card.get("cv_pct") is not None else "N/A"],
            [
                "Valeurs aberrantes",
                _fmt_num(card.get("nb_outliers"), 0)
                if card.get("nb_outliers") is not None
                else "N/A",
            ],
            ["P5", _fmt_num(card.get("p5"))],
            ["P95", _fmt_num(card.get("p95"))],
            ["% sous LTI", _pct_cell(card.get("pct_sous_lti"))],
            ["% au-dessus LTS", _pct_cell(card.get("pct_au_dessus_lts"))],
            ["% hors tolérances", _pct_cell(card.get("pct_hors_tol"))],
        ]
        if card.get("cp") is not None:
            rows.append(["Cp", _fmt_num(card.get("cp"))])
        if card.get("cpk") is not None:
            rows.append(["Cpk", _fmt_num(card.get("cpk"))])
        if card.get("cpk_adj") is not None:
            lbl = str(card.get("cpk_adj_label") or "Cpk (ajusté)")
            rows.append([lbl, _fmt_num(card.get("cpk_adj"))])
        out.append(
            {
                "variable": col,
                "columns": ["Indicateur", "Valeur"],
                "rows": rows,
                "verdict_normalite": card.get("verdict_normalite") or "",
                "loi_retenue": card.get("loi_retenue") or "",
                "pct_hors_tol": card.get("pct_hors_tol"),
            }
        )
    return out


def filter_cpk_tables(tables: list[dict]) -> list[dict]:
    return [
        t
        for t in tables
        if "capabilit" in str(t.get("title", "")).lower()
        or "cpk" in str(t.get("title", "")).lower()
    ]


def should_include_facteurs(intent: dict) -> bool:
    intention = str(intent.get("intention") or "").strip().lower()
    if intention == "diagnostic_causal":
        return True
    gb = intent.get("group_by")
    if isinstance(gb, list):
        return bool(gb)
    return bool(gb)


def build_facteurs_block(
    intent: dict,
    s3_output: dict,
    metric_tables: list[dict],
    specialist_results: list[dict],
    dunn_annexe: list[dict],
) -> dict | None:
    """Facteurs influents — langage d'association (PHILOSOPHY §28)."""
    if not should_include_facteurs(intent):
        return None

    from systems.s5.prep import friendly_group_label

    tables: list[dict] = []
    for t in metric_tables:
        title = str(t.get("title", "")).lower()
        if "comparaison" in title or "anova" in title or "kruskal" in title:
            tables.append(t)

    ranking = _group_ranking_from_s3(s3_output)

    group_rows: list[list[str]] = []
    pivot = ranking.get("variable_pivot") or ranking.get("variable")
    pire = ranking.get("pire_groupe")
    if pire:
        group_rows.append(
            [
                str(pire),
                str(pivot or "—"),
                "Groupe le plus défavorable (classement certifié)",
            ]
        )

    dunn_lines: list[str] = []
    for item in dunn_annexe:
        txt = str(item.get("text") or "").strip()
        if txt:
            dunn_lines.append(txt)
    for item in specialist_results:
        if _canonical_s3_agent(item.get("agent")) != "dunn_posthoc":
            continue
        if item.get("status") != "success":
            continue
        for pair in (item.get("result") or {}).get("paires_significatives") or []:
            if not isinstance(pair, dict):
                continue
            ga = pair.get("groupe_a", "")
            gb = pair.get("groupe_b", "")
            p_disp = pair.get("p_value_display") or format_p_value(pair.get("p_value"))
            if ga and gb:
                dunn_lines.append(
                    f"{ga} vs {gb} : {p_disp} — écart associé entre groupes"
                )

    if group_rows:
        tables.insert(
            0,
            {
                "title": "Classement des groupes",
                "columns": ["Groupe", "Variable", "Note"],
                "rows": group_rows,
            },
        )

    if not tables and not dunn_lines and not group_rows:
        return None

    gb_label = friendly_group_label(intent.get("group_by"), intent)
    intro = (
        f"Les écarts observés entre {gb_label} sont associés à la variable analysée ; "
        "ils n'établissent pas une causalité directe."
    )
    return {
        "intro": intro,
        "tables": tables,
        "dunn_summary": dunn_lines[:6],
    }


def filter_graphs_complet(intent: dict, graphs: list[dict], cfg: dict) -> list[dict]:
    """Histogrammes (portrait) ou boxplots (comparaison / causal) — plafond YAML."""
    max_n = max_graphiques_complet(cfg)
    if not graphs:
        return []
    intention = str(intent.get("intention") or "").strip().lower()

    def _blob(g: dict) -> str:
        return " ".join(str(g.get(k, "")) for k in ("title", "type", "description", "variable")).lower()

    if intention == "portrait_statistique":
        preferred = []
        for ctype in ("histogram", "boxplot", "qqplot"):
            preferred.extend(g for g in graphs if ctype in _blob(g))
    elif intention == "analyse_complete" and not intent.get("group_by"):
        preferred = [g for g in graphs if "histogram" in _blob(g) or "qqplot" in _blob(g)]
    elif intention in ("diagnostic_causal", "comparaison_groupes", "analyse_complete"):
        preferred = [g for g in graphs if "boxplot" in _blob(g)]
    else:
        preferred = list(graphs)
    pool = preferred if preferred else list(graphs)
    return pool[:max_n]


def verdict_bullets_complet(
    specialist_results: list[dict],
    recommandations: list[dict],
    intent: dict,
    s3_output: dict,
) -> list[str]:
    """Verdict portrait : % hors tol, Cpk, normalité ou facteur."""
    snap = portrait_metrics_snapshot(specialist_results)
    bullets: list[str] = []
    pct = snap.get("max_pct_hors_tol")
    if pct is not None:
        bullets.append(f"Mesures hors tolérances : {pct} % (max.)")
    min_v, min_col = min_cpk_details(specialist_results)
    if min_v is not None:
        bullets.append(f"Indice de capabilité minimum : {min_v} ({min_col or 'variable'})")
    elif not bullets:
        for card in build_portrait_variables(specialist_results):
            vn = card.get("verdict_normalite")
            if vn:
                bullets.append(f"Normalité ({card['variable']}) : {vn}")
                break
    if should_include_facteurs(intent):
        from systems.s5.prep import friendly_group_label

        ranking = _group_ranking_from_s3(s3_output)
        pire = ranking.get("pire_groupe")
        if pire:
            bullets.append(f"Groupe le plus défavorable : {pire}")
        else:
            bullets.append(
                f"Analyse par {friendly_group_label(intent.get('group_by'), intent)}"
            )
    delai_p1 = "—"
    for rec in recommandations:
        if str(rec.get("priorite", "")).upper() == "P1":
            delai_p1 = str(rec.get("delai", "immédiat"))
            break
    bullets.append(f"Délai action P1 : {delai_p1}")
    return bullets[:3]


def map_chart_interpretations(interpretations: list[dict]) -> dict[str, str]:
    """Texte d'interprétation S5 indexé par chart_id."""
    out: dict[str, str] = {}
    for it in interpretations or []:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("chart_id") or "").strip()
        if not cid:
            continue
        text = str(it.get("texte") or it.get("text") or "").strip()
        if text:
            out[cid] = text
    return out


def portrait_chart_text_for_render(
    chart: dict,
    specialist_results: list[dict],
    intent: dict,
    context: "ClientContext",
    interp_by_id: dict[str, str],
) -> str:
    """
    Interprétation sous graphique (portrait) — S5 LLM si dispo, sinon repli Python certifié.
    """
    from systems.s5 import prep as s5_prep

    cid = str(chart.get("id") or "").strip()
    raw = interp_by_id.get(cid, "")
    cleaned = chart_interpretation_for_pdf(raw)
    if cleaned:
        return cleaned

    ctype = str(chart.get("type") or "histogram").lower()
    variable = str(chart.get("variable") or "").strip()
    if not variable:
        return ""
    facts = s5_prep.portrait_chart_facts_block(
        ctype, variable, specialist_results, intent, context
    )
    fallback = s5_prep.portrait_chart_fallback(ctype, variable, facts)
    return chart_interpretation_for_pdf(
        s5_prep.finalize_chart_interpretation(fallback)
    )


def portrait_escalate_recommendations(
    recommandations: list[dict],
    specialist_results: list[dict],
    intent: dict,
    verdict_key: str,
    *,
    responsable: str = "qualité",
) -> list[dict]:
    """NO-GO portrait → P1 immédiat sur % hors tol (remplace P4 surveillance seule)."""
    if str(verdict_key).upper() not in ("NO_GO", "NO_GO_OPERATIONNEL"):
        return recommandations
    snap = portrait_metrics_snapshot(specialist_results)
    pct = snap.get("max_pct_hors_tol")
    if pct is None or float(pct) <= 0:
        return recommandations
    variables = intent.get("variables") or []
    var = str(variables[0]) if variables else "la variable analysée"
    pct_txt = _fmt_num(pct, 1)
    action = (
        f"Investiguer les {pct_txt} % de mesures hors tolérances sur {var} "
        "(priorité immédiate)."
    )
    p1 = {
        "priorite": "P1",
        "action": action,
        "responsable": responsable,
        "delai": "immédiat",
        "justification": f"Processus hors tolérances ({pct_txt} %).",
    }
    rest = [
        r
        for r in recommandations
        if str(r.get("priorite", "")).upper() != "P4"
        or "surveillance standard" not in str(r.get("action", "")).lower()
    ]
    if any(str(r.get("priorite", "")).upper() == "P1" for r in rest):
        return [p1] + [r for r in rest if str(r.get("priorite")).upper() != "P1"][:3]
    return [p1] + rest[:3]


def report_reference(timestamp_iso: str, cfg: dict) -> str:
    prefix = str(cfg.get("reference_prefix", "RPT"))
    raw = str(timestamp_iso or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        dt = datetime.now(timezone.utc)
    return f"{prefix}-{dt.strftime('%Y%m%d-%H%M%S')}"


def verdict_banner(verdict_key: str, cfg: dict) -> dict:
    bandeaux = cfg.get("verdict_bandeaux", {})
    entry = bandeaux.get(verdict_key, bandeaux.get("NO_GO", {}))
    return {
        "text": str(entry.get("libelle", verdict_key)),
        "bg": str(entry.get("fond", "#C62828")),
        "fg": str(entry.get("texte", "#FFFFFF")),
    }


def synthesis_contradicts_cpk(synthese: str, min_cpk: float | None) -> bool:
    if min_cpk is None or min_cpk >= 1.33:
        return False
    return any(p.search(synthese or "") for p in _CONTRA_EN9100)


def strip_client_synthesis(text: str, min_cpk: float | None = None) -> str:
    from systems.s5.prep import polish_client_text

    out = str(text or "")
    for pat in _CLIENT_STRIP_PATTERNS:
        out = pat.sub("", out)
    if min_cpk is not None and min_cpk < 1.33:
        for pat in _CONTRA_EN9100:
            out = pat.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,;])", r"\1", out)
    out = re.sub(r"\bLe\s+Le\b", "Le", out)
    out = re.sub(r"\s+,\s+", ", ", out)
    return polish_client_text(out)


def sanitize_client_visible(text: str) -> str:
    from systems.s5.prep import polish_client_text

    out = sanitize_text(text)
    out = re.sub(r"\bAIC\s*=\s*[-\d.,]+", "", out, flags=re.I)
    out = re.sub(r"\bBIC\s*=\s*[-\d.,]+", "", out, flags=re.I)
    out = re.sub(r"selon\s+AIC[^.]*\.?", "", out, flags=re.I)
    out = out.replace("Ref_Matrice", "matrice")
    out = re.sub(r"\bRef_Matrice\b", "matrice", out)
    out = re.sub(r"\bmatrice\s+matrice\b", "matrice", out, flags=re.I)
    for pat in _CLIENT_STRIP_PATTERNS:
        out = pat.sub("", out)
    return polish_client_text(re.sub(r"\s{2,}", " ", out).strip())


def filter_client_metric_tables(tables: list[dict]) -> list[dict]:
    """Masque le champ Intention (jargon interne) en mode client."""
    out: list[dict] = []
    for table in tables:
        t = dict(table)
        title = str(t.get("title", "")).lower()
        if "contexte" in title:
            rows = []
            for row in t.get("rows") or []:
                if not row:
                    continue
                label = str(row[0]).strip().lower()
                if label == "intention":
                    continue
                rows.append(row)
            t["rows"] = rows
        out.append(t)
    return out


def specialist_client_label(specialist: str) -> str:
    key = str(specialist or "").strip().lower()
    return _SPECIALIST_CLIENT_LABELS.get(key, "Analyse qualité")


def filter_priority_graphs(graphs: list[dict], cfg: dict) -> list[dict]:
    priority = list(cfg.get("boxplots_prioritaires") or [])
    max_n = int(cfg.get("max_graphiques_client", cfg.get("max_graphiques_directeur", 3)))
    if not graphs:
        return []
    if not priority:
        return graphs[:max_n]
    picked: list[dict] = []
    used: set[int] = set()
    for name in priority:
        for idx, g in enumerate(graphs):
            if idx in used or not isinstance(g, dict):
                continue
            blob = " ".join(
                str(g.get(k, ""))
                for k in ("title", "variable", "type", "description")
            )
            if name in blob:
                picked.append(g)
                used.add(idx)
                break
        if len(picked) >= max_n:
            break
    if not picked:
        return graphs[:max_n]
    return picked[:max_n]


def _parse_cpk_cell(cell: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(cell))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def cpk_row_background(cpk: float | None, cfg: dict) -> str | None:
    if cpk is None:
        return None
    rules = cfg.get("cpk_couleurs", {})
    crit = rules.get("critique", {})
    lim = rules.get("limite", {})
    conf = rules.get("conforme", {})
    if cpk < float(crit.get("max", 1.0)):
        return str(crit.get("fond", "#FFEBEE"))
    if cpk < float(lim.get("max", 1.33)):
        return str(lim.get("fond", "#FFF3E0"))
    if cpk >= float(conf.get("min", 1.33)):
        return str(conf.get("fond", "#E8F5E9"))
    return str(lim.get("fond", "#FFF3E0"))


def annotate_cpk_table_colors(tables: list[dict], cfg: dict) -> list[dict]:
    for table in tables:
        title = str(table.get("title", "")).lower()
        if "capabilit" not in title and "cpk" not in title:
            continue
        cols = [str(c).lower() for c in table.get("columns") or []]
        cpk_idx = next((i for i, c in enumerate(cols) if "cpk" in c), 1)
        backgrounds: list[str | None] = []
        for row in table.get("rows") or []:
            cell = row[cpk_idx] if cpk_idx < len(row) else ""
            backgrounds.append(cpk_row_background(_parse_cpk_cell(str(cell)), cfg))
        table["row_backgrounds"] = backgrounds
    return tables


def aggregate_cpk_interpretations(items: list[dict]) -> str:
    parts: list[str] = []
    for it in items:
        spec = str(it.get("specialist", "")).lower()
        if spec != "cp_cpk":
            continue
        text = str(it.get("text") or "").strip()
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return (
        "Synthèse capabilité : "
        + " ".join(parts[:3])
        + (f" (+{len(parts) - 3} autre(s) variable(s) — voir tableau Cpk)." if len(parts) > 3 else "")
    )


def min_cpk_details(specialist_results: list[dict]) -> tuple[float | None, str]:
    best_val: float | None = None
    best_col = ""
    for item in specialist_results:
        if item.get("status") != "success":
            continue
        res = item.get("result") or {}
        cpk = res.get("Cpk", res.get("cpk"))
        col = str(res.get("colonne", ""))
        if cpk is None:
            continue
        try:
            v = float(cpk)
        except (TypeError, ValueError):
            continue
        if best_val is None or v < best_val:
            best_val = v
            best_col = col
    return best_val, best_col


def _group_ranking_from_s3(s3_output: dict) -> dict:
    ranking = s3_output.get("group_ranking")
    if isinstance(ranking, dict) and ranking:
        return ranking
    ms = s3_output.get("metrics_summary")
    if isinstance(ms, dict):
        nested = ms.get("group_ranking")
        if isinstance(nested, dict) and nested:
            return nested
    return {}


def verdict_bullets(
    specialist_results: list[dict],
    recommandations: list[dict],
    intent: dict,
    s3_output: dict,
) -> list[str]:
    min_v, min_col = min_cpk_details(specialist_results)
    ranking = _group_ranking_from_s3(s3_output)
    matrice = ranking.get("pire_groupe") or intent.get("matrice") or "—"
    delai_p1 = "—"
    for rec in recommandations:
        if str(rec.get("priorite", "")).upper() == "P1":
            delai_p1 = str(rec.get("delai", "immédiat"))
            break
    bullets: list[str] = []
    if min_v is not None:
        bullets.append(f"Cpk minimum : {min_v} ({min_col or 'variable'})")
    bullets.append(f"Matrice prioritaire : {matrice}")
    bullets.append(f"Délai action P1 : {delai_p1}")
    return bullets[:3]


def cap_recommendations(recos: list[dict], max_n: int) -> list[dict]:
    p1 = [r for r in recos if str(r.get("priorite")).upper() == "P1"]
    rest = [r for r in recos if str(r.get("priorite")).upper() != "P1"]
    out = p1 + rest
    return out[:max_n]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def priority_rank(priorite: str) -> int:
    return _PRIORITY_ORDER.get(str(priorite).upper(), 9)


def priorite_max(recommandations: list[dict]) -> str:
    best = "P4"
    for rec in recommandations:
        p = str(rec.get("priorite", "P4")).upper()
        if _PRIORITY_ORDER.get(p, 9) < _PRIORITY_ORDER.get(best, 9):
            best = p
    return best


def verdict_key(priorite: str) -> str:
    p = priorite.upper()
    if p == "P1":
        return "NO_GO"
    if p == "P2":
        return "NO_GO_OPERATIONNEL"
    if p == "P3":
        return "SURVEILLANCE"
    return "GO"


def verdict_label(priorite: str, cfg: dict) -> str:
    key = verdict_key(priorite)
    libelles = cfg.get("verdict_libelles", {})
    return str(libelles.get(key, key))


def max_graphiques(profile: str, cfg: dict) -> int:
    key = f"max_graphiques_{profile}"
    if key in cfg:
        return int(cfg[key])
    if profile == "directeur":
        return int(cfg.get("max_graphiques_directeur", 3))
    return int(cfg.get("max_graphiques_technicien", 12))


def client_display_name(context: "ClientContext") -> str:
    client = context.raw.get("client", {})
    if isinstance(client, dict):
        return str(client.get("nom", client.get("name", "Client")))
    return "Client"


def interpretation_text(item: dict) -> str:
    """S5 utilise « texte » ; certains tests utilisent « text »."""
    return str(item.get("texte") or item.get("text") or "").strip()


def interpretation_fallback_from_s3(
    specialist: str,
    specialist_results: list[dict],
) -> str:
    """Texte Python certifié si l'interprétation LLM est inutilisable."""
    from systems.s5.prep import canonical_agent, python_fallback_interpretation

    target = canonical_agent(specialist)
    for item in specialist_results:
        if canonical_agent(item.get("agent")) != target:
            continue
        if item.get("status") != "success":
            continue
        return python_fallback_interpretation(item)
    return ""


def prepare_interpretation_text(
    item: dict,
    specialist_results: list[dict],
    profile: str,
    forbidden: list[str],
) -> str:
    """Nettoie, filtre profil ; repli S3 si méta LLM résiduel."""
    from systems.s5.prep import (
        looks_like_llm_meta_artifact,
        strip_llm_meta_from_interpretation,
    )

    raw = interpretation_text(item)
    cleaned = strip_llm_meta_from_interpretation(raw)
    spec = str(item.get("specialist", ""))
    if not cleaned or looks_like_llm_meta_artifact(cleaned):
        fallback = interpretation_fallback_from_s3(spec, specialist_results)
        if fallback:
            cleaned = fallback
    return apply_profile_text(sanitize_text(cleaned), profile, forbidden)


def is_meaningful_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return t.upper() not in ("N/A", "NA", "NONE", "—", "-")


def chart_interpretation_for_pdf(text: str) -> str:
    """Texte d'interprétation graphique prêt PDF — vide si absent ou N/A."""
    t = sanitize_text(str(text or ""))
    return t if is_meaningful_text(t) else ""


def sanitize_text(text: str, formatters_mod: Any | None = None) -> str:
    if formatters_mod is not None and hasattr(formatters_mod, "sanitize_for_pdf"):
        return formatters_mod.sanitize_for_pdf(text)
    s = str(text or "").replace("None", "N/A")
    return s.strip() or "N/A"


def apply_profile_text(text: str, profile: str, forbidden: list[str]) -> str:
    if not text:
        return ""
    out = text
    if profile == "operateur":
        for pattern, repl in _OPERATEUR_SUBSTITUTIONS:
            out = pattern.sub(repl, out)
    lowered = out.lower()
    for word in forbidden:
        w = str(word).strip().lower()
        if not w:
            continue
        out = re.sub(rf"\b{re.escape(w)}\b", "", out, flags=re.IGNORECASE)
        if w in lowered and profile == "operateur":
            out = re.sub(rf"{re.escape(w)}", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


def format_metric_row(agent: str, result: dict, profile: str) -> list[str]:
    agent_l = (agent or "").lower()
    if agent_l in ("cp_cpk", "cpcpk"):
        cpk = result.get("Cpk", result.get("cpk"))
        col = result.get("colonne", "")
        conf = result.get("conforme_EN9100")
        if profile == "operateur":
            status = "conforme" if conf else "hors tolérance"
            return [str(col or "mesure"), f"Capabilité : {status}"]
        return [
            str(col or "variable"),
            f"Cpk = {cpk}" if cpk is not None else "Cpk N/A",
            "Conforme EN9100" if conf else "Non conforme",
        ]
    if agent_l in ("anova_kruskal",):
        pval = result.get("p_value", result.get("p"))
        if profile == "operateur":
            sig = "différence notable" if pval is not None and float(pval) < 0.05 else "pas d'écart marqué"
            return ["Comparaison groupes", sig]
        return [
            "ANOVA / Kruskal",
            f"p = {pval}" if pval is not None else "p N/A",
            str(result.get("interpretation", result.get("significatif", ""))),
        ]
    parts = []
    for k, v in list(result.items())[:6]:
        if isinstance(v, (dict, list)):
            continue
        parts.append(f"{k}={v}")
    label = agent or "spécialiste"
    return [label, ", ".join(parts) if parts else "N/A"]


def build_metric_tables(
    s4_output: dict,
    specialist_results: list[dict],
    profile: str,
    forbidden: list[str],
    *,
    client_mode: bool = False,
) -> list[dict]:
    """Tableaux structurés (colonnes + lignes) — priorité aux tables S4."""
    tables: list[dict] = []
    for table in s4_output.get("tables") or []:
        if not isinstance(table, dict):
            continue
        cols = list(table.get("columns") or [])
        rows_in = list(table.get("rows") or [])
        if not cols or not rows_in:
            continue
        rows_out: list[list[str]] = []
        for row in rows_in:
            if not isinstance(row, (list, tuple)):
                continue
            cells = [
                apply_profile_text(sanitize_text(str(c)), profile, forbidden)
                for c in row
            ]
            rows_out.append(cells)
        if rows_out:
            tables.append(
                {
                    "title": sanitize_text(str(table.get("title", "Tableau"))),
                    "columns": [sanitize_text(str(c)) for c in cols],
                    "rows": rows_out,
                }
            )
    if tables:
        if client_mode:
            return filter_client_metric_tables(tables)
        return tables
    legacy_rows = specialist_rows(specialist_results, profile)
    if legacy_rows:
        max_cols = max(len(r) for r in legacy_rows)
        columns = ["Élément"] + [f"Valeur {i}" for i in range(1, max_cols)]
        return [{"title": "Synthèse métriques", "columns": columns, "rows": legacy_rows}]
    return []


def specialist_rows(
    specialist_results: list[dict],
    profile: str,
) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in specialist_results:
        if not isinstance(item, dict) or item.get("status") != "success":
            continue
        res = item.get("result") or {}
        if not isinstance(res, dict):
            continue
        rows.append(format_metric_row(str(item.get("agent", "")), res, profile))
    return rows


def min_cpk(specialist_results: list[dict]) -> float | None:
    vals: list[float] = []
    for item in specialist_results:
        if item.get("status") != "success":
            continue
        res = item.get("result") or {}
        if not isinstance(res, dict):
            continue
        cpk = res.get("Cpk", res.get("cpk"))
        if cpk is not None:
            try:
                vals.append(float(cpk))
            except (TypeError, ValueError):
                pass
    return min(vals) if vals else None


def is_graph_only_interpretation(item: dict) -> bool:
    text = str(item.get("text", "") or "").strip()
    spec = str(item.get("specialist", "") or "").lower()
    if spec in ("graphique", "graph", "chart"):
        return True
    return bool(_GRAPH_ONLY_RE.match(text))


def interpretation_badge(statut: str, *, client_mode: bool = False) -> str:
    if client_mode:
        return ""
    s = (statut or "").lower()
    if s == "reject":
        return "Données certifiées (écart LLM corrigé)"
    if s == "fallback":
        return "Synthèse automatique"
    return "Interprétation vérifiée"


def slug_piece_op(intent: dict) -> str:
    piece = str(intent.get("piece") or "PIECE")
    op = str(intent.get("operation") or "OP")
    safe = re.sub(r"[^\w\-]+", "_", f"{piece}_{op}")
    return safe.strip("_") or "rapport"
