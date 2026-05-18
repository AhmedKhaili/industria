import hashlib
import io
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio  # noqa: F401 — export kaleido
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from state.schema import AgentState

logger = logging.getLogger(__name__)

_VERSION = "IndustrIA v2.1"
_MARGIN = 1.2 * cm
_CONTENT_WIDTH = A4[0] - 2 * _MARGIN

COULEURS = {
    "P1": colors.HexColor("#DC2626"),
    "P2": colors.HexColor("#EA580C"),
    "P3": colors.HexColor("#CA8A04"),
    "P4": colors.HexColor("#16A34A"),
    "header": colors.HexColor("#1E3A5F"),
    "light_blue": colors.HexColor("#EBF4FF"),
    "light_gray": colors.HexColor("#F8F9FA"),
    "border": colors.HexColor("#DEE2E6"),
    "text_dark": colors.HexColor("#212529"),
    "text_gray": colors.HexColor("#6C757D"),
    "success": colors.HexColor("#16A34A"),
    "warning": colors.HexColor("#CA8A04"),
    "danger": colors.HexColor("#DC2626"),
    "oapc_observer": colors.HexColor("#DBEAFE"),
    "oapc_analyser": colors.HexColor("#F1F5F9"),
    "oapc_prescrire": colors.HexColor("#FFEDD5"),
    "oapc_certifier": colors.HexColor("#DCFCE7"),
    "verdict_p1": colors.HexColor("#FEE2E2"),
    "verdict_p2": colors.HexColor("#FFEDD5"),
    "verdict_p3": colors.HexColor("#FEF9C3"),
    "verdict_p4": colors.HexColor("#DCFCE7"),
}

VERDICT_PRODUCTION = {
    "P1": {
        "bg": COULEURS["verdict_p1"],
        "border": COULEURS["P1"],
        "text": "ARRET PRODUCTION REQUIS",
        "style": "critical_text",
    },
    "P2": {
        "bg": COULEURS["verdict_p2"],
        "border": COULEURS["P2"],
        "text": (
            "PRODUCTION AUTORISEE avec surveillance renforcee. "
            "Intervention &lt; 30 min"
        ),
        "style": "warning_text",
    },
    "P3": {
        "bg": COULEURS["verdict_p3"],
        "border": COULEURS["P3"],
        "text": "PRODUCTION AUTORISEE — Surveillance requise",
        "style": "warning_text",
    },
    "P4": {
        "bg": COULEURS["verdict_p4"],
        "border": COULEURS["P4"],
        "text": "PRODUCTION NORMALE — Surveillance standard",
        "style": "body",
    },
}

DELAIS = {
    "P1": "ARRET IMMEDIAT requis",
    "P2": "Intervention &lt; 30 minutes",
    "P3": "Intervention &lt; 4 heures",
    "P4": "Prochaine maintenance planifiee",
}

RESPONSABLES: dict[str, Any] = {
    "P1": "Chef d'atelier + Responsable securite",
    "P2": {
        "operateur": "Technicien maintenance",
        "technicien": "Technicien maintenance",
        "ingenieur": "Ingenieur process",
        "directeur": "Directeur production",
    },
    "P3": "Technicien maintenance",
    "P4": "Operateur terrain",
}

CONFIDENCE_STYLES = {
    "haute": ("Confiance : HAUTE", COULEURS["verdict_p4"], COULEURS["P4"]),
    "moyenne": ("Confiance : MOYENNE", COULEURS["verdict_p2"], COULEURS["P3"]),
    "faible": ("Confiance : FAIBLE", COULEURS["verdict_p1"], COULEURS["P1"]),
}

_COUT_HORAIRE_DEFAULT = 500
_IMPACT_HEURES = {"P1": 8.0, "P2": 2.0, "P3": 0.5, "P4": 0.0}

_AGENT_CANONICAL = {
    "ZScoreSpecialist": "zscore",
    "zscore": "zscore",
    "SpcSpecialist": "spc",
    "spc": "spc",
    "EwmaCusumSpecialist": "ewma_cusum",
    "ewma_cusum": "ewma_cusum",
    "CpCpkSpecialist": "cp_cpk",
    "cp_cpk": "cp_cpk",
    "RegressionSpecialist": "regression",
    "regression": "regression",
    "MannKendallSpecialist": "mann_kendall",
    "mann_kendall": "mann_kendall",
    "AnovaKruskalSpecialist": "anova_kruskal",
    "anova_kruskal": "anova_kruskal",
    "PivotSpecialist": "pivot",
    "pivot": "pivot",
    "CorrelationSpecialist": "correlation",
    "correlation": "correlation",
    "FourierSpecialist": "fourier",
    "fourier": "fourier",
}

_TECHNICIAN_METRIC_KEYS = (
    "anomalies_count",
    "max_zscore",
    "pourcentage_anomalies",
    "sous_controle",
    "derive_detectee",
    "Cpk",
    "UCL_x",
    "hors_limites_x",
)


class _NumberedCanvas(pdf_canvas.Canvas):
    """Canvas that paints Page X / Y on every page after layout is known."""

    def __init__(self, *args, page_callback=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_states: list[dict] = []
        self._page_callback = page_callback

    def showPage(self) -> None:
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            if self._page_callback:
                self._page_callback(self, total)
            super().showPage()
        super().save()


class PDFReportAgent:
    """Agent 6c — premium industrial PDF (ReportLab + Plotly), no LLM."""

    def __init__(self) -> None:
        self._page_meta: dict[str, str] = {}
        self._total_pages: int = 1

    def _canonical_agent(self, agent_name: str | None) -> str:
        if not isinstance(agent_name, str):
            return ""
        return _AGENT_CANONICAL.get(agent_name, agent_name.strip())

    def _find_validated(
        self,
        validated_results: list[dict],
        specialist_name: str,
    ) -> dict | None:
        for item in validated_results:
            if not isinstance(item, dict):
                continue
            agent = item.get("agent", "")
            if agent == specialist_name:
                return item
            if self._canonical_agent(agent) == self._canonical_agent(specialist_name):
                return item
        return None

    def _priority_color(self, priority: str):
        return COULEURS.get(priority, COULEURS["P4"])

    def _get_responsable(self, priority: str, user_profile: str) -> str:
        entry = RESPONSABLES.get(priority, "Responsable atelier")
        if isinstance(entry, dict):
            return str(entry.get(user_profile, entry.get("technicien", "")))
        return str(entry)

    def _state_label(self, state: dict, *keys: str, default: str = "N/A") -> str:
        """Return first non-empty state value among keys."""
        for key in keys:
            value = state.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return default

    def _draw_page_frame(self, canv: pdf_canvas.Canvas, total_pages: int) -> None:
        """Header and footer on each page."""
        self._total_pages = max(1, total_pages)
        meta = self._page_meta
        page_num = canv.getPageNumber()
        w, h = A4

        canv.setStrokeColor(COULEURS["border"])
        canv.setLineWidth(0.4)
        canv.line(_MARGIN, h - 1.35 * cm, w - _MARGIN, h - 1.35 * cm)
        canv.line(_MARGIN, 1.15 * cm, w - _MARGIN, 1.15 * cm)

        canv.setFont("Helvetica", 8)
        canv.setFillColor(COULEURS["text_gray"])
        canv.drawString(_MARGIN, h - 1.05 * cm, _VERSION)
        canv.drawRightString(w - _MARGIN, h - 1.05 * cm, meta.get("datetime", ""))

        canv.drawCentredString(w / 2, 0.75 * cm, f"Page {page_num} / {total_pages}")
        canv.drawRightString(w - _MARGIN, 0.75 * cm, meta.get("sha_short", ""))

    def _build_styles(self) -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        header = COULEURS["header"]
        text_dark = COULEURS["text_dark"]
        text_gray = COULEURS["text_gray"]

        return {
            "title_main": ParagraphStyle(
                "title_main", parent=base["Title"],
                fontSize=22, leading=26, alignment=TA_CENTER,
                textColor=header, fontName="Helvetica-Bold", spaceAfter=2,
            ),
            "title_section": ParagraphStyle(
                "title_section", parent=base["Heading2"],
                fontSize=13, leading=16, textColor=header,
                fontName="Helvetica-Bold", spaceBefore=4, spaceAfter=4,
            ),
            "title_subsection": ParagraphStyle(
                "title_subsection", parent=base["Heading3"],
                fontSize=10, leading=13, textColor=text_dark,
                fontName="Helvetica-Bold", spaceBefore=2, spaceAfter=2,
            ),
            "body": ParagraphStyle(
                "body", parent=base["Normal"],
                fontSize=9.5, leading=12, alignment=TA_JUSTIFY, textColor=text_dark,
            ),
            "body_small": ParagraphStyle(
                "body_small", parent=base["Normal"],
                fontSize=8.5, leading=11, textColor=text_dark,
            ),
            "oapc_observer": ParagraphStyle(
                "oapc_observer", parent=base["Normal"],
                fontSize=8.5, leading=11, fontName="Helvetica-Oblique", textColor=text_dark,
            ),
            "oapc_prescrire": ParagraphStyle(
                "oapc_prescrire", parent=base["Normal"],
                fontSize=9, leading=12, fontName="Helvetica-Bold", textColor=text_dark,
            ),
            "caption": ParagraphStyle(
                "caption", parent=base["Normal"],
                fontSize=7.5, leading=9, alignment=TA_CENTER, textColor=text_gray,
            ),
            "warning_text": ParagraphStyle(
                "warning_text", parent=base["Normal"],
                fontSize=9.5, leading=12, textColor=COULEURS["warning"],
                fontName="Helvetica-Bold", alignment=TA_CENTER,
            ),
            "critical_text": ParagraphStyle(
                "critical_text", parent=base["Normal"],
                fontSize=10, leading=13, textColor=COULEURS["P1"],
                fontName="Helvetica-Bold", alignment=TA_CENTER,
            ),
            "badge_white": ParagraphStyle(
                "badge_white", parent=base["Normal"],
                fontSize=11, alignment=TA_CENTER, textColor=colors.white,
                fontName="Helvetica-Bold",
            ),
            "verdict_box": ParagraphStyle(
                "verdict_box", parent=base["Normal"],
                fontSize=10, leading=13, alignment=TA_CENTER,
                fontName="Helvetica-Bold", textColor=text_dark,
            ),
        }

    def _section_title(self, text: str, styles: dict) -> Paragraph:
        return Paragraph(text, styles["title_section"])

    def _thin_hr(self, color=None) -> HRFlowable:
        return HRFlowable(
            width="100%", thickness=0.5,
            color=color or COULEURS["border"],
            spaceBefore=2, spaceAfter=2,
        )

    def _production_verdict_box(self, priority: str, styles: dict) -> Table:
        """Binary production verdict encart under priority badge."""
        spec = VERDICT_PRODUCTION.get(priority, VERDICT_PRODUCTION["P4"])
        prefix = ""
        if priority == "P1":
            prefix = "ARRET — "
        elif priority == "P2":
            prefix = "ATTENTION — "
        elif priority in ("P3", "P4"):
            prefix = "OK — "

        text = prefix + spec["text"]
        style_key = spec.get("style", "body")
        cell = Paragraph(text, styles.get(style_key, styles["verdict_box"]))

        table = Table([[cell]], colWidths=[_CONTENT_WIDTH])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), spec["bg"]),
            ("BOX", (0, 0), (-1, -1), 1.2, spec["border"]),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        return table

    def _confidence_badge(self, confidence: str, styles: dict) -> Table | None:
        """Display pipeline confidence level badge."""
        if not confidence:
            return None
        key = str(confidence).strip().lower()
        spec = CONFIDENCE_STYLES.get(key)
        if not spec:
            return None
        label, bg, border = spec
        cell = Table(
            [[Paragraph(label, styles["badge_white"])]],
            colWidths=[5 * cm],
            hAlign="LEFT",
        )
        cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 1, border),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        return cell

    def _build_page_de_garde(
        self,
        state: dict,
        rapport_oapc: dict,
        styles: dict,
    ) -> list:
        priority = str(rapport_oapc.get("priority", "P4"))
        priority_color = self._priority_color(priority)
        question = str(state.get("question", ""))
        target = str(state.get("target_column", ""))
        user_profile = str(state.get("user_profile", "technicien"))
        now_display = self._page_meta.get("datetime", "")
        validated = state.get("validated_results", [])
        n_specialistes = len(validated) if isinstance(validated, list) else 0

        story: list = [
            Spacer(1, 0.4 * cm),
            Paragraph("IndustrIA", ParagraphStyle(
                "brand", parent=styles["title_main"], fontSize=26,
            )),
            self._thin_hr(priority_color),
            Paragraph("Rapport d'Analyse Industrielle", styles["title_main"]),
            Spacer(1, 0.25 * cm),
        ]

        badge = Table(
            [[Paragraph(f"PRIORITE {priority}", styles["badge_white"])]],
            colWidths=[5 * cm],
            hAlign="CENTER",
        )
        badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), priority_color),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.extend([
            badge,
            Spacer(1, 0.2 * cm),
            self._production_verdict_box(priority, styles),
            Spacer(1, 0.25 * cm),
        ])

        info_rows = [
            ["Date / heure", now_display],
            ["Question", question],
            ["Capteur", target],
            ["Profil", user_profile],
            ["Specialistes", str(n_specialistes)],
        ]
        info_table = Table(info_rows, colWidths=[4.5 * cm, _CONTENT_WIDTH - 4.5 * cm])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), COULEURS["text_gray"]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, -1), (-1, -1), 0.25, COULEURS["border"]),
        ]))
        story.append(info_table)

        context_rows = [
            ["Contexte machine", ""],
            ["N lot", self._state_label(state, "numero_lot", "num_lot", "lot_number")],
            ["Operateur", self._state_label(state, "operateur", "operator_name")],
            ["Recette active", self._state_label(state, "recette_active", "recette", "recipe")],
        ]
        ctx_table = Table(context_rows, colWidths=[4.5 * cm, _CONTENT_WIDTH - 4.5 * cm])
        ctx_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), COULEURS["light_gray"]),
            ("SPAN", (0, 0), (1, 0)),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BOX", (0, 0), (-1, -1), 0.5, COULEURS["border"]),
        ]))
        story.extend([Spacer(1, 0.2 * cm), ctx_table, PageBreak()])
        return story

    def _oapc_cell(self, label: str, text: str, styles: dict, bg_color) -> Table:
        label_p = Paragraph(f"<b>{label}</b>", styles["title_subsection"])
        if label == "OBSERVER":
            body_style = styles["oapc_observer"]
        elif label == "PRESCRIRE":
            body_style = styles["oapc_prescrire"]
        else:
            body_style = styles["body_small"]
        inner = Table(
            [[label_p], [Paragraph(text or "-", body_style)]],
            colWidths=[(_CONTENT_WIDTH / 4) - 0.25 * cm],
        )
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_color),
            ("BOX", (0, 0), (-1, -1), 0.5, COULEURS["border"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return inner

    def _build_section_resume(
        self,
        state: dict,
        resume_executif: str,
        rapport_oapc: dict,
        styles: dict,
    ) -> list:
        story: list = [self._section_title("1. Resume executif", styles)]

        conf_badge = self._confidence_badge(str(state.get("confidence", "")), styles)
        if conf_badge:
            story.extend([conf_badge, Spacer(1, 0.15 * cm)])

        story.append(Paragraph(resume_executif or "-", styles["body"]))

        col_w = _CONTENT_WIDTH / 4
        oapc_cells = [
            self._oapc_cell("OBSERVER", str(rapport_oapc.get("observer", "")), styles, COULEURS["oapc_observer"]),
            self._oapc_cell("ANALYSER", str(rapport_oapc.get("analyser", "")), styles, COULEURS["oapc_analyser"]),
            self._oapc_cell("PRESCRIRE", str(rapport_oapc.get("prescrire", "")), styles, COULEURS["oapc_prescrire"]),
            self._oapc_cell("CERTIFIER", str(rapport_oapc.get("certifier", "")), styles, COULEURS["oapc_certifier"]),
        ]
        oapc_row = Table([oapc_cells], colWidths=[col_w] * 4)
        oapc_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.extend([Spacer(1, 0.2 * cm), oapc_row])
        return story

    def _plotly_chart_bytes(self, state: dict) -> bytes | None:
        df = state.get("df_propre")
        target = state.get("target_column", "")
        if df is None or getattr(df, "empty", True):
            return None
        if not isinstance(target, str) or target not in df.columns:
            return None

        series = pd.to_numeric(df[target], errors="coerce")
        if series.notna().sum() < 3:
            return None

        x_values = (
            pd.to_datetime(df["timestamp"], errors="coerce")
            if "timestamp" in df.columns
            else pd.Series(range(len(df)), index=df.index)
        )

        rolling_mean = series.rolling(window=10, min_periods=1).mean()
        rolling_std = series.rolling(window=10, min_periods=1).std().fillna(0.0)
        ucl_2, lcl_2 = rolling_mean + 2 * rolling_std, rolling_mean - 2 * rolling_std
        ucl_3, lcl_3 = rolling_mean + 3 * rolling_std, rolling_mean - 3 * rolling_std

        figure = go.Figure()
        figure.add_trace(go.Scatter(
            x=x_values, y=lcl_3, mode="lines",
            line=dict(color="rgba(0,0,0,0)"), showlegend=False, hoverinfo="skip",
        ))
        figure.add_trace(go.Scatter(
            x=x_values, y=ucl_3, mode="lines", fill="tonexty",
            fillcolor="rgba(220,38,38,0.15)",
            line=dict(width=0), name="Zone +/-3 sigma",
        ))
        figure.add_trace(go.Scatter(
            x=x_values, y=lcl_2, mode="lines",
            line=dict(color="rgba(0,0,0,0)"), showlegend=False, hoverinfo="skip",
        ))
        figure.add_trace(go.Scatter(
            x=x_values, y=ucl_2, mode="lines", fill="tonexty",
            fillcolor="rgba(0,128,0,0.15)",
            line=dict(width=0), name="Zone +/-2 sigma",
        ))
        figure.add_trace(go.Scatter(
            x=x_values, y=series, mode="lines", name=target,
            line=dict(color="#1D4ED8", width=2),
        ))
        figure.add_trace(go.Scatter(
            x=x_values, y=rolling_mean, mode="lines",
            name="Moyenne mobile (10)",
            line=dict(color="#64748B", width=1.5, dash="dash"),
        ))

        df_anomalies = state.get("df_anomalies")
        if (
            df_anomalies is not None
            and not getattr(df_anomalies, "empty", True)
            and target in df_anomalies.columns
        ):
            anomaly_y = pd.to_numeric(df_anomalies[target], errors="coerce")
            anomaly_x = (
                pd.to_datetime(df_anomalies["timestamp"], errors="coerce")
                if "timestamp" in df_anomalies.columns
                else df_anomalies.index
            )
            figure.add_trace(go.Scatter(
                x=anomaly_x, y=anomaly_y, mode="markers", name="Anomalies",
                marker=dict(color="#DC2626", size=11, symbol="x", line=dict(width=2)),
            ))

        figure.update_layout(
            template="plotly_white",
            paper_bgcolor="white",
            plot_bgcolor="white",
            xaxis_title="Temps",
            yaxis_title=f"{target} (valeur brute)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=1),
            margin=dict(l=44, r=20, t=36, b=40),
            width=800,
            height=400,
        )

        try:
            return figure.to_image(format="png", scale=2)
        except Exception:
            logger.exception("Plotly/kaleido PNG export failed")
            return None

    def _build_section_graphique(
        self,
        state: dict,
        styles: dict,
    ) -> list:
        block: list = [self._section_title("2. Graphique principal", styles)]
        png_bytes = self._plotly_chart_bytes(state)

        if png_bytes:
            chart = Image(io.BytesIO(png_bytes), width=_CONTENT_WIDTH, height=8 * cm)
            legend = Paragraph(
                "Zone verte +/-2 sigma = variation normale. "
                "Zone rouge +/-3 sigma = hors controle. "
                "Croix rouges = anomalies detectees.",
                styles["caption"],
            )
            return block + [KeepTogether([chart, legend])]

        block.append(Paragraph(
            "Donnees insuffisantes pour generer le graphique.",
            styles["body"],
        ))
        return block

    def _format_metric_value(self, key: str, value: Any) -> list[tuple[str, str]]:
        """Expand one metric into human-readable rows (no raw dict JSON)."""
        if key == "tendance" and isinstance(value, dict):
            rows = []
            if "direction" in value:
                rows.append(("tendance_direction", str(value["direction"])))
            if "slope" in value:
                rows.append(("tendance_pente", f"{value['slope']:.4f}"))
            if "significative" in value:
                rows.append(("tendance_significative", str(value["significative"])))
            return rows or [("tendance", "presente")]

        if key == "ewma" and isinstance(value, dict):
            rows = []
            if "alertes_count" in value:
                rows.append(("ewma_alertes", str(value["alertes_count"])))
            if "premier_alerte" in value:
                rows.append(("ewma_premiere_alerte", str(value["premier_alerte"])))
            return rows or [("ewma", "alerte active")]

        if key == "meilleure_variable" and isinstance(value, dict):
            rows = []
            if "variable" in value:
                rows.append(("variable", str(value["variable"])))
            if "r_squared" in value:
                rows.append(("r_squared", f"{value['r_squared']:.4f}"))
            return rows

        if key == "global" and isinstance(value, dict):
            return [(f"global_{k}", str(v)) for k, v in value.items() if k in ("mean", "std", "min", "max")]

        if key == "hors_limites_x" and isinstance(value, list):
            return [("hors_limites_x", f"{len(value)} points")]

        if key == "correlation_max" and isinstance(value, dict):
            rows = []
            for sub in ("colonne", "pearson_r", "spearman_r"):
                if sub in value:
                    rows.append((f"correlation_{sub}", str(value[sub])))
            return rows

        if isinstance(value, bool):
            return [(key, "Oui" if value else "Non")]

        if isinstance(value, list):
            return [(key, f"{len(value)} elements")]

        if isinstance(value, dict):
            return [(key, "voir detail annexe")]

        return [(key, str(value))]

    def _flatten_metrics_formatted(self, payload: dict) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        if not isinstance(payload, dict):
            return rows
        for key, value in payload.items():
            rows.extend(self._format_metric_value(key, value))
        return rows

    def _verdict_row(self, validated: dict | None) -> tuple[str, str]:
        if not validated:
            return ("Verdict", "Non determine")
        payload = validated.get("result", {})
        if not isinstance(payload, dict):
            return ("Anomalie", "Non")
        if payload.get("anomalie_process_count", 0) or payload.get("anomalies_count", 0):
            return ("Anomalie", "Oui")
        if payload.get("derive_detectee") or not payload.get("sous_controle", True):
            return ("Anomalie", "Oui")
        return ("Anomalie", "Non")

    def _directeur_rows(self, rapport_oapc: dict) -> list[tuple[str, str]]:
        priority = rapport_oapc.get("priority", "P4")
        rows = [("Priorite", str(priority))]
        if priority in ("P1", "P2"):
            rows.append(("Impact", "Risque conformite EN9100 / TRS"))
        else:
            rows.append(("Impact", "Surveillance standard"))
        return rows[:2]

    def _technician_rows(self, payload: dict) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for key in _TECHNICIAN_METRIC_KEYS:
            if key not in payload:
                continue
            rows.extend(self._format_metric_value(key, payload[key]))
            if len(rows) >= 3:
                return rows[:3]
        return rows[:3] if rows else self._flatten_metrics_formatted(payload)[:3]

    def _metrics_table(self, rows: list[tuple[str, str]], styles: dict) -> Table | None:
        if not rows:
            return None
        data = [["Metrique", "Valeur"]] + [[k, v] for k, v in rows]
        table = Table(data, colWidths=[5.5 * cm, _CONTENT_WIDTH - 5.5 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COULEURS["light_gray"]),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.25, COULEURS["border"]),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COULEURS["light_blue"]]),
        ]))
        return table

    def _top3_anomalies_table(self, state: dict, styles: dict) -> Table | None:
        """Top 3 anomalies with timestamp from df_anomalies."""
        df_anomalies = state.get("df_anomalies")
        target = state.get("target_column", "")
        if (
            df_anomalies is None
            or getattr(df_anomalies, "empty", True)
            or not isinstance(target, str)
            or target not in df_anomalies.columns
        ):
            return None

        work = df_anomalies.head(3).copy()
        rows = [["Timestamp", "Valeur", "Type anomalie"]]
        for _, row in work.iterrows():
            ts = row.get("timestamp", "")
            if hasattr(ts, "strftime"):
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts_str = str(ts)
            val = row.get(target, "")
            try:
                val_str = f"{float(val):.2f}"
            except (TypeError, ValueError):
                val_str = str(val)
            rows.append([ts_str, val_str, "Process"])

        if len(rows) <= 1:
            return None

        table = Table(rows, colWidths=[6 * cm, 4 * cm, _CONTENT_WIDTH - 10 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COULEURS["header"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.25, COULEURS["border"]),
        ]))
        return table

    def _build_section_interpretations(
        self,
        state: dict,
        interpretations: dict,
        validated_results: list,
        user_profile: str,
        styles: dict,
        rapport_oapc: dict,
    ) -> list:
        story: list = [
            PageBreak(),
            self._section_title("3. Interpretations", styles),
        ]
        if not interpretations:
            story.append(Paragraph("Aucune interpretation disponible.", styles["body"]))
            return story

        for specialist_name, interpretation_text in interpretations.items():
            validated = self._find_validated(validated_results, specialist_name)
            judge_ok = bool(validated.get("judge_valid", True)) if validated else True

            block: list = [
                Paragraph(specialist_name, styles["title_subsection"]),
            ]

            if not judge_ok:
                block.append(Paragraph(
                    "Resultat non retenu",
                    styles["critical_text"],
                ))
            else:
                block.append(Paragraph(str(interpretation_text), styles["body"]))
                payload = {}
                if validated and isinstance(validated.get("result"), dict):
                    payload = validated["result"]

                metric_rows: list[tuple[str, str]] = []
                if user_profile == "operateur":
                    metric_rows = [self._verdict_row(validated)]
                elif user_profile == "technicien":
                    metric_rows = self._technician_rows(payload)
                elif user_profile == "ingenieur":
                    metric_rows = self._flatten_metrics_formatted(payload)
                elif user_profile == "directeur":
                    metric_rows = [self._verdict_row(validated)]
                    metric_rows.extend(self._directeur_rows(rapport_oapc))

                metrics_table = self._metrics_table(metric_rows, styles)
                if metrics_table:
                    block.append(metrics_table)

                if (
                    judge_ok
                    and self._canonical_agent(specialist_name) == "zscore"
                ):
                    top3 = self._top3_anomalies_table(state, styles)
                    if top3:
                        block.extend([
                            Paragraph("Top 3 anomalies", styles["title_subsection"]),
                            top3,
                        ])

            block.append(self._thin_hr())
            story.append(KeepTogether(block))

        return story

    def _compute_causes(self, validated_results: list[dict]) -> list[dict]:
        causes: list[dict] = []
        for item in validated_results:
            if not isinstance(item, dict) or item.get("status") != "success":
                continue
            if item.get("judge_valid") is False:
                continue
            agent = self._canonical_agent(item.get("agent"))
            payload = item.get("result", {})
            if not isinstance(payload, dict):
                continue

            if agent == "zscore":
                total = float(payload.get("total_points", 0) or 0)
                process_count = float(payload.get("anomalie_process_count", 0) or 0)
                bruit_count = float(payload.get("bruit_capteur_count", 0) or 0)
                pct = float(payload.get("pourcentage_anomalies", 0) or 0)
                if process_count > 0:
                    causes.append({
                        "cause": "Anomalie process detectee",
                        "indice": round(min(pct * 2, 85), 1),
                        "agent": agent,
                    })
                if bruit_count > 0 and total > 0:
                    causes.append({
                        "cause": "Bruit capteur",
                        "indice": round(min(bruit_count / total * 100, 60), 1),
                        "agent": agent,
                    })
            elif agent == "spc" and not bool(payload.get("sous_controle", True)):
                causes.append({
                    "cause": "Processus hors controle SPC",
                    "indice": 75.0,
                    "agent": agent,
                })
            elif agent == "ewma_cusum" and bool(payload.get("derive_detectee", False)):
                causes.append({
                    "cause": "Derive progressive EWMA/CUSUM",
                    "indice": 70.0,
                    "agent": agent,
                })
            elif agent == "cp_cpk":
                cpk = float(payload.get("Cpk", 999))
                if cpk < 1.33:
                    causes.append({
                        "cause": "Capabilite insuffisante",
                        "indice": 80.0,
                        "agent": agent,
                    })
            elif agent == "regression":
                meilleure = payload.get("meilleure_variable")
                if isinstance(meilleure, dict):
                    variable = meilleure.get("variable", "")
                    r_squared = float(meilleure.get("r_squared", 0) or 0)
                    if variable and r_squared > 0.5:
                        causes.append({
                            "cause": f"Correlation avec {variable}",
                            "indice": round(min(r_squared * 100, 95), 1),
                            "agent": agent,
                        })

        causes.sort(key=lambda row: row["indice"], reverse=True)
        return causes[:5]

    def _confidence_bar(self, score: float) -> Table:
        score = max(0.0, min(float(score), 100.0))
        bar_color = COULEURS["P4"]
        if score < 50:
            bar_color = COULEURS["P1"]
        elif score < 75:
            bar_color = COULEURS["P3"]

        filled = max(0.05 * cm, (score / 100.0) * 5 * cm)
        empty = max(0.05 * cm, 5 * cm - filled)
        bar = Table([["", ""]], colWidths=[filled, empty], rowHeights=[0.4 * cm])
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), bar_color),
            ("BACKGROUND", (1, 0), (1, 0), COULEURS["light_gray"]),
            ("BOX", (0, 0), (-1, -1), 0.25, COULEURS["border"]),
        ]))
        return bar

    def _build_section_causes(
        self,
        validated_results: list,
        styles: dict,
    ) -> list:
        story: list = [
            Spacer(1, 0.15 * cm),
            self._section_title("4. Causes probables", styles),
        ]
        causes = self._compute_causes(validated_results)

        if not causes:
            story.append(Paragraph(
                "Aucune cause identifiee automatiquement.",
                styles["body"],
            ))
        else:
            table_data = [["Cause", "Indice de confiance (/100)", "Agent"]]
            for item in causes:
                indice = float(item.get("indice", 0))
                bar_cell = Table(
                    [
                        [self._confidence_bar(indice)],
                        [Paragraph(f"{indice:.0f}", styles["caption"])],
                    ],
                    colWidths=[5.2 * cm],
                )
                table_data.append([
                    item.get("cause", ""),
                    bar_cell,
                    item.get("agent", ""),
                ])
            cause_table = Table(
                table_data,
                colWidths=[7.8 * cm, 5.5 * cm, 2.2 * cm],
            )
            cause_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), COULEURS["header"]),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.25, COULEURS["border"]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COULEURS["light_gray"]]),
            ]))
            story.append(cause_table)

        story.append(Paragraph(
            "<i>Scores independants par methode. Ne se somment pas.</i>",
            styles["caption"],
        ))
        return story

    def _estimate_financial_impact(self, priority: str) -> tuple[float, float]:
        heures = _IMPACT_HEURES.get(priority, 0.0)
        impact = _COUT_HORAIRE_DEFAULT * heures
        return impact, heures

    def _build_section_recommandation(
        self,
        rapport_oapc: dict,
        user_profile: str,
        styles: dict,
    ) -> list:
        priority = str(rapport_oapc.get("priority", "P4"))
        priority_color = self._priority_color(priority)
        prescrire = str(rapport_oapc.get("prescrire", ""))

        story: list = [
            Spacer(1, 0.15 * cm),
            self._section_title("5. Recommandation", styles),
        ]

        prescrire_table = Table(
            [[Paragraph(prescrire or "-", ParagraphStyle(
                "prescrire_big", parent=styles["oapc_prescrire"],
                fontSize=11, leading=14,
            ))]],
            colWidths=[_CONTENT_WIDTH],
        )
        prescrire_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COULEURS["light_blue"]),
            ("BOX", (0, 0), (-1, -1), 1, priority_color),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(prescrire_table)

        delai = DELAIS.get(priority, DELAIS["P4"])
        responsable = self._get_responsable(priority, user_profile)
        delay_table = Table(
            [["Delai", delai], ["Responsable", responsable]],
            colWidths=[3.5 * cm, _CONTENT_WIDTH - 3.5 * cm],
        )
        delay_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, COULEURS["border"]),
            ("BACKGROUND", (0, 0), (0, -1), COULEURS["light_gray"]),
        ]))
        story.append(delay_table)

        impact, heures = self._estimate_financial_impact(priority)
        if heures > 0:
            story.append(Paragraph(
                f"<b>Impact estime si non traite :</b> {impact:,.0f} EUR "
                f"(arret ligne estime {heures:.1f} h).",
                styles["body"],
            ))
            story.append(Paragraph(
                "<i>Estimation indicative. Adapter au cout reel de l'usine.</i>",
                styles["caption"],
            ))

        if priority in ("P1", "P2"):
            alert = styles["critical_text"] if priority == "P1" else styles["warning_text"]
            story.append(Paragraph("ACTION REQUISE IMMEDIATEMENT", alert))

        return story

    def _build_section_annexe(
        self,
        validated_results: list,
        user_profile: str,
        styles: dict,
    ) -> list:
        if user_profile in ("operateur", "directeur"):
            return []

        story: list = [
            PageBreak(),
            self._section_title("6. Annexe technique", styles),
        ]

        if user_profile == "technicien":
            for item in validated_results:
                if not isinstance(item, dict) or item.get("status") != "success":
                    continue
                agent_name = str(item.get("agent", ""))
                if item.get("judge_valid") is False:
                    story.append(Paragraph(
                        f"<b>{agent_name}</b> — Resultat non retenu",
                        styles["title_subsection"],
                    ))
                    continue
                payload = item.get("result", {})
                if not isinstance(payload, dict):
                    payload = {}
                story.append(Paragraph(f"<b>{agent_name}</b>", styles["title_subsection"]))
                table = self._metrics_table(self._technician_rows(payload), styles)
                if table:
                    story.append(table)

        elif user_profile == "ingenieur":
            for item in validated_results:
                if not isinstance(item, dict):
                    continue
                agent_name = str(item.get("agent", ""))
                if item.get("judge_valid") is False:
                    story.append(Paragraph(
                        f"<b>{agent_name}</b> — Resultat non retenu",
                        styles["title_subsection"],
                    ))
                    continue
                payload = item.get("result", {})
                if not isinstance(payload, dict):
                    payload = {}
                story.append(Paragraph(f"<b>{agent_name}</b>", styles["title_subsection"]))
                table = self._metrics_table(self._flatten_metrics_formatted(payload), styles)
                if table:
                    story.append(table)

        return story

    def _compute_sha256(
        self,
        state: dict,
        rapport_oapc: dict,
        resume_executif: str,
        timestamp: str,
    ) -> str:
        hash_payload = {
            "question": state.get("question", ""),
            "target_column": state.get("target_column", ""),
            "priority": rapport_oapc.get("priority", "P4"),
            "timestamp": timestamp,
            "rapport_oapc": rapport_oapc,
            "resume_executif": resume_executif,
        }
        return hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, ensure_ascii=False).encode(),
        ).hexdigest()

    def _signature_table(self, styles: dict) -> Table:
        """Two-column signature block with drawn lines, min 3 cm height."""

        def signature_column(title: str) -> Table:
            line = Table([[""]], colWidths=[6.8 * cm], rowHeights=[0.55 * cm])
            line.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.75, colors.black),
            ]))
            rows = [
                [Paragraph(f"<b>{title}</b>", styles["title_subsection"])],
                [Paragraph("Nom :", styles["body_small"])],
                [line],
                [Paragraph("Date :", styles["body_small"])],
                [line],
                [Paragraph("Signature :", styles["body_small"])],
                [line],
            ]
            col = Table(rows, colWidths=[7 * cm])
            col.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("MINHEIGHT", (0, 0), (-1, -1), 3 * cm),
            ]))
            return col

        outer = Table(
            [[signature_column("Operateur terrain"), signature_column("Responsable qualite")]],
            colWidths=[8.3 * cm, 8.3 * cm],
        )
        outer.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
        return outer

    def _build_section_tracabilite(
        self,
        state: dict,
        rapport_oapc: dict,
        styles: dict,
        sha256: str,
        timestamp: str,
    ) -> list:
        validated = state.get("validated_results", [])
        if not isinstance(validated, list):
            validated = []
        agents_called = state.get("agents_called", [])
        if not isinstance(agents_called, list):
            agents_called = []

        story: list = [
            Spacer(1, 0.15 * cm),
            self._section_title("7. Tracabilite EN9100", styles),
        ]

        trace_rows = [
            ["Champ", "Valeur"],
            ["Version", _VERSION],
            ["Horodatage", timestamp],
            ["Question", str(state.get("question", ""))],
            ["Cible", str(state.get("target_column", ""))],
            ["Priorite", str(rapport_oapc.get("priority", "P4"))],
            ["Profil", str(state.get("user_profile", ""))],
            ["N specialistes", str(len(validated))],
            ["Agents appeles", ", ".join(str(a) for a in agents_called[:14])],
            ["SHA-256", sha256],
        ]
        trace_table = Table(trace_rows, colWidths=[4.8 * cm, _CONTENT_WIDTH - 4.8 * cm])
        trace_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COULEURS["header"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.25, COULEURS["border"]),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COULEURS["light_gray"]]),
        ]))
        story.extend([trace_table, Spacer(1, 0.2 * cm), self._signature_table(styles)])
        return story

    def run(self, state: AgentState | dict) -> dict:
        start_time = time.time()
        sha256 = ""

        try:
            if not isinstance(state, dict):
                raise TypeError("state must be a dict")

            rapport_oapc = state.get("rapport_oapc", {})
            if not isinstance(rapport_oapc, dict) or not rapport_oapc:
                return {
                    "agent": "agent_6c_pdf",
                    "status": "error",
                    "pdf_path": "",
                    "pages": 0,
                    "sha256": "",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                    "error": "rapport_oapc absent — executer Agent 5 avant le PDF",
                }

            resume_executif = str(state.get("resume_executif", "") or "")
            interpretations = state.get("interpretations", {})
            if not isinstance(interpretations, dict):
                interpretations = {}
            validated_results = state.get("validated_results", [])
            if not isinstance(validated_results, list):
                validated_results = []
            user_profile = str(state.get("user_profile", "technicien"))

            timestamp = datetime.now().isoformat(timespec="milliseconds")
            sha256 = self._compute_sha256(state, rapport_oapc, resume_executif, timestamp)
            self._page_meta = {
                "datetime": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "sha_short": f"SHA {sha256[:8]}",
            }

            styles = self._build_styles()
            story: list = []
            story.extend(self._build_page_de_garde(state, rapport_oapc, styles))
            story.extend(self._build_section_resume(state, resume_executif, rapport_oapc, styles))
            story.extend(self._build_section_graphique(state, styles))
            story.extend(self._build_section_interpretations(
                state, interpretations, validated_results, user_profile, styles, rapport_oapc,
            ))
            story.extend(self._build_section_causes(validated_results, styles))
            story.extend(self._build_section_recommandation(rapport_oapc, user_profile, styles))

            annexe = self._build_section_annexe(validated_results, user_profile, styles)
            if annexe:
                story.extend(annexe)

            story.extend(self._build_section_tracabilite(
                state, rapport_oapc, styles, sha256, timestamp,
            ))

            output_dir = _ROOT / "outputs"
            output_dir.mkdir(exist_ok=True)
            output_path = str(
                output_dir / f"rapport_industria_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            )

            doc = SimpleDocTemplate(
                output_path,
                pagesize=A4,
                rightMargin=_MARGIN,
                leftMargin=_MARGIN,
                topMargin=1.55 * cm,
                bottomMargin=1.45 * cm,
                title="Rapport IndustrIA",
                author=_VERSION,
            )

            def page_callback(canv: pdf_canvas.Canvas, total: int) -> None:
                self._draw_page_frame(canv, total)

            doc.build(
                story,
                canvasmaker=lambda *a, **kw: _NumberedCanvas(
                    *a, page_callback=page_callback, **kw,
                ),
            )
            pages = self._total_pages

            state["pdf_path"] = output_path
            agents = state.setdefault("agents_called", [])
            if "agent_6c_pdf" not in agents:
                agents.append("agent_6c_pdf")

            return {
                "agent": "agent_6c_pdf",
                "status": "success",
                "pdf_path": output_path,
                "pages": pages,
                "sha256": sha256,
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "error": None,
            }
        except Exception as exc:
            logger.exception("agent_6c_pdf failed")
            if isinstance(state, dict):
                state.setdefault("errors", []).append(str(exc))
            return {
                "agent": "agent_6c_pdf",
                "status": "error",
                "pdf_path": "",
                "pages": 0,
                "sha256": sha256,
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    np.random.seed(42)
    n = 100

    df_test = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="1min"),
        "inducteur_1": np.concatenate([
            np.random.normal(100, 5, 80),
            np.random.normal(130, 5, 20),
        ]),
    })

    df_anomalies = df_test[df_test["inducteur_1"] > 115].copy()

    state_test = {
        "question": "Y a-t-il des anomalies sur les capteurs ?",
        "target_column": "inducteur_1",
        "user_profile": "ingenieur",
        "confidence": "haute",
        "numero_lot": "LOT-2026-0142",
        "operateur": "Martin D.",
        "recette_active": "Cuisson_A3",
        "agents_called": [
            "agent_1", "agent_2", "agent_3",
            "ZScoreSpecialist", "SpcSpecialist", "EwmaCusumSpecialist",
            "statistician_judge", "agent_5", "agent_6a", "agent_6b",
        ],
        "df_propre": df_test,
        "df_anomalies": df_anomalies,
        "rapport_oapc": {
            "observer": "13 anomalies detectees sur inducteur_1.",
            "analyser": "max_zscore de 4.7 indique une anomalie significative.",
            "prescrire": (
                "Intervention dans les 30 minutes. "
                "Verifier le capteur concerne."
            ),
            "certifier": "IndustrIA v2.1 | inducteur_1 | P2",
            "priority": "P2",
            "goal": "detection_anomalies",
            "user_profile": "ingenieur",
        },
        "resume_executif": (
            "L'analyse multi-methodes de l'inducteur 1 "
            "confirme des anomalies P2. "
            "Intervention requise sous 30 minutes."
        ),
        "interpretations": {
            "ZScoreSpecialist": (
                "13 anomalies process detectees sur inducteur_1, zscore max 4.7."
            ),
            "SpcSpecialist": (
                "3 points depassent UCL=115.2. Processus hors controle."
            ),
            "EwmaCusumSpecialist": (
                "Derive progressive confirmee depuis 2026-01-01 01:20."
            ),
        },
        "validated_results": [
            {
                "agent": "ZScoreSpecialist",
                "status": "success",
                "judge_valid": True,
                "result": {
                    "anomalies_count": 13,
                    "bruit_capteur_count": 2,
                    "anomalie_process_count": 11,
                    "max_zscore": 4.7,
                    "pourcentage_anomalies": 13.0,
                    "total_points": 100,
                },
            },
            {
                "agent": "SpcSpecialist",
                "status": "success",
                "judge_valid": True,
                "result": {
                    "sous_controle": False,
                    "hors_limites_x": [8, 12, 15],
                    "UCL_x": 115.2,
                    "LCL_x": 84.8,
                },
            },
            {
                "agent": "EwmaCusumSpecialist",
                "status": "success",
                "judge_valid": True,
                "result": {
                    "derive_detectee": True,
                    "tendance": {
                        "direction": "hausse progressive",
                        "significative": True,
                        "slope": 0.106,
                    },
                    "ewma": {"alertes_count": 55},
                },
            },
        ],
        "judge_warnings": ["Ne doit pas apparaitre dans le PDF"],
    }

    agent = PDFReportAgent()
    result = agent.run(state_test)

    print(f"Status   : {result['status']}")
    print(f"PDF      : {result['pdf_path']}")
    print(f"Pages    : {result['pages']}")
    print(f"SHA-256  : {result['sha256'][:32]}...")
    print(f"Temps    : {result['execution_time_ms']}ms")

    if result["status"] == "success":
        print(f"\nPDF genere -> {result['pdf_path']}")
