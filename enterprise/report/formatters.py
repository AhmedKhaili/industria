"""Utilitaires de formatage pour les rapports PDF IndustrIA."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

import pandas as pd

_MAX_PDF_TEXT = 2000
_PRINTABLE_RE = re.compile(r"[^\x20-\x7E\u00A0-\u024F\u1E00-\u1EFF]")


def format_bool(b: Any) -> str:
    """True → Oui, False → Non, None → N/A."""
    if b is None:
        return "N/A"
    return "Oui" if bool(b) else "Non"


def format_number(n: Any, decimals: int = 2, unit: str = "") -> str:
    """Formate un nombre avec séparateur de milliers (espace) et unité optionnelle."""
    if n is None:
        return "N/A"
    try:
        if pd.isna(n):
            return "N/A"
    except (TypeError, ValueError):
        pass
    try:
        val = float(n)
    except (TypeError, ValueError):
        return "N/A"
    if math.isnan(val) or math.isinf(val):
        return "N/A"
    if decimals > 0:
        formatted = f"{val:,.{decimals}f}".replace(",", " ")
    else:
        formatted = f"{int(round(val)):,}".replace(",", " ")
    suffix = f" {unit.strip()}" if unit and unit.strip() else ""
    return f"{formatted}{suffix}"


def format_percentage(v: Any, decimals: int = 1) -> str:
    """0.173 → 17.3 %."""
    if v is None:
        return "N/A"
    try:
        if pd.isna(v):
            return "N/A"
    except (TypeError, ValueError):
        pass
    try:
        val = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if math.isnan(val):
        return "N/A"
    if abs(val) <= 1.0:
        val *= 100.0
    return f"{val:.{decimals}f} %"


def format_timestamp(ts: Any) -> str:
    """datetime / str / timestamp → JJ/MM/AAAA HH:MM:SS."""
    if ts is None:
        return "N/A"
    try:
        if pd.isna(ts):
            return "N/A"
    except (TypeError, ValueError):
        pass
    if isinstance(ts, datetime):
        return ts.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime().strftime("%d/%m/%Y %H:%M:%S")
    try:
        parsed = pd.to_datetime(ts, errors="coerce")
        if pd.isna(parsed):
            return "N/A"
        return parsed.to_pydatetime().strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return "N/A"


def format_duration(seconds: Any) -> str:
    """3661 → 1h 01min ; 90 → 1min 30s."""
    if seconds is None:
        return "N/A"
    try:
        if pd.isna(seconds):
            return "N/A"
    except (TypeError, ValueError):
        pass
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "N/A"
    if total < 0:
        return "N/A"
    if total >= 3600:
        h, rem = divmod(total, 3600)
        m = rem // 60
        return f"{h}h {m:02d}min"
    if total >= 60:
        m, s = divmod(total, 60)
        return f"{m}min {s:02d}s"
    return f"{total}s"


def format_priority(p: str) -> str:
    """Libellé priorité ISA-18.2 (sans emoji — compatible PDF ReportLab)."""
    mapping = {
        "P1": "P1 — Critique",
        "P2": "P2 — Urgent",
        "P3": "P3 — Surveillance",
        "P4": "P4 — Information",
    }
    return mapping.get(str(p).upper() if p else "", "Inconnu")


def format_dict(d: dict) -> str:
    """Formate un dict métier en texte lisible (jamais repr Python)."""
    if not d:
        return "N/A"
    if "direction" in d and "slope" in d:
        slope = d.get("slope", 0)
        try:
            slope_f = float(slope)
            return f"{d['direction']} (pente={slope_f:.2f})"
        except (TypeError, ValueError):
            return f"{d['direction']} (pente={slope})"
    if "trend" in d and "p" in d:
        try:
            p_f = float(d["p"])
            return f"{d['trend']} (p={p_f:.2f})"
        except (TypeError, ValueError):
            return f"{d['trend']} (p={d['p']})"
    parts = []
    for key, val in d.items():
        if isinstance(val, dict):
            parts.append(f"{key}={format_dict(val)}")
        elif isinstance(val, list):
            parts.append(f"{key}={format_list(val)}")
        elif isinstance(val, bool):
            parts.append(f"{key}={format_bool(val)}")
        elif isinstance(val, float):
            parts.append(f"{key}={format_number(val, decimals=4)}")
        else:
            parts.append(f"{key}={format_value(val)}")
    return ", ".join(parts)


def format_list(items: list, max_items: int = 3) -> str:
    """Formate une liste pour affichage PDF."""
    if not items:
        return "Aucun"
    formatted = [format_value(x) for x in items[:max_items]]
    if len(items) == 1:
        return formatted[0]
    if len(items) <= max_items:
        return ", ".join(formatted)
    extra = len(items) - max_items
    label = "autre" if extra == 1 else "autres"
    return f"{', '.join(formatted)} (+{extra} {label})"


def format_value(v: Any) -> str:
    """Point d'entrée : aucune sortie None, dict ou list brute."""
    if v is None:
        return "N/A"
    try:
        if pd.isna(v):
            return "N/A"
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return format_bool(v)
    if isinstance(v, dict):
        return format_dict(v)
    if isinstance(v, list):
        return format_list(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return "N/A"
        rounded = round(v, 4)
        text = f"{rounded:.4f}".rstrip("0").rstrip(".")
        return text if text else "0"
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, (datetime, pd.Timestamp)):
        return format_timestamp(v)
    return str(v).strip() if v is not None else "N/A"


def sanitize_for_pdf(text: str) -> str:
    """Nettoie le texte LLM pour insertion PDF sûre."""
    if text is None:
        return "N/A"
    s = str(text)
    s = _PRINTABLE_RE.sub("", s)
    s = s.replace("None", "N/A")
    # Remplacements grossiers de structures Python résiduelles
    s = re.sub(r"\{[^}]{0,200}\}", lambda m: format_dict(_safe_literal_dict(m.group(0))), s)
    if len(s) > _MAX_PDF_TEXT:
        s = s[: _MAX_PDF_TEXT - 3] + "..."
    return s.strip() or "N/A"


def _safe_literal_dict(fragment: str) -> dict:
    """Tente d'interpréter un fragment dict ; sinon retourne vide."""
    try:
        import ast

        parsed = ast.literal_eval(fragment)
        if isinstance(parsed, dict):
            return parsed
    except (SyntaxError, ValueError):
        pass
    return {}
