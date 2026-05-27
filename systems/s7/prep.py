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
    "max_graphiques_directeur": 3,
    "max_graphiques_technicien": 12,
    "max_graphiques_operateur": 8,
    "sauvegarder_dans": "reports/",
    "verdict_libelles": {
        "GO": "GO — Procédé sous contrôle",
        "NO_GO": "NO-GO — Action corrective requise",
        "NO_GO_OPERATIONNEL": "NO-GO opérationnel — Intervention urgente",
        "SURVEILLANCE": "SURVEILLANCE — Suivi renforcé",
    },
}

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
        if key == "verdict_libelles" and isinstance(val, dict):
            merged = dict(cfg["verdict_libelles"])
            merged.update(val)
            cfg["verdict_libelles"] = merged
        else:
            cfg[key] = val
    return cfg


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


def interpretation_badge(statut: str) -> str:
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
