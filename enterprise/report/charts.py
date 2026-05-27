"""Graphiques Plotly industriels — export PNG via kaleido, sans LLM."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Couleurs alignées sur enterprise/report/styles.py (pas d'import pour éviter cycles)
_C_P1 = "#DC2626"
_C_P2 = "#EA580C"
_C_P3 = "#CA8A04"
_C_P4 = "#16A34A"
_C_HEADER = "#1E3A5F"
_C_TEXT = "#1E293B"

PLOTLY_THEME = dict(
    font_family="Arial",
    font_color=_C_TEXT,
    paper_bgcolor="white",
    plot_bgcolor="#F8FAFC",
    margin=dict(l=50, r=30, t=40, b=50),
)

_PLACEHOLDER_MSG = "Données insuffisantes"


def _placeholder_figure(message: str = _PLACEHOLDER_MSG) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        **PLOTLY_THEME,
        title=dict(text=message, x=0.5, xanchor="center"),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color=_C_TEXT),
            )
        ],
    )
    return fig


def _fig_to_png(fig: go.Figure, width: int = 1200, height: int = 400) -> bytes:
    """Convertit une figure Plotly en PNG ; placeholder si kaleido absent."""
    try:
        return fig.to_image(format="png", width=width, height=height, engine="kaleido")
    except Exception:
        try:
            return fig.to_image(format="png", width=width, height=height)
        except Exception:
            return _minimal_png_bytes(width, height, _PLACEHOLDER_MSG)


def _minimal_png_bytes(width: int, height: int, message: str) -> bytes:
    """PNG minimal via Plotly sans moteur externe (dernier recours)."""
    fig = _placeholder_figure(message)
    try:
        import plotly.io as pio

        pio.kaleido.scope.default_width = width
        pio.kaleido.scope.default_height = height
        return fig.to_image(format="png", width=width, height=height)
    except Exception:
        # 1×1 PNG transparent en dernier recours absolu
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )


def _resolve_time_value_cols(df: pd.DataFrame, target: str) -> tuple[str | None, str | None]:
    """Détecte colonnes temps et valeur."""
    if df is None or df.empty:
        return None, None
    time_candidates = [
        c
        for c in df.columns
        if c.lower() in ("timestamp", "time", "datetime", "date", "ts")
        or pd.api.types.is_datetime64_any_dtype(df[c])
    ]
    time_col = time_candidates[0] if time_candidates else None
    if time_col is None and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
        time_col = df.columns[0]
    value_col = target if target in df.columns else None
    if value_col is None:
        numeric = df.select_dtypes(include=[np.number]).columns.tolist()
        value_col = numeric[0] if numeric else None
    return time_col, value_col


def build_timeseries(
    df: pd.DataFrame,
    target: str,
    anomalies: pd.DataFrame | None = None,
    unit: str = "valeur brute",
    title: str = "",
) -> bytes:
    """Série temporelle avec bandes ±2σ / ±3σ et anomalies en croix rouges."""
    if df is None or df.empty:
        return _fig_to_png(_placeholder_figure(), 1200, 400)

    work = df.copy()
    time_col, value_col = _resolve_time_value_cols(work, target)
    if value_col is None:
        return _fig_to_png(_placeholder_figure(), 1200, 400)

    if time_col and time_col in work.columns:
        work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
        work = work.dropna(subset=[time_col, value_col]).sort_values(time_col)
        x = work[time_col]
    else:
        work = work.dropna(subset=[value_col])
        x = np.arange(len(work))

    y = work[value_col].astype(float)
    if len(y) < 2:
        return _fig_to_png(_placeholder_figure(), 1200, 400)

    mean = float(y.mean())
    std = float(y.std(ddof=0)) if len(y) > 1 else 0.0
    if std == 0:
        std = 1e-9

    fig = go.Figure()
    upper2, lower2 = mean + 2 * std, mean - 2 * std
    upper3, lower3 = mean + 3 * std, mean - 3 * std

    fig.add_trace(
        go.Scatter(
            x=x,
            y=[upper3] * len(x),
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[lower3] * len(x),
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(220,38,38,0.15)",
            line=dict(width=0),
            name="±3σ",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[upper2] * len(x),
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=[lower2] * len(x),
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(0,128,0,0.15)",
            line=dict(width=0),
            name="±2σ",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name=target,
            line=dict(color=_C_HEADER, width=2),
        )
    )

    if anomalies is not None and not anomalies.empty:
        anom = anomalies.copy()
        _, anom_val = _resolve_time_value_cols(anom, target)
        anom_time = time_col if time_col and time_col in anom.columns else None
        if anom_val and anom_val in anom.columns:
            if anom_time:
                anom[anom_time] = pd.to_datetime(anom[anom_time], errors="coerce")
                ax = anom[anom_time]
            else:
                ax = anom.index
            fig.add_trace(
                go.Scatter(
                    x=ax,
                    y=anom[anom_val],
                    mode="markers",
                    name="Anomalies",
                    marker=dict(symbol="x", size=10, color=_C_P1, line=dict(width=2)),
                )
            )

    y_label = f"{target} ({unit})" if unit else target
    layout_title = title or f"Série temporelle — {target}"
    fig.update_layout(
        **PLOTLY_THEME,
        title=layout_title,
        xaxis_title="Temps",
        yaxis_title=y_label,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return _fig_to_png(fig, 1200, 400)


def build_gauge(
    value: float,
    title: str,
    min_val: float = 0,
    max_val: float = 100,
    seuils: dict | None = None,
) -> bytes:
    """Jauge indicateur avec zones P4→P1."""
    seuils = seuils or {"P3": 60, "P2": 80, "P1": 95}
    p3 = float(seuils.get("P3", 60))
    p2 = float(seuils.get("P2", 80))
    p1 = float(seuils.get("P1", 95))

    try:
        val = float(value)
    except (TypeError, ValueError):
        val = min_val

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=val,
            title=dict(text=title),
            gauge=dict(
                axis=dict(range=[min_val, max_val]),
                bar=dict(color=_C_HEADER),
                steps=[
                    dict(range=[min_val, p3], color=_C_P4),
                    dict(range=[p3, p2], color=_C_P3),
                    dict(range=[p2, p1], color=_C_P2),
                    dict(range=[p1, max_val], color=_C_P1),
                ],
            ),
        )
    )
    fig.update_layout(**PLOTLY_THEME)
    return _fig_to_png(fig, 400, 400)


def build_heatmap(
    corr_matrix: pd.DataFrame,
    title: str = "Corrélations",
) -> bytes:
    """Heatmap de corrélations avec annotations."""
    if corr_matrix is None or corr_matrix.empty:
        return _fig_to_png(_placeholder_figure(), 800, 600)

    mat = corr_matrix.astype(float)
    labels = [str(c) for c in mat.columns]
    z = mat.values
    annotations = []
    for i, row in enumerate(z):
        for j, val in enumerate(row):
            if np.isnan(val):
                txt = "N/A"
            else:
                txt = f"{val:.2f}"
            annotations.append(
                dict(
                    x=labels[j],
                    y=labels[i],
                    text=txt,
                    showarrow=False,
                    font=dict(size=9, color=_C_TEXT),
                )
            )

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=labels,
            y=labels,
            colorscale=[
                [0.0, "#2563EB"],
                [0.5, "#FFFFFF"],
                [1.0, _C_P1],
            ],
            zmin=-1,
            zmax=1,
            colorbar=dict(title="r"),
        )
    )
    fig.update_layout(
        **PLOTLY_THEME,
        title=title,
        annotations=annotations,
        xaxis=dict(side="bottom"),
        yaxis=dict(autorange="reversed"),
    )
    return _fig_to_png(fig, 800, 600)


def build_waterfall(
    categories: list,
    values: list,
    title: str = "Impact financier",
    unit: str = "€",
) -> bytes:
    """Diagramme en cascade — positifs verts, négatifs rouges, total bleu header."""
    if not categories or not values:
        return _fig_to_png(_placeholder_figure(), 1000, 400)

    cats = list(categories)
    vals = [float(v) for v in values]
    measures = []
    for i, v in enumerate(vals):
        if i == len(vals) - 1:
            measures.append("total")
        else:
            measures.append("relative")

    fig = go.Figure(
        go.Waterfall(
            name=title,
            orientation="v",
            measure=measures,
            x=cats,
            y=vals,
            connector=dict(line=dict(color=_C_TEXT)),
            increasing=dict(marker=dict(color=_C_P4)),
            decreasing=dict(marker=dict(color=_C_P1)),
            totals=dict(marker=dict(color=_C_HEADER)),
        )
    )
    fig.update_layout(
        **PLOTLY_THEME,
        title=title,
        yaxis_title=f"Montant ({unit})",
    )
    return _fig_to_png(fig, 1000, 400)


def _score_to_color(score: float, max_score: int = 100) -> str:
    """Gradient P4 (faible) → P1 (élevé)."""
    ratio = min(max(float(score) / max(max_score, 1), 0.0), 1.0)
    stops = [
        (0.0, (22, 163, 74)),
        (0.33, (202, 138, 4)),
        (0.66, (234, 88, 12)),
        (1.0, (220, 38, 38)),
    ]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= ratio <= t1:
            t = (ratio - t0) / (t1 - t0) if t1 > t0 else 0
            r = int(c0[0] + t * (c1[0] - c0[0]))
            g = int(c0[1] + t * (c1[1] - c0[1]))
            b = int(c0[2] + t * (c1[2] - c0[2]))
            return f"rgb({r},{g},{b})"
    return _C_P1


def build_bar_horizontal(
    labels: list,
    scores: list,
    title: str = "Causes probables",
    max_score: int = 100,
) -> bytes:
    """Barres horizontales triées par score décroissant."""
    if not labels or not scores:
        return _fig_to_png(_placeholder_figure(), 800, 400)

    pairs = sorted(zip(labels, scores), key=lambda x: float(x[1]), reverse=True)
    lbls = [str(p[0]) for p in pairs]
    scrs = [float(p[1]) for p in pairs]
    bar_colors = [_score_to_color(s, max_score) for s in scrs]
    annotations = [
        dict(x=s + max_score * 0.02, y=lbl, text=f"{s:.0f}", showarrow=False, xanchor="left")
        for lbl, s in zip(lbls, scrs)
    ]

    fig = go.Figure(
        go.Bar(
            x=scrs,
            y=lbls,
            orientation="h",
            marker=dict(color=bar_colors),
            text=[f"{s:.0f}" for s in scrs],
            textposition="outside",
        )
    )
    fig.update_layout(
        **PLOTLY_THEME,
        title=title,
        xaxis=dict(title="Indice /100", range=[0, max_score * 1.15]),
        yaxis=dict(autorange="reversed"),
        annotations=annotations,
    )
    return _fig_to_png(fig, 800, 400)


def build_boxplot(
    df: pd.DataFrame,
    value_col: str,
    group_col: str | None = None,
    title: str = "",
    unit: str = "valeur brute",
) -> bytes:
    """Boxplot global ou par groupe."""
    if df is None or df.empty or value_col not in df.columns:
        return _fig_to_png(_placeholder_figure(), 800, 400)

    plot_df = df[[value_col]].copy() if not group_col else df[[value_col, group_col]].copy()
    plot_df = plot_df.dropna(subset=[value_col])
    if plot_df.empty:
        return _fig_to_png(_placeholder_figure(), 800, 400)

    y_title = f"{value_col} ({unit})" if unit else value_col
    if group_col and group_col in plot_df.columns:
        fig = px.box(plot_df, x=group_col, y=value_col, points="outliers")
    else:
        fig = px.box(plot_df, y=value_col, points="outliers")

    fig.update_layout(
        **PLOTLY_THEME,
        title=title or f"Distribution — {value_col}",
        yaxis_title=y_title,
    )
    return _fig_to_png(fig, 800, 400)
