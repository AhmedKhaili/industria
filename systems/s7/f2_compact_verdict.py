"""
P7-F2 compact — verdict prudent depuis le pire groupe fiable (seuils YAML).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from systems.s7 import prep
from systems.s7.f2_compact_selection import F2CompactSelection


@dataclass
class CompactVerdict:
    verdict_key: str
    label: str
    banner: dict[str, Any]
    rationale: str
    tone: str | None = None


def _seuils_cpk(context: Any) -> dict[str, float | None]:
    if context is None:
        return {}
    rec = context.get_recommandations()
    seuils = rec.get("seuils_cpk") if isinstance(rec, dict) else {}
    if not isinstance(seuils, dict):
        return {}
    out: dict[str, float | None] = {}
    for key in ("p1_sous", "p2_sous", "p3_sous"):
        raw = seuils.get(key)
        if raw is not None:
            try:
                out[key] = float(raw)
            except (TypeError, ValueError):
                out[key] = None
    return out


def _pct_p1_threshold(cfg: dict) -> float | None:
    compact = prep.f2_compact_config(cfg)
    for key in ("pct_hors_tol_p1", "pct_hors_tolerance_p1"):
        raw = compact.get(key)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    rec = cfg.get("recommandations") if isinstance(cfg.get("recommandations"), dict) else {}
    for key in ("pct_hors_tol_p1", "pct_hors_tolerance_p1"):
        raw = rec.get(key) if isinstance(rec, dict) else None
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    return None


def compute_compact_verdict(
    selection: F2CompactSelection,
    context: Any,
    cfg: dict,
) -> CompactVerdict:
    """
    NO-GO uniquement si seuils YAML le justifient clairement.
    Sinon SURVEILLANCE ou GO.
    """
    cfg = cfg or {}
    if selection.skipped_reason:
        key = "SURVEILLANCE"
        return CompactVerdict(
            verdict_key=key,
            label=_verdict_label(key, cfg),
            banner=prep.verdict_banner(key, cfg),
            rationale="données group_descriptive absentes",
            tone="point_attention",
        )

    if selection.degenerate:
        key = "SURVEILLANCE"
        return CompactVerdict(
            verdict_key=key,
            label=_verdict_label(key, cfg),
            banner=prep.verdict_banner(key, cfg),
            rationale="aucun groupe fiable après filtrage",
            tone="point_attention",
        )

    worst = selection.worst_reliable or {}
    seuils = _seuils_cpk(context)
    p1_cpk = seuils.get("p1_sous")
    p2_cpk = seuils.get("p2_sous")
    pct_p1 = _pct_p1_threshold(cfg)

    cpk_raw = worst.get("cpk")
    pct_raw = worst.get("out_of_tolerance_rate")
    cpk = float(cpk_raw) if cpk_raw is not None else None
    pct = float(pct_raw) if pct_raw is not None else None

    no_go_reasons: list[str] = []
    if cpk is not None and p1_cpk is not None and cpk < p1_cpk:
        no_go_reasons.append(f"Cpk {cpk:.2f} < seuil P1 ({p1_cpk:.2f})")
    if pct is not None and pct_p1 is not None and pct > pct_p1:
        no_go_reasons.append(f"% HT {pct:.1f} > seuil P1 ({pct_p1:.1f})")

    if no_go_reasons:
        key = "NO_GO"
        return CompactVerdict(
            verdict_key=key,
            label=_verdict_label(key, cfg),
            banner=prep.verdict_banner(key, cfg),
            rationale=" ; ".join(no_go_reasons),
        )

    surveillance_reasons: list[str] = []
    if cpk is not None and p2_cpk is not None and cpk < p2_cpk:
        surveillance_reasons.append(f"Cpk {cpk:.2f} sous le seuil de surveillance ({p2_cpk:.2f})")
    if pct is not None and pct > 0:
        surveillance_reasons.append(f"% HT {pct:.1f} > 0")
    sev = str(worst.get("severity_label") or "").lower()
    if sev in ("critique", "surveillance"):
        surveillance_reasons.append(f"niveau {sev} sur le groupe prioritaire")

    if surveillance_reasons:
        key = "SURVEILLANCE"
        tone = "point_attention" if cpk is not None and p1_cpk is not None and cpk >= p1_cpk else None
        return CompactVerdict(
            verdict_key=key,
            label=_verdict_label(key, cfg),
            banner=prep.verdict_banner(key, cfg),
            rationale=" ; ".join(surveillance_reasons),
            tone=tone,
        )

    key = "GO"
    return CompactVerdict(
        verdict_key=key,
        label=_verdict_label(key, cfg),
        banner=prep.verdict_banner(key, cfg),
        rationale="indicateurs du pire groupe fiable dans les seuils configurés",
    )


def _verdict_label(key: str, cfg: dict) -> str:
    libelles = cfg.get("verdict_libelles") or {}
    if isinstance(libelles, dict) and libelles.get(key):
        return str(libelles[key])
    return key
