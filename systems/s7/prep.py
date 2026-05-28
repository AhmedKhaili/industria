"""
Pré-formatage S7 — verdict, profils, métriques (zéro LLM).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

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
    "max_recommandations_client": 4,
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


def verdict_bullets(
    specialist_results: list[dict],
    recommandations: list[dict],
    intent: dict,
    s3_output: dict,
) -> list[str]:
    min_v, min_col = min_cpk_details(specialist_results)
    ranking = s3_output.get("group_ranking") or {}
    if not ranking:
        ms = s3_output.get("metrics_summary") or {}
        ranking = ms.get("group_ranking") if isinstance(ms, dict) else {}
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
