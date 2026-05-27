"""
Pré-formatage S6 — lecture YAML, agents canoniques, profils.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_AGENT_ALIASES = {
    "CpCpkSpecialist": "cp_cpk",
    "AnovaKruskalSpecialist": "anova_kruskal",
    "MannKendallSpecialist": "mann_kendall",
    "ZScoreSpecialist": "zscore",
}

_PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}

_DEFAULT_RECO = {
    "seuils_cpk": {"p1_sous": 1.0, "p2_sous": 1.33, "p3_sous": 1.67},
    "zscore": {"absolu_p1": 3.0, "anomaly_pct_p1": 20.0, "anomaly_pct_p2": 10.0},
    "delais": {
        "P1": "immédiat",
        "P2": "48 heures",
        "P3": "semaine en cours",
        "P4": "surveillance standard",
    },
    "responsables_par_profil": {
        "operateur": "chef d'équipe",
        "technicien": "responsable qualité",
        "ingenieur": "direction technique",
        "directeur": "direction générale",
    },
    "regroupement_causes": [],
    "rag": {
        "min_relevance": 0.7,
        "message_vide": "Aucune procédure locale trouvée. Contacter l'ingénieur procédé.",
    },
    "detail_par_profil": {
        "technicien": {
            "inclure_priorites": ["P1", "P2", "P3", "P4"],
            "agreger_p2_p3": False,
        },
    },
}


def canonical_agent(agent: str | None) -> str:
    if not agent:
        return ""
    return _AGENT_ALIASES.get(agent, str(agent).strip().lower())


def reco_config(context: "ClientContext") -> dict:
    raw = context.get_recommandations()
    cfg = dict(_DEFAULT_RECO)
    for key, val in raw.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            merged = dict(cfg[key])
            merged.update(val)
            cfg[key] = merged
        else:
            cfg[key] = val
    return cfg


def responsable_for(context: "ClientContext", profile: str) -> str:
    cfg = reco_config(context)
    mapping = cfg.get("responsables_par_profil", {})
    return str(mapping.get(profile) or mapping.get("technicien", "responsable qualité"))


def delai_for(cfg: dict, priorite: str) -> str:
    delais = cfg.get("delais", {})
    return str(delais.get(priorite, "surveillance standard"))


def profile_config(context: "ClientContext", profile: str) -> dict:
    profils = context.profils or {}
    default = profils.get("technicien", {})
    cfg = profils.get(profile, default)
    return cfg if isinstance(cfg, dict) else default


def profile_detail_config(context: "ClientContext", profile: str) -> dict:
    cfg = reco_config(context)
    details = cfg.get("detail_par_profil", {})
    default = details.get("technicien", {"inclure_priorites": ["P1", "P2", "P3", "P4"], "agreger_p2_p3": False})
    row = details.get(profile, default)
    return row if isinstance(row, dict) else default


def priority_rank(priorite: str) -> int:
    return _PRIORITY_ORDER.get(priorite, 9)


def infer_cause_key(intent: dict, result: dict, cfg: dict) -> tuple[str, str]:
    """Retourne (cause_key, cause_label) pour regroupement P2/P3."""
    p = result.get("result") or {}
    agent = canonical_agent(result.get("agent"))
    colonne = str(p.get("colonne") or intent.get("group_by") or "processus")

    for rule in cfg.get("regroupement_causes", []):
        if not isinstance(rule, dict):
            continue
        col = rule.get("colonne")
        label = rule.get("label", col)
        gb = intent.get("group_by")
        if col and (gb == col or (isinstance(gb, list) and col in gb)):
            return f"{label}:{col}", f"{label} {col}"

    if agent == "anova_kruskal":
        gb = intent.get("group_by", "groupes")
        if isinstance(gb, list):
            gb = gb[0] if gb else "groupes"
        return f"comparaison:{gb}", f"comparaison {gb}"

    return f"variable:{colonne}", colonne


def strip_forbidden(text: str, forbidden: list[str]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    out = text
    for word in forbidden:
        w = str(word).lower()
        if re.search(rf"\b{re.escape(w)}\b", out, re.IGNORECASE):
            out = re.sub(rf"\b{re.escape(w)}\b", "", out, flags=re.IGNORECASE)
            warnings.append(f"Terme retiré (profil) : {word}")
    return re.sub(r"\s+", " ", out).strip(), warnings


def truncate_tokens(text: str, tokens_max: int) -> str:
    max_words = max(20, int(tokens_max * 0.75))
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"
