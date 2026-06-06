"""
P7-F2 high-cardinality — projection présentation pour facteurs à forte cardinalité.

S3 reste exhaustif ; cette couche ne modifie que le sous-ensemble affiché en F2 compact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from systems.s3 import group_descriptive

DisplayStrategy = Literal["top_risk", "top_risk_plus_best"]

_DEFAULT_HC_CFG: dict[str, Any] = {
    "high_cardinality_threshold": 8,
    "max_groups_displayed": 5,
    "display_strategy": "top_risk_plus_best",
    "aggregate_remainder": True,
    "remainder_label": "Autres modalités",
    "exploratory_disclaimer": True,
}


@dataclass
class HighCardinalityProjection:
    high_cardinality_active: bool = False
    rows_display: list[dict[str, Any]] = field(default_factory=list)
    top_risk_rows: list[dict[str, Any]] = field(default_factory=list)
    favorable_reference_row: dict[str, Any] | None = None
    remainder_row: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_high_cardinality_config(compact_cfg: dict[str, Any]) -> dict[str, Any]:
    """Fusionne defaults code + rapport_pdf.f2_compact (config-driven, pas de YAML client requis)."""
    out = dict(_DEFAULT_HC_CFG)
    if isinstance(compact_cfg, dict):
        for key in _DEFAULT_HC_CFG:
            if key in compact_cfg and compact_cfg[key] is not None:
                out[key] = compact_cfg[key]
    return out


def build_high_cardinality_projection(
    rows_reliable: list[dict[str, Any]],
    *,
    compact_cfg: dict[str, Any] | None = None,
    best_reliable: dict[str, Any] | None = None,
    favorable_strength: str = "none",
    group_by: str = "",
    variable: str = "",
    df_propre: Any = None,
    context: Any = None,
    intent: dict | None = None,
    primary_block: dict[str, Any] | None = None,
) -> HighCardinalityProjection:
    """
    Projette les groupes fiables déjà classés par S3 en lignes d'affichage compact.

    Ne recalcule aucun rang : réutilise ``rank`` S3 tel quel.
    """
    hc_cfg = resolve_high_cardinality_config(compact_cfg or {})
    threshold = int(hc_cfg["high_cardinality_threshold"])
    max_k = int(hc_cfg["max_groups_displayed"])
    strategy = str(hc_cfg.get("display_strategy") or "top_risk_plus_best")
    aggregate_remainder = bool(hc_cfg.get("aggregate_remainder", True))
    remainder_label = str(hc_cfg.get("remainder_label") or "Autres modalités")

    ordered = sorted(rows_reliable, key=lambda r: int(r.get("rank") or 999))
    total_reliable = len(ordered)

    inactive_meta = {
        "total_reliable_groups": total_reliable,
        "displayed_groups": total_reliable,
        "strategy": strategy,
        "threshold": threshold,
    }
    if total_reliable <= threshold:
        return HighCardinalityProjection(
            high_cardinality_active=False,
            rows_display=list(ordered),
            meta=inactive_meta,
        )

    top_risk_rows = [dict(r) for r in ordered[:max_k]]
    displayed_values: set[str] = {
        str(r.get("group_value", "")) for r in top_risk_rows
    }

    favorable_reference_row: dict[str, Any] | None = None
    if strategy == "top_risk_plus_best" and favorable_strength in ("robust", "limited"):
        if best_reliable and isinstance(best_reliable, dict):
            best_gv = str(best_reliable.get("group_value", ""))
            if best_gv and best_gv not in displayed_values:
                favorable_reference_row = dict(best_reliable)
                displayed_values.add(best_gv)

    remainder_sources = [
        r
        for r in ordered
        if str(r.get("group_value", "")) not in displayed_values
    ]
    remainder_row: dict[str, Any] | None = None
    if aggregate_remainder and remainder_sources:
        remainder_row = _build_remainder_row(
            remainder_sources,
            label=remainder_label,
            group_by=group_by,
            variable=variable,
            df_propre=df_propre,
            context=context,
            intent=intent,
            primary_block=primary_block,
        )
        if remainder_row:
            displayed_values.add(remainder_label)

    rows_display: list[dict[str, Any]] = list(top_risk_rows)
    if favorable_reference_row is not None:
        rows_display.append(favorable_reference_row)
    if remainder_row is not None:
        rows_display.append(remainder_row)

    max_table_rows = hc_cfg.get("max_table_rows")
    if max_table_rows is not None:
        cap = int(max_table_rows)
        if len(rows_display) > cap:
            rows_display = rows_display[:cap]

    meta = {
        "total_reliable_groups": total_reliable,
        "displayed_groups": len(rows_display),
        "top_k": max_k,
        "strategy": strategy,
        "threshold": threshold,
        "remainder_group_count": len(remainder_sources),
        "remainder_label": remainder_label if remainder_row else None,
        "exploratory_disclaimer": bool(hc_cfg.get("exploratory_disclaimer", True)),
        "all_reliable_group_values": [
            str(r.get("group_value", "")) for r in ordered
        ],
    }

    return HighCardinalityProjection(
        high_cardinality_active=True,
        rows_display=rows_display,
        top_risk_rows=top_risk_rows,
        favorable_reference_row=favorable_reference_row,
        remainder_row=remainder_row,
        meta=meta,
    )


def apply_high_cardinality_projection(
    selection: Any,
    cfg: dict[str, Any],
    *,
    df_propre: Any = None,
    context: Any = None,
    intent: dict | None = None,
    primary_block: dict[str, Any] | None = None,
) -> HighCardinalityProjection:
    """
    Enrichit une ``F2CompactSelection`` avec la projection high-cardinality.
    """
    from systems.s7 import prep

    compact_cfg = prep.f2_compact_config(cfg)
    projection = build_high_cardinality_projection(
        list(selection.rows_reliable),
        compact_cfg=compact_cfg,
        best_reliable=selection.best_reliable,
        favorable_strength=str(selection.favorable_strength or "none"),
        group_by=str(selection.group_by or ""),
        variable=str(selection.variable or ""),
        df_propre=df_propre,
        context=context,
        intent=intent,
        primary_block=primary_block,
    )

    selection.high_cardinality_active = projection.high_cardinality_active
    selection.rows_display = list(projection.rows_display)
    selection.high_cardinality = projection.to_dict()

    hc_meta = dict(selection.selection_meta)
    hc_meta["high_cardinality"] = projection.meta
    hc_meta["high_cardinality_active"] = projection.high_cardinality_active
    if projection.high_cardinality_active:
        hc_meta["displayed_groups"] = projection.meta.get("displayed_groups")
    selection.selection_meta = hc_meta

    return projection


def chart_group_values(selection: Any) -> list[str]:
    """Groupes à inclure dans le boxplot (hors agrégat remainder sauf sources explicites)."""
    rows = rows_for_display(selection)
    out: list[str] = []
    hc = getattr(selection, "high_cardinality", None) or {}
    remainder_label = (hc.get("meta") or {}).get("remainder_label")
    for row in rows:
        if row.get("is_remainder_aggregate"):
            continue
        gv = str(row.get("group_value", ""))
        if gv:
            out.append(gv)
    if not out and remainder_label:
        for row in rows:
            gv = str(row.get("group_value", ""))
            if gv:
                out.append(gv)
    return out


def rows_for_display(selection: Any) -> list[dict[str, Any]]:
    if getattr(selection, "high_cardinality_active", False) and getattr(
        selection, "rows_display", None
    ):
        return list(selection.rows_display)
    return list(selection.rows_reliable)


def exploratory_disclaimer_paragraph(selection: Any, *, factor_label: str = "") -> str | None:
    hc = getattr(selection, "high_cardinality", None) or {}
    meta = hc.get("meta") or {}
    if not getattr(selection, "high_cardinality_active", False):
        return None
    if not meta.get("exploratory_disclaimer", True):
        return None
    total = meta.get("total_reliable_groups")
    shown = meta.get("displayed_groups")
    unit = factor_label.strip() or "modalités"
    return (
        f"Analyse exploratoire : {total} {unit} fiables analysées, "
        f"{shown} affichées (groupes les plus à risque). "
        "Les écarts observés sont des associations statistiques ; "
        "ils ne démontrent pas à eux seuls une causalité directe."
    )


def _build_remainder_row(
    remainder_rows: list[dict[str, Any]],
    *,
    label: str,
    group_by: str,
    variable: str,
    df_propre: Any,
    context: Any,
    intent: dict | None,
    primary_block: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not remainder_rows:
        return None

    remainder_values = [str(r.get("group_value", "")) for r in remainder_rows]
    if df_propre is not None and group_by and variable and _has_columns(
        df_propre, group_by, variable
    ):
        row = _remainder_from_df(
            df_propre,
            group_col=group_by,
            variable=variable,
            remainder_values=remainder_values,
            label=label,
            context=context,
            intent=intent or {},
            primary_block=primary_block,
        )
        if row is not None:
            return row

    return _remainder_from_rows(remainder_rows, label=label)


def _remainder_from_df(
    df_propre: Any,
    *,
    group_col: str,
    variable: str,
    remainder_values: list[str],
    label: str,
    context: Any,
    intent: dict,
    primary_block: dict[str, Any] | None,
) -> dict[str, Any] | None:
    try:
        import pandas as pd
    except ImportError:
        return None

    if not isinstance(df_propre, pd.DataFrame):
        return None

    value_set = set(remainder_values)
    mask = df_propre[group_col].astype(str).isin(value_set)
    series = df_propre.loc[mask, variable]
    if series.empty:
        return _remainder_from_rows(
            [{"group_value": v, "n": 0} for v in remainder_values],
            label=label,
        )

    worse_direction = "both"
    lti = lts = nominal = None
    if primary_block:
        worse_direction = str(primary_block.get("worse_direction") or "both")
    if context is not None and variable:
        lti, lts, nominal = group_descriptive._resolve_tolerances(  # noqa: SLF001
            context, intent, variable
        )

    row = group_descriptive._build_group_row(  # noqa: SLF001
        label,
        series,
        lti=lti,
        lts=lts,
        nominal=nominal,
        worse_direction=worse_direction,  # type: ignore[arg-type]
    )
    row["is_remainder_aggregate"] = True
    row["remainder_group_count"] = len(remainder_values)
    row["severity_label"] = "surveillance"
    row["rank"] = None
    return row


def _remainder_from_rows(
    remainder_rows: list[dict[str, Any]],
    *,
    label: str,
) -> dict[str, Any]:
    total_n = 0
    weighted_mean = 0.0
    weighted_ht = 0.0
    for row in remainder_rows:
        n_raw = row.get("n")
        try:
            n = int(n_raw) if n_raw is not None else 0
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            continue
        total_n += n
        mean_raw = row.get("mean")
        ht_raw = row.get("out_of_tolerance_rate")
        if mean_raw is not None:
            weighted_mean += float(mean_raw) * n
        if ht_raw is not None:
            weighted_ht += float(ht_raw) * n

    mean_val = round(weighted_mean / total_n, 6) if total_n else None
    ht_val = round(weighted_ht / total_n, 4) if total_n else None

    return {
        "group_value": label,
        "n": total_n,
        "mean": mean_val,
        "out_of_tolerance_rate": ht_val,
        "cpk": None,
        "is_remainder_aggregate": True,
        "remainder_group_count": len(remainder_rows),
        "severity_label": "surveillance",
        "rank": None,
        "warnings": [],
    }


def _has_columns(df: Any, *columns: str) -> bool:
    try:
        return all(col in df.columns for col in columns)
    except AttributeError:
        return False
