"""
P7-F2 compact — C1 sélection / filtrage group_descriptive (présentation uniquement).

Zéro LLM, zéro recalcul statistique, zéro PDF.
Lit group_descriptive S3, warnings, seuils et filtres YAML.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from systems.s7.f2_report_blocks import (
    extract_group_descriptive_list,
    select_group_descriptive_blocks,
)

ExclusionReason = Literal[
    "effectif_insuffisant",
    "valeur_manquante",
    "pattern_yaml_non_respecte",
    "groupe_parasite",
    "warning_s3_autre",
]

FavorableStrength = Literal["robust", "limited", "none"]

_EFFECTIF_FAIBLE_RE = re.compile(r"effectif_faible_n_\d+_inferieur_(\d+)")


@dataclass
class ExcludedGroupRow:
    group_value: str
    n: int | None
    exclusion_reason: ExclusionReason
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class F2CompactSelection:
    variable: str
    group_by: str
    level: str
    aggregation_meta: dict[str, Any]
    block_selection: dict[str, Any]
    thresholds_used: dict[str, Any]
    rows_reliable: list[dict[str, Any]] = field(default_factory=list)
    rows_excluded: list[ExcludedGroupRow] = field(default_factory=list)
    worst_reliable: dict[str, Any] | None = None
    best_reliable: dict[str, Any] | None = None
    worst_group_s3: str | None = None
    best_group_s3: str | None = None
    worst_group_s3_ignored: str | None = None
    best_group_s3_ignored: str | None = None
    favorable_strength: FavorableStrength = "none"
    selection_meta: dict[str, Any] = field(default_factory=dict)
    skipped_reason: str | None = None
    high_cardinality_active: bool = False
    rows_display: list[dict[str, Any]] = field(default_factory=list)
    high_cardinality: dict[str, Any] = field(default_factory=dict)

    @property
    def degenerate(self) -> bool:
        return not self.skipped_reason and not self.rows_reliable

    @property
    def rows_for_display(self) -> list[dict[str, Any]]:
        if self.high_cardinality_active and self.rows_display:
            return list(self.rows_display)
        return list(self.rows_reliable)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rows_excluded"] = [r.to_dict() for r in self.rows_excluded]
        payload["degenerate"] = self.degenerate
        return payload


def build_f2_compact_selection(
    s3_output: dict,
    intent: dict,
    context: Any = None,
    cfg: dict | None = None,
) -> F2CompactSelection:
    """
    Partitionne les rows group_descriptive en fiables / exclus pour le rapport F2 compact.
    """
    cfg = cfg or {}
    compact_cfg = dict(cfg.get("f2_compact") or {})

    variable = _resolve_variable(intent, s3_output)
    blocks_list = extract_group_descriptive_list(s3_output)
    if not blocks_list:
        return F2CompactSelection(
            variable=variable or "",
            group_by=_resolve_group_by(intent, {}),
            level="",
            aggregation_meta={},
            block_selection={},
            thresholds_used={},
            skipped_reason="no_group_descriptive",
        )

    primary, _measure_annex, block_selection = select_group_descriptive_blocks(
        blocks_list, variable
    )
    if primary is None:
        return F2CompactSelection(
            variable=variable or "",
            group_by=_resolve_group_by(intent, {}),
            level="",
            aggregation_meta={},
            block_selection=block_selection,
            thresholds_used={},
            skipped_reason="no_group_descriptive",
        )

    variable = str(primary.get("variable") or variable or "")
    group_by = str(primary.get("group_by") or _resolve_group_by(intent, primary))
    level = str(primary.get("level") or "")
    aggregation_meta = dict(primary.get("aggregation") or {})
    rows = list(primary.get("rows") or [])

    factor_cfg = _find_factor_config(context, group_by)
    pattern, pattern_source = _resolve_group_pattern(factor_cfg, compact_cfg)
    denylist = _resolve_denylist(factor_cfg, compact_cfg)
    min_n, min_n_source = _resolve_min_n_threshold(
        level, aggregation_meta, compact_cfg, context, rows
    )

    thresholds_used: dict[str, Any] = {
        "min_n": min_n,
        "min_n_source": min_n_source,
        "group_value_pattern": pattern,
        "pattern_source": pattern_source,
        "denylist_count": len(denylist),
        "denylist_source": _denylist_source(factor_cfg, compact_cfg, denylist),
    }

    pattern_re = re.compile(pattern) if pattern else None
    reliable: list[dict[str, Any]] = []
    excluded: list[ExcludedGroupRow] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        reason_detail = _classify_exclusion(
            row,
            min_n=min_n,
            denylist=denylist,
            pattern_re=pattern_re,
        )
        if reason_detail is None:
            reliable.append(dict(row))
        else:
            reason, detail = reason_detail
            excluded.append(
                ExcludedGroupRow(
                    group_value=str(row.get("group_value", "")),
                    n=_row_n(row),
                    exclusion_reason=reason,
                    detail=detail,
                )
            )

    reliable.sort(key=lambda r: int(r.get("rank") or 999))
    worst_reliable = reliable[0] if reliable else None
    best_reliable, favorable_strength = _select_favorable_reference(
        reliable,
        worst_reliable,
        min_n=min_n,
        compact_cfg=compact_cfg,
    )

    worst_s3 = primary.get("worst_group")
    best_s3 = primary.get("best_group")
    worst_s3_str = str(worst_s3) if worst_s3 is not None else None
    best_s3_str = str(best_s3) if best_s3 is not None else None
    reliable_values = {str(r.get("group_value", "")) for r in reliable}

    worst_ignored = (
        worst_s3_str
        if worst_s3_str and worst_s3_str not in reliable_values
        else None
    )
    best_ignored = (
        best_s3_str if best_s3_str and best_s3_str not in reliable_values else None
    )

    return F2CompactSelection(
        variable=variable,
        group_by=group_by,
        level=level,
        aggregation_meta=aggregation_meta,
        block_selection=block_selection,
        thresholds_used=thresholds_used,
        rows_reliable=reliable,
        rows_excluded=excluded,
        worst_reliable=worst_reliable,
        best_reliable=best_reliable,
        favorable_strength=favorable_strength,
        worst_group_s3=worst_s3_str,
        best_group_s3=best_s3_str,
        worst_group_s3_ignored=worst_ignored,
        best_group_s3_ignored=best_ignored,
        selection_meta={
            "reliable_count": len(reliable),
            "excluded_count": len(excluded),
            "total_rows": len(rows),
            "degenerate": len(reliable) == 0,
            "favorable_strength": favorable_strength,
            "favorable_group": (
                str(best_reliable.get("group_value", "")) if best_reliable else None
            ),
        },
    )


def _resolve_variable(intent: dict, s3_output: dict) -> str | None:
    vars_intent = intent.get("variables") or []
    if isinstance(vars_intent, list) and vars_intent:
        return str(vars_intent[0])
    blocks = extract_group_descriptive_list(s3_output)
    if blocks:
        return str(blocks[0].get("variable", "")) or None
    return None


def _resolve_group_by(intent: dict, block: dict) -> str:
    if block.get("group_by"):
        return str(block["group_by"])
    gb = intent.get("group_by")
    if isinstance(gb, list):
        return str(gb[0]) if gb else ""
    return str(gb or "")


def _find_factor_config(context: Any, group_by: str) -> dict[str, Any]:
    if context is None or not group_by:
        return {}
    raw = getattr(context, "raw", None) or {}
    entites = raw.get("entites") or {}
    facteurs = entites.get("facteurs_analyse") or {}
    if not isinstance(facteurs, dict):
        return {}
    for op_cfg in facteurs.values():
        if not isinstance(op_cfg, dict):
            continue
        for factor_cfg in op_cfg.values():
            if not isinstance(factor_cfg, dict):
                continue
            if str(factor_cfg.get("colonne", "")).strip() == group_by:
                return factor_cfg
    return {}


def _resolve_group_pattern(
    factor_cfg: dict[str, Any], compact_cfg: dict[str, Any]
) -> tuple[str | None, str | None]:
    pattern = factor_cfg.get("group_value_pattern") or compact_cfg.get(
        "group_value_pattern"
    )
    if not pattern:
        return None, None
    pat = str(pattern).strip()
    if not pat:
        return None, None
    source = (
        "entites.facteurs_analyse.group_value_pattern"
        if factor_cfg.get("group_value_pattern")
        else "rapport_pdf.f2_compact.group_value_pattern"
    )
    return pat, source


def _resolve_denylist(
    factor_cfg: dict[str, Any], compact_cfg: dict[str, Any]
) -> list[str]:
    out: list[str] = []
    for src in (
        compact_cfg.get("group_value_denylist"),
        factor_cfg.get("group_value_denylist"),
    ):
        if isinstance(src, list):
            out.extend(str(x).strip() for x in src if str(x).strip())
    seen: set[str] = set()
    deduped: list[str] = []
    for item in out:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _denylist_source(
    factor_cfg: dict[str, Any],
    compact_cfg: dict[str, Any],
    denylist: list[str],
) -> str | None:
    if not denylist:
        return None
    if compact_cfg.get("group_value_denylist"):
        return "rapport_pdf.f2_compact.group_value_denylist"
    if factor_cfg.get("group_value_denylist"):
        return "entites.facteurs_analyse.group_value_denylist"
    return "merged"


def _resolve_min_n_threshold(
    level: str,
    aggregation_meta: dict[str, Any],
    compact_cfg: dict[str, Any],
    context: Any,
    rows: list[dict[str, Any]],
) -> tuple[int | None, str | None]:
    if level == "aggregated_unit":
        raw = aggregation_meta.get("min_units_per_group")
        if raw is not None:
            return int(raw), "group_descriptive.aggregation.min_units_per_group"
        if context is not None:
            defaults = context.get_agregation_metier_f2_raw().get("defaults") or {}
            if defaults.get("min_units_per_group") is not None:
                return (
                    int(defaults["min_units_per_group"]),
                    "dataset.agregation_metier_f2.defaults.min_units_per_group",
                )

    if level == "measure":
        raw = compact_cfg.get("min_n_measure")
        if raw is not None:
            return int(raw), "rapport_pdf.f2_compact.min_n_measure"

    inferred = _infer_min_n_from_row_warnings(rows)
    if inferred is not None:
        return inferred, "s3_row_warnings.effectif_faible"

    return None, None


def _infer_min_n_from_row_warnings(rows: list[dict[str, Any]]) -> int | None:
    best: int | None = None
    for row in rows:
        for warning in row.get("warnings") or []:
            text = _warning_str(warning)
            match = _EFFECTIF_FAIBLE_RE.search(text)
            if match:
                value = int(match.group(1))
                if best is None or value > best:
                    best = value
    return best


def _classify_exclusion(
    row: dict[str, Any],
    *,
    min_n: int | None,
    denylist: list[str],
    pattern_re: re.Pattern[str] | None,
) -> tuple[ExclusionReason, str] | None:
    gv_raw = row.get("group_value")
    gv = str(gv_raw).strip() if gv_raw is not None else ""
    if not gv or gv.lower() in ("none", "nan"):
        return "valeur_manquante", "group_value vide ou absent"

    gv_fold = gv.casefold()
    for denied in denylist:
        if gv_fold == denied.casefold():
            return "groupe_parasite", f"denylist: {denied}"

    if pattern_re is not None and not pattern_re.search(gv):
        return "pattern_yaml_non_respecte", f"pattern: {pattern_re.pattern}"

    n = _row_n(row)
    if min_n is not None and n is not None and n < min_n:
        return "effectif_insuffisant", f"n={n} < min_n={min_n}"

    for warning in row.get("warnings") or []:
        text = _warning_str(warning)
        if text.startswith("effectif_faible"):
            return "effectif_insuffisant", text

    return None


def _warning_str(warning: Any) -> str:
    if isinstance(warning, dict):
        code = warning.get("code", "")
        return str(code) if code else str(warning)
    return str(warning)


def _select_favorable_reference(
    reliable: list[dict[str, Any]],
    worst: dict[str, Any] | None,
    *,
    min_n: int | None,
    compact_cfg: dict[str, Any],
) -> tuple[dict[str, Any] | None, FavorableStrength]:
    """
    Référence favorable parmi les groupes fiables (hors pire groupe retenu).

    Priorité : % HT faible, Cpk élevé, IC95 % HT étroit, effectif suffisant, sans warning.
    """
    if not reliable or worst is None:
        return None, "none"

    require_cpk = bool(compact_cfg.get("require_cpk_for_favorable", True))
    max_ci95_width: float | None = None
    if "max_ci95_ht_width_pct" in compact_cfg:
        max_ci95_width = _float_cfg(compact_cfg.get("max_ci95_ht_width_pct"))
    worst_gv = str(worst.get("group_value", ""))

    robust_pool: list[dict[str, Any]] = []
    limited_pool: list[dict[str, Any]] = []

    for row in reliable:
        gv = str(row.get("group_value", ""))
        if gv == worst_gv:
            continue
        tier = _favorable_tier(
            row,
            min_n=min_n,
            require_cpk=require_cpk,
            max_ci95_width=max_ci95_width,
        )
        if tier == "robust":
            robust_pool.append(row)
        elif tier == "limited":
            limited_pool.append(row)

    if robust_pool:
        chosen = min(robust_pool, key=_favorable_sort_key)
        return chosen, "robust"
    if limited_pool:
        chosen = min(limited_pool, key=_favorable_sort_key)
        return chosen, "limited"
    return None, "none"


def _favorable_tier(
    row: dict[str, Any],
    *,
    min_n: int | None,
    require_cpk: bool,
    max_ci95_width: float | None,
) -> FavorableStrength | None:
    if _has_reliability_warning(row):
        return None
    n = _row_n(row)
    if min_n is not None and n is not None and n < min_n:
        return None

    cpk_raw = row.get("cpk")
    cpk: float | None
    try:
        cpk = float(cpk_raw) if cpk_raw is not None else None
    except (TypeError, ValueError):
        cpk = None

    if require_cpk and cpk is None:
        return None

    ci95_width = _ci95_ht_width_pct(row)
    if cpk is not None:
        if ci95_width is not None:
            if max_ci95_width is None:
                return "limited"
            if ci95_width > max_ci95_width:
                return "limited"
        return "robust"
    return None


def _favorable_sort_key(row: dict[str, Any]) -> tuple:
    pct = row.get("out_of_tolerance_rate")
    pct_key = float(pct) if pct is not None else 999.0
    cpk_raw = row.get("cpk")
    try:
        cpk_key = -float(cpk_raw) if cpk_raw is not None else 999.0
    except (TypeError, ValueError):
        cpk_key = 999.0
    ci95_w = _ci95_ht_width_pct(row)
    ci95_key = ci95_w if ci95_w is not None else 999.0
    n = _row_n(row)
    n_key = -n if n is not None else 0
    return (pct_key, cpk_key, ci95_key, n_key)


def _has_reliability_warning(row: dict[str, Any]) -> bool:
    return bool(row.get("warnings"))


def _ci95_ht_width_pct(row: dict[str, Any]) -> float | None:
    ci = row.get("ci95_out_of_tolerance_rate")
    if not isinstance(ci, dict):
        return None
    try:
        low = float(ci["low"])
        high = float(ci["high"])
    except (TypeError, ValueError, KeyError):
        return None
    return high - low


def _float_cfg(value: Any, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _row_n(row: dict[str, Any]) -> int | None:
    raw = row.get("n")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
