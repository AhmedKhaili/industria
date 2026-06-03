"""
Construction des PNG via enterprise/report/charts.py.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy import stats

from enterprise.report import charts as report_charts
from systems.stats.portrait_metrics import fit_pdf_grid

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


def _tolerance_span(tol: dict, value_span: float | None = None) -> float:
    """Plage pour seuil de chevauchement nominal / LTI / LTS (5 %)."""
    if value_span is not None and value_span > 0:
        return float(value_span)
    lti, lts = tol.get("lti"), tol.get("lts")
    if lti is not None and lts is not None:
        return max(float(lts) - float(lti), 1e-9)
    return 1.0


def _nominal_label_visible(tol: dict, value_span: float | None = None) -> bool:
    """Masque le label Nominal s'il chevauche LTI ou LTS (ligne conservée)."""
    if tol.get("nominal") is None:
        return False
    nom = float(tol["nominal"])
    thresh = 0.05 * _tolerance_span(tol, value_span)
    for key in ("lti", "lts"):
        if tol.get(key) is not None and abs(nom - float(tol[key])) < thresh:
            return False
    return True


def _add_tolerance_lines(
    fig,
    tol: dict | None,
    *,
    axis: str = "y",
    value_span: float | None = None,
) -> None:
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
        show_ann = not (key == "nominal" and not _nominal_label_visible(tol, value_span))
        if axis == "y":
            if show_ann:
                fig.add_hline(
                    y=val,
                    line_dash=dash,
                    line_color=color,
                    annotation_text=label,
                )
            else:
                fig.add_hline(y=val, line_dash=dash, line_color=color)
        elif show_ann:
            fig.add_vline(
                x=val,
                line_dash=dash,
                line_color=color,
                annotation_text=label,
            )
        else:
            fig.add_vline(x=val, line_dash=dash, line_color=color)


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


def _fit_for_variable(
    specialist_results: list[dict] | None,
    variable: str,
) -> dict | None:
    if not specialist_results:
        return None
    for item in specialist_results:
        if item.get("status") != "success":
            continue
        agent = str(item.get("agent", "")).lower()
        if "distribution" not in agent:
            continue
        res = item.get("result") or {}
        if str(res.get("colonne", "")) == variable and res.get("loi_retenue"):
            return res
    return None


def build_histogram(
    df: pd.DataFrame,
    variable: str,
    context: "ClientContext",
    intent: dict,
    *,
    specialist_results: list[dict] | None = None,
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
        vals = work[variable].astype(float)
        data_span = float(vals.max() - vals.min()) or 1.0
        _add_tolerance_lines(fig, tol, axis="x", value_span=data_span)

        fit = _fit_for_variable(specialist_results, variable)
        if fit and fit.get("loi_retenue") != "normale":
            grid = fit_pdf_grid(
                str(fit["loi_retenue"]),
                dict(fit.get("parametres") or {}),
                float(vals.min()),
                float(vals.max()),
            )
            if grid is not None:
                xs, pdf = grid
                scale = len(vals) * (data_span / nbins)
                fig.add_trace(
                    go.Scatter(
                        x=xs,
                        y=pdf * scale,
                        mode="lines",
                        name="Loi ajustée",
                        line=dict(color="#1E3A5F", width=2),
                    )
                )

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


def build_qqplot(
    df: pd.DataFrame,
    variable: str,
    context: "ClientContext",
    intent: dict,
    *,
    specialist_results: list[dict] | None = None,
) -> dict:
    """QQ-plot empirique vs normale théorique."""
    _ = specialist_results
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if variable not in df.columns:
            return {"error": f"Variable absente : {variable}", "png_bytes": None}
        series = pd.to_numeric(df[variable], errors="coerce").dropna()
        if len(series) < 8:
            return {"error": "Effectif insuffisant pour QQ-plot", "png_bytes": None}

        fig_mpl, ax = plt.subplots(figsize=(8, 4))
        stats.probplot(series.to_numpy(dtype=float), dist="norm", plot=ax)
        ax.set_title(f"QQ-plot — {variable}")
        ax.grid(True, alpha=0.3)
        buf = io.BytesIO()
        fig_mpl.tight_layout()
        fig_mpl.savefig(buf, format="png", dpi=100)
        plt.close(fig_mpl)
        return {
            "error": None,
            "png_bytes": buf.getvalue(),
            "description": _chart_description("qqplot", variable, intent, context),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "png_bytes": None}


def build_boxplot_chart(
    df: pd.DataFrame,
    variable: str,
    context: "ClientContext",
    intent: dict,
    *,
    specialist_results: list[dict] | None = None,
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

        filter_warning: str | None = None
        include_groups = intent.get("chart_include_group_values")
        if group_col and group_col in plot_df.columns and include_groups is not None:
            if isinstance(include_groups, list):
                if len(include_groups) == 0:
                    filter_warning = "chart_include_group_values_empty"
                else:
                    allowed = {str(g) for g in include_groups}
                    plot_df = plot_df[plot_df[group_col].astype(str).isin(allowed)]
                    if plot_df.empty:
                        return {
                            "error": "Aucune donnée pour le boxplot après filtrage groupes",
                            "png_bytes": None,
                            "filter_warning": "chart_include_group_values_no_match",
                        }

        unit = _unit_label(context, intent, variable)
        y_title = f"{variable} ({unit})" if unit else variable
        if group_col and group_col in plot_df.columns:
            fig = px.box(plot_df, x=group_col, y=variable, points="outliers")
            title = f"Comparaison par {group_col} — {variable}"
        else:
            fig = px.box(plot_df, y=variable, points="outliers")
            title = f"Distribution — {variable}"

        tol = _tolerance(context, intent, variable)
        y_span = float(plot_df[variable].max() - plot_df[variable].min()) or 1.0
        _add_tolerance_lines(fig, tol, axis="y", value_span=y_span)
        _ = specialist_results
        fig.update_layout(
            **report_charts.PLOTLY_THEME,
            title=title,
            yaxis_title=y_title,
        )
        png = report_charts._fig_to_png(fig, 800, 400)
        groups_plotted: list[str] = []
        if group_col and group_col in plot_df.columns:
            groups_plotted = sorted(plot_df[group_col].astype(str).unique().tolist())
        return {
            "error": None,
            "png_bytes": png,
            "description": _chart_description("boxplot", variable, intent, context),
            "groups_plotted": groups_plotted,
            "filter_warning": filter_warning,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "png_bytes": None}


def build_timeseries_chart(
    df: pd.DataFrame,
    variable: str,
    context: "ClientContext",
    intent: dict,
    *,
    specialist_results: list[dict] | None = None,
) -> dict:
    _ = specialist_results
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
    "qqplot": build_qqplot,
    "timeseries": build_timeseries_chart,
}

_PORTRAIT_CHART_TYPES = ("histogram", "boxplot", "qqplot")


def build_charts(
    df: pd.DataFrame,
    intent: dict,
    context: "ClientContext",
    chart_types: list[str],
    *,
    specialist_results: list[dict] | None = None,
) -> dict:
    try:
        if df is None or df.empty:
            return {"error": "df_propre vide", "charts": []}

        variables = _target_variables(df, intent)
        if not variables:
            return {"error": "Aucune variable numérique à tracer", "charts": []}

        charts: list[dict] = []
        intention = str(intent.get("intention") or "")
        if intention == "portrait_statistique":
            types_for_portrait = [t for t in _PORTRAIT_CHART_TYPES if t in chart_types or not chart_types]
            if not types_for_portrait:
                types_for_portrait = list(_PORTRAIT_CHART_TYPES)
            for variable in variables[:3]:
                portrait_intent = {**intent, "group_by": None}
                for chart_type in types_for_portrait:
                    builder = _BUILDERS.get(chart_type)
                    if not builder:
                        continue
                    built = builder(
                        df,
                        variable,
                        context,
                        portrait_intent,
                        specialist_results=specialist_results,
                    )
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

        for chart_type in chart_types:
            builder = _BUILDERS.get(chart_type)
            if not builder:
                continue
            vars_to_plot = variables[:1] if chart_type in ("histogram", "qqplot", "timeseries") else variables
            for variable in vars_to_plot:
                built = builder(
                    df,
                    variable,
                    context,
                    intent,
                    specialist_results=specialist_results,
                )
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
