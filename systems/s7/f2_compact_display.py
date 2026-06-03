"""
P7-F2 compact — libellés et formats PDF (D4, sans calcul).
"""

from __future__ import annotations

import re
from typing import Any

from systems.s7.f2_templates import severity_display

_MATRIX_CODE_RE = re.compile(r"^O\d{7}[A-Z0-9\-]*$", re.IGNORECASE)

_EXCLUSION_DETAIL_CLIENT = {
    "pattern_yaml_non_respecte": (
        "Valeur non conforme au format attendu des matrices"
    ),
    "groupe_parasite": "Groupe exclu de l'analyse (liste de retrait configurée)",
}


def compact_report_title(variable_label: str, factor_label: str) -> str:
    """Titre métier page de garde (question technique conservée à part)."""
    var = (variable_label or "").strip()
    fac = (factor_label or "").strip()
    if not var:
        return "Synthèse métier comparative"
    fac_part = fac.lower() if fac else "le facteur analysé"
    if fac and "matrice" in fac.lower():
        return f"Comparaison du {var} selon la {fac_part}"
    if fac:
        return f"Comparaison du {var} selon {fac_part}"
    return f"Comparaison du {var}"


def compact_verdict_allows_critique(verdict_key: str) -> bool:
    return str(verdict_key or "").upper() in ("NO_GO", "NO_GO_OPERATIONNEL")


def compact_level_display(severity_label: str | None, *, verdict_key: str) -> str:
    """Niveau tableau : « Critique » uniquement si seuils P1 franchis (NO-GO)."""
    sev = str(severity_label or "").lower()
    if sev == "critique":
        if compact_verdict_allows_critique(verdict_key):
            return "Critique"
        return "Prioritaire"
    if sev == "surveillance":
        return "Surveillance renforcée"
    if sev == "favorable":
        return "Favorable"
    if not sev:
        return "—"
    disp = severity_display(severity_label)
    if disp == "Critique" and not compact_verdict_allows_critique(verdict_key):
        return "Prioritaire"
    return disp


def priority_entity_label(factor_label: str) -> str:
    if "matrice" in str(factor_label or "").lower():
        return "Matrice prioritaire"
    return "Groupe prioritaire"


def favorable_indicator_label(favorable_strength: str) -> str:
    strength = str(favorable_strength or "none").lower()
    if strength == "limited":
        return "Référence favorable à confirmer"
    if strength == "robust":
        return "Référence favorable la plus robuste"
    return "Groupe le plus favorable"


def exclusion_detail_client(reason: str, detail: str | None) -> str:
    if reason in _EXCLUSION_DETAIL_CLIENT:
        return _EXCLUSION_DETAIL_CLIENT[reason]
    raw = str(detail or "").strip()
    if reason == "effectif_insuffisant" and raw:
        return raw
    if reason == "valeur_manquante":
        return "Valeur manquante ou non exploitable"
    if raw.lower().startswith("pattern:") or raw.lower().startswith("denylist:"):
        return _EXCLUSION_DETAIL_CLIENT.get(
            reason, "Groupe non retenu pour l'analyse"
        )
    return raw or "—"


def looks_like_matrix_group_code(text: str) -> bool:
    return bool(_MATRIX_CODE_RE.match(str(text or "").strip()))


def _fmt_num(value: Any, decimals: int = 3) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
        if abs(v) < 10 ** -(decimals + 1):
            v = 0.0
        return f"{v:.{decimals}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
        if abs(v) < 0.05:
            v = 0.0
        return f"{v:.1f} %".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _fmt_ci95_pct_value(value: float) -> str:
    v = float(value)
    if abs(v) < 5e-3:
        v = 0.0
    return f"{v:.2f} %".replace(".", ",")


def format_ci95_interval(
    low: Any,
    high: Any,
    *,
    as_percent: bool = False,
) -> str:
    try:
        lo = float(low)
        hi = float(high)
    except (TypeError, ValueError):
        return "IC95 non disponible"
    if as_percent:
        return f"[{_fmt_ci95_pct_value(lo)} ; {_fmt_ci95_pct_value(hi)}]"
    return f"[{_fmt_num(lo, 3)} ; {_fmt_num(hi, 3)}]"


def ci95_display(ci: Any, *, as_percent: bool = False) -> str:
    if not isinstance(ci, dict):
        return "IC95 non disponible"
    low, high = ci.get("low"), ci.get("high")
    if low is not None and high is not None:
        return format_ci95_interval(low, high, as_percent=as_percent)
    label = str(ci.get("label") or "").strip()
    if label:
        return _normalize_ci95_label(label)
    return "IC95 non disponible"


def _normalize_ci95_label(label: str) -> str:
    out = label.replace("-0,0 %", "0,00 %").replace("-0.0 %", "0,00 %")
    out = out.replace("LTI–LTS", "LTI/LTS").replace("LTI-LTS", "LTI/LTS")
    return out
