"""
Formatage statistique open-core — p-values et libellés certifiés (zéro LLM).
"""

from __future__ import annotations

import math
import re
from typing import Any

_BAD_P_VALUE_PHRASES = [
    re.compile(r"p[- ]?value\s+d['']environ\s+0", re.I),
    re.compile(r"p\s*=\s*0[,.]000", re.I),
    re.compile(r"\benviron\s+0[,.]000\b", re.I),
    re.compile(r"\bp\s*=\s*0\b(?!\d)", re.I),
]


def format_p_value(p: Any) -> str:
    """
    Affichage rapport qualité :
    - p < 0,001 si p < 0.001
    - sinon p = X,XXX (3 décimales, virgule FR)
    """
    if p is None:
        return "N/A"
    try:
        if hasattr(p, "__float__") and math.isnan(float(p)):
            return "N/A"
    except (TypeError, ValueError):
        pass
    try:
        val = float(p)
    except (TypeError, ValueError):
        return "N/A"
    if math.isnan(val) or math.isinf(val):
        return "N/A"
    if val < 0.001:
        return "p < 0,001"
    formatted = f"{val:.3f}".replace(".", ",")
    return f"p = {formatted}"


def certified_significance_phrase(
    p_value: Any,
    significatif: bool | None,
    *,
    methode: str = "Kruskal-Wallis",
) -> str:
    """Libellé Python unique pour synthèse / R6 — le LLM ne reformule pas la p-value."""
    p_txt = format_p_value(p_value)
    if significatif:
        if p_txt == "p < 0,001":
            return f"différence hautement significative ({p_txt})"
        return f"différence significative entre les groupes ({methode}, {p_txt})"
    return f"aucune différence significative entre les groupes ({methode}, {p_txt})"


def enrich_specialist_results_display(specialist_results: list[dict]) -> list[dict]:
    """Ajoute champs d'affichage sans modifier les valeurs numériques brutes."""
    for item in specialist_results:
        if item.get("status") != "success":
            continue
        payload = item.get("result")
        if not isinstance(payload, dict):
            continue
        agent = str(item.get("agent", "")).lower()
        if "p_value" in payload:
            payload["p_value_display"] = format_p_value(payload["p_value"])
            if agent == "anova_kruskal":
                payload["significance_phrase"] = certified_significance_phrase(
                    payload["p_value"],
                    payload.get("significatif"),
                    methode=str(payload.get("methode_choisie", "Kruskal-Wallis")),
                )
        if agent == "normality" and "p_value" in payload:
            if "p_value_display" not in payload:
                payload["p_value_display"] = format_p_value(payload["p_value"])
        if agent == "dunn_posthoc":
            paires = payload.get("paires_significatives") or []
            for pair in paires:
                if isinstance(pair, dict) and "p_value" in pair:
                    pair["p_value_display"] = format_p_value(pair["p_value"])
                    paire_a = pair.get("groupe_a", "")
                    paire_b = pair.get("groupe_b", "")
                    p_disp = pair["p_value_display"]
                    pair["libelle"] = (
                        f"{paire_a} vs {paire_b} : {p_disp} — différence significative"
                    )
    return specialist_results


def strip_bad_p_value_phrases(text: str) -> str:
    """Retire formulations LLM interdites sur les p-values."""
    out = str(text or "")
    for pat in _BAD_P_VALUE_PHRASES:
        out = pat.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def assert_no_misleading_p_display(payload: dict) -> None:
    """Lève AssertionError si un champ d'affichage contient 0,0000 trompeur."""
    for key, val in payload.items():
        if not key.endswith("_display") and key not in ("libelle", "significance_phrase", "interpretation"):
            continue
        if isinstance(val, str) and re.search(r"0[,.]0000?", val):
            if "p <" not in val.lower():
                raise AssertionError(f"Affichage p-value trompeur : {key}={val!r}")
