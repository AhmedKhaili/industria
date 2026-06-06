"""
P7-F2 compact — graphiques limités aux groupes fiables (présentation S7, génération S4 minimale).
"""

from __future__ import annotations

from typing import Any

from systems.s7.f2_compact_selection import F2CompactSelection
from systems.s7.f2_high_cardinality import chart_group_values


def build_compact_chart_items(
    chart_items: list[dict[str, Any]],
    selection: F2CompactSelection,
    intent: dict,
    context: Any,
    *,
    df_propre: Any = None,
) -> list[dict[str, Any]]:
    """
    Boxplot principal : groupes fiables uniquement si df_propre disponible.
    Sinon repasse les items avec métadonnées de filtrage attendu.
    """
    reliable = chart_group_values(selection)
    excluded = {
        str(e.group_value)
        for e in selection.rows_excluded
        if e.group_value
    }
    variable = selection.variable

    if df_propre is not None and variable and _has_column(df_propre, variable):
        rebuilt = _rebuild_boxplots(
            chart_items,
            df_propre=df_propre,
            variable=variable,
            intent=intent,
            context=context,
            reliable_groups=reliable,
        )
        if rebuilt is not None:
            return rebuilt

    out: list[dict[str, Any]] = []
    for item in chart_items:
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        payload["included_groups"] = reliable
        payload["excluded_from_chart"] = sorted(excluded)
        payload["reliable_groups_only"] = True
        if excluded and not df_propre:
            note = (
                "Graphique non régénéré : groupes exclus retirés du boxplot "
                "lorsque df_propre est fourni au pipeline."
            )
            cap = str(payload.get("caption") or "")
            if note not in cap:
                payload["caption"] = f"{cap} {note}".strip() if cap else note
        out.append(payload)
    return out


def _has_column(df: Any, column: str) -> bool:
    try:
        return column in df.columns
    except AttributeError:
        return False


def _rebuild_boxplots(
    chart_items: list[dict[str, Any]],
    *,
    df_propre: Any,
    variable: str,
    intent: dict,
    context: Any,
    reliable_groups: list[str],
) -> list[dict[str, Any]] | None:
    try:
        from systems.s4.chart_builder import build_boxplot_chart
    except ImportError:
        return None

    if not reliable_groups:
        return chart_items

    filt_intent = {**intent, "chart_include_group_values": reliable_groups}
    rebuilt_chart = build_boxplot_chart(
        df_propre, variable, context, filt_intent
    )
    if not isinstance(rebuilt_chart, dict) or not rebuilt_chart.get("png_bytes"):
        return None

    out: list[dict[str, Any]] = []
    replaced = False
    for item in chart_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).lower()
        is_box = "boxplot" in title or str(item.get("type", "")).lower() == "boxplot"
        if is_box and not replaced:
            out.append(
                {
                    "id": item.get("id", "boxplot_compact"),
                    "title": item.get("title") or f"Comparaison par groupe — {variable}",
                    "caption": item.get("caption") or "",
                    "interpretation": item.get("interpretation") or "",
                    "png_bytes": rebuilt_chart.get("png_bytes"),
                    "included_groups": reliable_groups,
                    "reliable_groups_only": True,
                    "filtered_from_s4": True,
                }
            )
            replaced = True
        else:
            out.append(dict(item))
    if not replaced:
        out.insert(
            0,
            {
                "id": "boxplot_compact",
                "title": f"Comparaison par groupe — {variable}",
                "caption": "",
                "interpretation": "",
                "png_bytes": rebuilt_chart.get("png_bytes"),
                "included_groups": reliable_groups,
                "reliable_groups_only": True,
                "filtered_from_s4": True,
            },
        )
    return out
