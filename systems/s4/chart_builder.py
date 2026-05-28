"""
Construction des PNG via enterprise/report/charts.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import plotly.express as px

from enterprise.report import charts as report_charts

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def _resolve_piece_operation(intent: dict) -> tuple[str | None, str | None]:
    filtres = intent.get("filtres") or {}
    piece = intent.get("piece") or filtres.get("piece")
    operation = intent.get("operation") or filtres.get("operation")
    if isinstance(piece, list):
        piece = piece[0] if piece else None
    return piece, operation


def _resolve_group_column(intent: dict) -> str | None:
    group_by = intent.get("group_by")
    if isinstance(group_by, list):
        return group_by[0] if group_by else None
    return group_by


def _target_variables(df: pd.DataFrame, intent: dict) -> list[str]:
    variables = intent.get("variables") or []
    numeric = set(df.select_dtypes(include="number").columns)
    if variables:
        return [v for v in variables if v in numeric]
    return sorted(numeric)


def _tolerance(
    context: "ClientContext",
    intent: dict,
    variable: str,
) -> dict | None:
    piece, operation = _resolve_piece_operation(intent)
    if not piece or not operation:
        return None
    tol = context.get_tolerance(piece, operation, variable)
    return dict(tol) if isinstance(tol, dict) else None


def _unit_label(context: "ClientContext", intent: dict, variable: str) -> str:
    tol = _tolerance(context, intent, variable)
    if tol and tol.get("unite"):
        return str(tol["unite"])
    return "valeur brute"


def _add_tolerance_lines(fig, tol: dict | None, *, axis: str = "y") -> None:
    """Trace LTI / LTS / nominal sur un graphique Plotly (y = boxplot, x = histogramme)."""
    if not tol:
        return
    for key, label, dash, color in (
        ("lti", "LTI", "dash", "#DC2626"),
        ("lts", "LTS", "dash", "#DC2626"),
        ("nominal", "Nominal", "dot", "#1E3A5F"),
    ):
        if tol.get(key) is None:
            continue
        val = float(tol[key])
        if axis == "y":
            fig.add_hline(
                y=val,
                line_dash=dash,
                line_color=color,
                annotation_text=label,
            )
        else:
            fig.add_vline(
                x=val,
                line_dash=dash,
                line_color=color,
                annotation_text=label,
            )


def _chart_description(
    chart_type: str,
    variable: str,
    intent: dict,
    context: "ClientContext",
) -> str:
    piece, operation = _resolve_piece_operation(intent)
    tol = _tolerance(context, intent, variable)
    parts = [
        f"Graphique {chart_type} pour la variable {variable}",
        f"pièce {piece}" if piece else None,
        f"opération {operation}" if operation else None,
    ]
    if tol and tol.get("lti") is not None and tol.get("lts") is not None:
        parts.append(
            f"limites LTI={tol['lti']} / LTS={tol['lts']} {tol.get('unite') or ''}".strip()
        )
    return " — ".join(p for p in parts if p)


def build_histogram(
    df: pd.DataFrame,
    variable: str,
    context: "ClientContext",
    intent: dict,
) -> dict:
    try:
        if variable not in df.columns:
            return {"error": f"Variable absente : {variable}", "png_bytes": None}

        work = df[[variable]].dropna()
        if work.empty:
            png = report_charts.build_boxplot(df, variable, None, title="", unit="")
            return {
                "error": None,
                "png_bytes": png,
                "description": _chart_description("histogram", variable, intent, context),
            }

        nbins = min(40, max(10, len(work) // 5))
        fig = px.histogram(work, x=variable, nbins=nbins)
        tol = _tolerance(context, intent, variable)
        _add_tolerance_lines(fig, tol, axis="x")

        unit = _unit_label(context, intent, variable)
        fig.update_layout(
            **report_charts.PLOTLY_THEME,
            title=f"Distribution — {variable}",
            xaxis_title=f"{variable} ({unit})",
            yaxis_title="Effectif",
        )
        png = report_charts._fig_to_png(fig, 800, 400)
        return {
            "error": None,
            "png_bytes": png,
            "description": _chart_description("histogram", variable, intent, context),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "png_bytes": None}


def build_boxplot_chart(
    df: pd.DataFrame,
    variable: str,
    context: "ClientContext",
    intent: dict,
) -> dict:
    """Boxplot Plotly avec LTI/LTS en lignes horizontales (S4 — sans modifier enterprise/)."""
    try:
        if variable not in df.columns:
            return {"error": f"Variable absente : {variable}", "png_bytes": None}

        group_col = _resolve_group_column(intent)
        cols = [variable]
        if group_col and group_col in df.columns:
            cols.append(group_col)
        plot_df = df[cols].dropna(subset=[variable])
        if plot_df.empty:
            return {"error": "Aucune donnée pour le boxplot", "png_bytes": None}

        unit = _unit_label(context, intent, variable)
        y_title = f"{variable} ({unit})" if unit else variable
        if group_col and group_col in plot_df.columns:
            fig = px.box(plot_df, x=group_col, y=variable, points="outliers")
            title = f"Comparaison par {group_col} — {variable}"
        else:
            fig = px.box(plot_df, y=variable, points="outliers")
            title = f"Distribution — {variable}"

        _add_tolerance_lines(fig, _tolerance(context, intent, variable), axis="y")
        fig.update_layout(
            **report_charts.PLOTLY_THEME,
            title=title,
            yaxis_title=y_title,
        )
        png = report_charts._fig_to_png(fig, 800, 400)
        return {
            "error": None,
            "png_bytes": png,
            "description": _chart_description("boxplot", variable, intent, context),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "png_bytes": None}


def build_timeseries_chart(
    df: pd.DataFrame,
    variable: str,
    context: "ClientContext",
    intent: dict,
) -> dict:
    try:
        unit = _unit_label(context, intent, variable)
        col_date = context.colonnes.get("temps", "Date")
        title = f"Série temporelle — {variable}"
        png = report_charts.build_timeseries(df, variable, anomalies=None, unit=unit, title=title)
        desc = _chart_description("timeseries", variable, intent, context)
        if col_date in df.columns:
            desc += f" (axe temps : {col_date})"
        return {"error": None, "png_bytes": png, "description": desc}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "png_bytes": None}


_BUILDERS = {
    "histogram": build_histogram,
    "boxplot": build_boxplot_chart,
    "timeseries": build_timeseries_chart,
}


def build_charts(
    df: pd.DataFrame,
    intent: dict,
    context: "ClientContext",
    chart_types: list[str],
) -> dict:
    try:
        if df is None or df.empty:
            return {"error": "df_propre vide", "charts": []}

        variables = _target_variables(df, intent)
        if not variables:
            return {"error": "Aucune variable numérique à tracer", "charts": []}

        charts: list[dict] = []
        for chart_type in chart_types:
            builder = _BUILDERS.get(chart_type)
            if not builder:
                continue
            vars_to_plot = variables[:1] if chart_type in ("histogram", "timeseries") else variables
            for variable in vars_to_plot:
                built = builder(df, variable, context, intent)
                charts.append(
                    {
                        "id": f"{chart_type}_{variable}",
                        "type": chart_type,
                        "variable": variable,
                        "title": f"{chart_type} — {variable}",
                        "png_bytes": built.get("png_bytes"),
                        "description": built.get("description", ""),
                        "error": built.get("error"),
                    }
                )

        return {"error": None, "charts": charts}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "charts": []}
