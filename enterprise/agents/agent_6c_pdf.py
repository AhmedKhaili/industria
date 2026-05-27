"""
Agent 6c — constructeur PDF premium 12 sections (ReportLab).
Python pur — zéro LLM.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
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

from data.config import OLLAMA_CONFIG
from enterprise.report.charts import build_timeseries
from enterprise.report.formatters import (
    format_dict,
    format_list,
    format_number,
    format_percentage,
    format_timestamp,
    format_value,
    sanitize_for_pdf,
)
from enterprise.report.styles import (
    COLORS,
    PAGE_MARGIN,
    build_styles,
    draw_footer,
    draw_header,
    get_table_style,
)

logger = logging.getLogger(__name__)

_VERSION = "IndustrIA v2.1"
_CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN
_TOP_MARGIN = PAGE_MARGIN + 14 * mm
_BOTTOM_MARGIN = PAGE_MARGIN + 12 * mm

_VERDICT_TEXT = {
    "P4": ("✅ GO — Procédé sous contrôle", "verdict_go"),
    "P3": ("⚠️ SURVEILLANCE REQUISE", "verdict_go"),
    "P2": ("🔴 INTERVENTION URGENTE", "verdict_nogo"),
    "P1": ("🛑 ARRÊT IMMÉDIAT", "verdict_nogo"),
}

_DELAIS = {
    "P1": "Immédiat",
    "P2": "< 30 minutes",
    "P3": "< 4 heures",
    "P4": "Prochaine maintenance",
}

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

_CAUSES_NOTE = "Scores indépendants /100 — ne somment pas à 100%"


class _NumberedCanvas(pdf_canvas.Canvas):
    """Canvas pour en-tête/pied avec numéro de page total."""

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
            pdf_canvas.Canvas.showPage(self)
        pdf_canvas.Canvas.save(self)


class Agent6cPDF:
    """Assemble le rapport PDF premium 12 sections depuis l'AgentState."""

    def __init__(self) -> None:
        self.styles = build_styles()
        self._total_pages = 1
        self._doc_ref: SimpleDocTemplate | None = None
        self._header_meta = {
            "title": "Rapport d'Analyse Industrielle",
            "machine": "N/A",
            "timestamp": format_timestamp(datetime.now()),
        }

    def run(self, state: dict) -> dict:
        """
        Génère le PDF rapport et retourne chemin + bytes.

        Returns:
            dict: pdf_path, pdf_bytes, n_pages, sections_built, error.
        """
        result = {
            "pdf_path": "",
            "pdf_bytes": b"",
            "n_pages": 0,
            "sections_built": [],
            "error": None,
        }
        try:
            if not isinstance(state, dict):
                raise TypeError("state doit être un dict")

            priority = self._priority(state)
            target = self._target(state)
            ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
            reports_dir = _ROOT / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            safe_target = "".join(c if c.isalnum() or c in "-_" else "_" for c in target)[:40]
            output_path = str(
                reports_dir / f"rapport_{safe_target}_{ts_slug}_{priority}.pdf"
            )

            build_info = self._build_pdf(state, output_path)
            result["pdf_path"] = output_path
            result["n_pages"] = build_info.get("n_pages", self._total_pages)
            result["sections_built"] = build_info.get("sections_built", [])

            try:
                with open(output_path, "rb") as fh:
                    result["pdf_bytes"] = fh.read()
            except OSError as exc:
                logger.warning("Lecture pdf_bytes impossible : %s", exc)

            state["pdf_path"] = output_path
            return result
        except Exception as exc:
            logger.exception("Agent6cPDF.run failed")
            result["error"] = str(exc)
            return result

    def _build_pdf(self, state: dict, output_path: str) -> dict:
        """Construit le document PDF complet."""
        self._header_meta = {
            "title": "Rapport d'Analyse Industrielle",
            "machine": format_value(state.get("machine_id", "default")),
            "timestamp": format_timestamp(datetime.now()),
        }

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=PAGE_MARGIN,
            leftMargin=PAGE_MARGIN,
            topMargin=_TOP_MARGIN,
            bottomMargin=_BOTTOM_MARGIN,
            title="Rapport IndustrIA",
            author=_VERSION,
        )
        self._doc_ref = doc

        story: list = []
        sections_built: list[str] = []

        section_builders = [
            ("S1_garde", self._section_1_garde),
            ("S2_resume", self._section_2_resume),
            ("S3_kpis", self._section_3_kpis),
            ("S4_graphique", self._section_4_graphique),
            ("S5_tendance", self._section_5_tendance),
            ("S6_interpretations", self._section_6_interpretations),
            ("S7_causes", self._section_7_causes),
            ("S8_heatmap", self._section_8_heatmap),
            ("S9_financier", self._section_9_financier),
            ("S10_recommandations", self._section_10_recommandations),
            ("S11_annexe", self._section_11_annexe),
            ("S12_tracabilite", self._section_12_tracabilite),
        ]

        for name, builder in section_builders:
            block = self._safe_section(name, builder, state)
            if block:
                story.extend(block)
                sections_built.append(name)

        if not story:
            story.append(
                Paragraph(
                    "Rapport vide — données insuffisantes.",
                    self.styles["body"],
                )
            )

        def page_callback(canv: pdf_canvas.Canvas, total: int) -> None:
            self._total_pages = max(1, total)
            draw_header(
                canv,
                self._doc_ref,
                self._header_meta["title"],
                self._header_meta["machine"],
                self._header_meta["timestamp"],
            )
            draw_footer(canv, self._doc_ref, canv.getPageNumber(), total)

        doc.build(
            story,
            canvasmaker=lambda *a, **kw: _NumberedCanvas(
                *a, page_callback=page_callback, **kw
            ),
        )

        return {"n_pages": self._total_pages, "sections_built": sections_built}

    def _safe_section(self, name: str, builder, state: dict) -> list:
        try:
            items = builder(state)
            return items if items is not None else []
        except Exception as exc:
            logger.exception("Section %s failed", name)
            return [
                Paragraph(
                    sanitize_for_pdf(f"Section indisponible ({name})."),
                    self.styles["body"],
                ),
                Spacer(1, 4 * mm),
            ]

    # ── Helpers ───────────────────────────────────────────

    def _priority(self, state: dict) -> str:
        p = str(state.get("priority") or state.get("rapport_oapc", {}).get("priority", "P4"))
        return p.upper() if p.upper() in ("P1", "P2", "P3", "P4") else "P4"

    def _target(self, state: dict) -> str:
        return str(
            state.get("target_column")
            or state.get("intention", {}).get("target_col", "capteur")
        )

    def _profile(self, state: dict) -> str:
        p = str(state.get("user_profile", "technicien")).lower()
        return p if p in ("operateur", "technicien", "ingenieur", "directeur") else "technicien"

    def _rapport_oapc(self, state: dict) -> dict:
        r = state.get("rapport_oapc", {})
        return r if isinstance(r, dict) else {}

    def _h1(self, text: str) -> Paragraph:
        return Paragraph(sanitize_for_pdf(text), self.styles["h1"])

    def _body(self, text: str) -> Paragraph:
        return Paragraph(sanitize_for_pdf(text), self.styles["body"])

    def _caption(self, text: str) -> Paragraph:
        return Paragraph(sanitize_for_pdf(text), self.styles["caption"])

    def _placeholder(self, text: str) -> list:
        return [
            Spacer(1, 2 * mm),
            self._body(text),
            Spacer(1, 4 * mm),
        ]

    def _image_png(
        self,
        png_bytes: bytes | None,
        width_mm: float,
        height_mm: float,
    ) -> Any | None:
        if not png_bytes:
            return None
        try:
            return Image(
                io.BytesIO(png_bytes),
                width=width_mm * mm,
                height=height_mm * mm,
            )
        except Exception as exc:
            logger.warning("Image PNG invalide : %s", exc)
            return None

    def _simple_table(
        self,
        rows: list[list],
        col_widths: list[float] | None = None,
        style_name: str = "TABLE_ROW",
    ) -> Table:
        if col_widths is None:
            n = max(len(r) for r in rows)
            col_widths = [_CONTENT_WIDTH / n] * n
        tbl = Table(rows, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(get_table_style(style_name))
        return tbl

    def _canonical_agent(self, name: str | None) -> str:
        if not isinstance(name, str):
            return ""
        return _AGENT_CANONICAL.get(name, name.strip().lower())

    def _find_specialist(self, state: dict, key: str) -> dict | None:
        for bucket in ("validated_results", "specialist_results"):
            items = state.get(bucket, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                agent = item.get("agent", "")
                if agent == key or self._canonical_agent(agent) == self._canonical_agent(key):
                    return item
        return None

    def _compute_sha256(self, state: dict, timestamp: str) -> str:
        question = str(state.get("question", ""))
        rapport = self._rapport_oapc(state)
        json_compact = state.get("json_compact")
        if not json_compact:
            json_compact = {
                "priority": self._priority(state),
                "target": self._target(state),
                "goal": state.get("intention", {}).get("goal", ""),
                "n_specialists": len(state.get("validated_results", []) or []),
            }
        try:
            jc = json.dumps(json_compact, sort_keys=True, ensure_ascii=False, default=str)
        except TypeError:
            jc = str(json_compact)
        ro = json.dumps(rapport, sort_keys=True, ensure_ascii=False, default=str)
        payload = f"{question}{jc}{ro}{timestamp}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _confidence_badge(self, confidence: str) -> Table:
        conf = str(confidence or "").lower()
        if conf == "haute":
            bg, fg, label = COLORS["bg_ok"], COLORS["P4"], "Confiance : HAUTE"
        elif conf == "faible":
            bg, fg, label = COLORS["bg_critical"], COLORS["P1"], "Confiance : FAIBLE"
        else:
            bg, fg, label = COLORS["bg_warn"], COLORS["P3"], "Confiance : MOYENNE"
        cell = Paragraph(
            f'<para align="center"><b>{label}</b></para>',
            self.styles["badge"],
        )
        tbl = Table([[cell]], colWidths=[_CONTENT_WIDTH * 0.5])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("TEXTCOLOR", (0, 0), (-1, -1), fg),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOX", (0, 0), (-1, -1), 1, fg),
        ]))
        return tbl

    def _priority_badge(self, priority: str) -> Table:
        """Badge couleur ReportLab (remplace emojis non supportés)."""
        prio = str(priority or "P4").upper()
        specs = {
            "P1": (colors.HexColor("#C0392B"), colors.white, "CRITIQUE"),
            "P2": (colors.HexColor("#E67E22"), colors.white, "URGENT"),
            "P3": (colors.HexColor("#F1C40F"), colors.black, "SURVEILLANCE"),
            "P4": (colors.HexColor("#27AE60"), colors.white, "OK"),
        }
        bg, fg, label = specs.get(prio, specs["P4"])
        cell = Paragraph(
            f'<para align="center"><b>{prio} — {label}</b></para>',
            self.styles["badge"],
        )
        tbl = Table([[cell]], colWidths=[_CONTENT_WIDTH * 0.45])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("TEXTCOLOR", (0, 0), (-1, -1), fg),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 1, bg),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return tbl

    @staticmethod
    def _resolve_anomaly_timestamp(row: pd.Series, df: pd.DataFrame) -> Any:
        """Colonne temporelle : Date > timestamp > date > datetime > index."""
        for col in ("Date", "timestamp", "date"):
            if col in row.index:
                val = row[col]
                try:
                    if val is not None and not pd.isna(val):
                        return val
                except (TypeError, ValueError):
                    if val is not None:
                        return val
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                val = row[col]
                try:
                    if not pd.isna(val):
                        return val
                except (TypeError, ValueError):
                    return val
        if isinstance(df.index, pd.DatetimeIndex):
            return row.name
        return None

    # ── S1 Page de garde ────────────────────────────────

    def _section_1_garde(self, state: dict) -> list:
        priority = self._priority(state)
        target = self._target(state)
        profile = self._profile(state)
        prio_color = COLORS.get(priority, COLORS["header"])

        verdict_txt, verdict_style = _VERDICT_TEXT.get(priority, _VERDICT_TEXT["P4"])
        verdict_para = Paragraph(
            sanitize_for_pdf(verdict_txt),
            self.styles[verdict_style],
        )

        badge_prio = self._priority_badge(priority)

        ctx_rows = [
            ["Champ", "Valeur"],
            ["Machine", format_value(state.get("machine_id", "N/A"))],
            ["Lot", format_value(state.get("lot_id", "N/A"))],
            ["Opérateur", format_value(state.get("operateur", "N/A"))],
            ["Recette", format_value(state.get("recette", "N/A"))],
            ["Date analyse", format_timestamp(datetime.now())],
            ["Profil rapport", format_value(profile)],
        ]
        ctx_table = self._simple_table(
            ctx_rows,
            col_widths=[45 * mm, _CONTENT_WIDTH - 45 * mm],
        )

        story = [
            Spacer(1, 6 * mm),
            Paragraph(
                "RAPPORT D'ANALYSE INDUSTRIELLE",
                self.styles["title"],
            ),
            Spacer(1, 4 * mm),
            Paragraph(
                sanitize_for_pdf(target),
                self.styles["h1"],
            ),
            Spacer(1, 3 * mm),
            Table([[badge_prio]], colWidths=[_CONTENT_WIDTH]),
            Spacer(1, 4 * mm),
            Table([[verdict_para]], colWidths=[_CONTENT_WIDTH]),
            Spacer(1, 6 * mm),
            self._h1("Contexte production"),
            ctx_table,
            Spacer(1, 4 * mm),
            self._confidence_badge(state.get("confidence", "")),
            Spacer(1, 2 * mm),
            HRFlowable(width=_CONTENT_WIDTH, color=prio_color, thickness=2),
            PageBreak(),
        ]
        return story

    # ── S2 Résumé exécutif ──────────────────────────────

    def _section_2_resume(self, state: dict) -> list:
        rapport = self._rapport_oapc(state)
        priority = self._priority(state)
        resume = sanitize_for_pdf(str(state.get("resume_executif", "") or ""))

        prescrire_bg = COLORS["light_blue"]
        if priority == "P1":
            prescrire_bg = COLORS["bg_critical"]
        elif priority in ("P2", "P3"):
            prescrire_bg = COLORS["bg_warn"]

        oapc_rows = [
            ["Étape OAPC", "Contenu"],
            [
                "OBSERVER",
                sanitize_for_pdf(rapport.get("observer", "N/A")),
            ],
            [
                "ANALYSER",
                sanitize_for_pdf(rapport.get("analyser", "N/A")),
            ],
            [
                "PRESCRIRE",
                sanitize_for_pdf(rapport.get("prescrire", state.get("recommendation", "N/A"))),
            ],
            [
                "CERTIFIER",
                sanitize_for_pdf(rapport.get("certifier", "N/A")),
            ],
        ]
        tbl = Table(oapc_rows, colWidths=[32 * mm, _CONTENT_WIDTH - 32 * mm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLORS["header"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), COLORS["text_light"]),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, COLORS["border"]),
            ("BACKGROUND", (0, 1), (-1, 1), COLORS["light_blue"]),
            ("BACKGROUND", (0, 3), (-1, 3), prescrire_bg),
            ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#F1F5F9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))

        ts = datetime.now().isoformat(timespec="milliseconds")
        sha = self._compute_sha256(state, ts)[:16]

        story = [
            self._h1("RÉSUMÉ EXÉCUTIF"),
            Spacer(1, 2 * mm),
        ]
        if resume:
            story.extend([self._body(resume), Spacer(1, 3 * mm)])
        story.extend([
            tbl,
            Spacer(1, 3 * mm),
            self._confidence_badge(state.get("confidence", "")),
            self._caption(f"Empreinte (16 car.) : {sha}"),
            PageBreak(),
        ])
        return story

    # ── S3 Dashboard KPIs ───────────────────────────────

    def _section_3_kpis(self, state: dict) -> list:
        kpis = state.get("kpis") or {}
        if not isinstance(kpis, dict) or not kpis:
            return [
                self._h1("DASHBOARD KPIs"),
                *self._placeholder(
                    "KPIs non disponibles — tables production non encore peuplées."
                ),
            ]

        imgs = []
        for key, label in (
            ("gauge_oee_png", "OEE"),
            ("gauge_mtbf_png", "MTBF"),
            ("gauge_fpyield_png", "FPY"),
        ):
            img = self._image_png(kpis.get(key), 55, 55)
            if img:
                imgs.append(img)
            else:
                imgs.append(Paragraph(label, self.styles["caption"]))

        gauge_row = Table([imgs], colWidths=[_CONTENT_WIDTH / 3] * 3)
        gauge_row.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))

        oee = kpis.get("oee")
        disp = kpis.get("disponibilite")
        perf = kpis.get("performance")
        qual = kpis.get("qualite")

        recap_rows = [
            ["Indicateur", "Valeur", "Détail"],
            [
                "OEE / TRS",
                format_percentage(oee) if oee is not None else "N/A",
                f"D={format_percentage(disp) if disp is not None else 'N/A'} "
                f"P={format_percentage(perf) if perf is not None else 'N/A'} "
                f"Q={format_percentage(qual) if qual is not None else 'N/A'}",
            ],
            [
                "MTBF",
                f"{format_number(kpis.get('mtbf_h'), 1)} h",
                f"MTTR {format_number(kpis.get('mttr_h'), 1)} h — "
                f"{format_number(kpis.get('nb_pannes'), 0)} pannes",
            ],
            [
                "First Pass Yield",
                format_percentage(kpis.get("first_pass_yield"))
                if kpis.get("first_pass_yield") is not None
                else "N/A",
                f"Scrap {format_percentage(kpis.get('scrap_rate')) if kpis.get('scrap_rate') is not None else 'N/A'} — "
                f"{format_number(kpis.get('nb_pieces_total'), 0)} pièces",
            ],
        ]

        return [
            self._h1("DASHBOARD KPIs"),
            Spacer(1, 2 * mm),
            gauge_row,
            Spacer(1, 4 * mm),
            self._simple_table(recap_rows, [50 * mm, 35 * mm, _CONTENT_WIDTH - 85 * mm]),
            Spacer(1, 4 * mm),
        ]

    # ── S4 Graphique principal ──────────────────────────

    def _section_4_graphique(self, state: dict) -> list:
        target = self._target(state)
        story = [self._h1(f"ANALYSE CAPTEUR — {target}"), Spacer(1, 2 * mm)]

        png = None
        z_item = self._find_specialist(state, "ZScoreSpecialist")
        if z_item and isinstance(z_item.get("result"), dict):
            png = z_item["result"].get("timeseries_png")

        if not png:
            df = state.get("df_propre")
            anom = state.get("df_anomalies")
            if isinstance(df, pd.DataFrame) and not df.empty:
                png = build_timeseries(df, target, anomalies=anom, title=target)

        img = self._image_png(png, 170, 65)
        if img:
            story.append(img)
        else:
            story.extend(self._placeholder("Graphique temporel non disponible."))

        story.append(Spacer(1, 3 * mm))
        story.append(self._h1("Top 3 anomalies"))
        story.extend(self._top_anomalies_table(state, z_item))

        stats = self._graph_stats(state, z_item)
        story.append(Spacer(1, 2 * mm))
        story.append(self._body(stats))
        story.append(PageBreak())
        return story

    def _top_anomalies_table(self, state: dict, z_item: dict | None) -> list:
        df_anom = state.get("df_anomalies")
        target = self._target(state)
        rows = [["Rang", "Timestamp", "Valeur", "Z-score", "Classification"]]

        if isinstance(df_anom, pd.DataFrame) and not df_anom.empty:
            subset = df_anom.head(3)
            for i, (_, row) in enumerate(subset.iterrows(), 1):
                ts = self._resolve_anomaly_timestamp(row, df_anom)
                val = row.get(target, row.iloc[0] if len(row) else "N/A")
                zsc = row.get("zscore", row.get("max_zscore", "N/A"))
                cls = row.get("type_anomalie", row.get("classification", "anomalie"))
                rows.append([
                    str(i),
                    format_timestamp(ts),
                    format_number(val, 2),
                    format_number(zsc, 2),
                    format_value(cls),
                ])
        else:
            payload = z_item.get("result", {}) if z_item else {}
            timestamps = payload.get("anomalies_timestamps", [])[:3]
            if timestamps:
                for i, ts in enumerate(timestamps, 1):
                    rows.append([str(i), format_value(ts), "N/A", "N/A", "anomalie"])
            else:
                return self._placeholder("Aucune anomalie détectée ✅")

        return [self._simple_table(rows, [12 * mm, 45 * mm, 28 * mm, 22 * mm, 43 * mm])]

    def _graph_stats(self, state: dict, z_item: dict | None) -> str:
        n_pts = "N/A"
        df = state.get("df_propre")
        if isinstance(df, pd.DataFrame):
            n_pts = str(len(df))
        pct = max_z = cpk = "N/A"
        if z_item and isinstance(z_item.get("result"), dict):
            r = z_item["result"]
            pct = format_number(r.get("pourcentage_anomalies"), 1) + " %"
            max_z = format_number(r.get("max_zscore"), 2)
        cpk_item = self._find_specialist(state, "CpCpkSpecialist")
        if cpk_item and isinstance(cpk_item.get("result"), dict):
            r_cpk = cpk_item["result"]
            cpk = format_number(r_cpk.get("cpk", r_cpk.get("Cpk")), 2)
        return (
            f"Points : {n_pts} | % anomalies : {pct} | max z-score : {max_z} | Cpk : {cpk}"
        )

    # ── S5 Tendance ─────────────────────────────────────

    def _section_5_tendance(self, state: dict) -> list:
        tendance = state.get("tendance") or {}
        if not isinstance(tendance, dict) or not tendance:
            return [
                self._h1("TENDANCE & COMPARAISON HISTORIQUE"),
                *self._placeholder("Analyse de tendance non disponible."),
                PageBreak(),
            ]

        story = [
            self._h1("TENDANCE & COMPARAISON HISTORIQUE"),
            Spacer(1, 2 * mm),
        ]
        img = self._image_png(tendance.get("timeseries_png"), 170, 60)
        if img:
            story.append(img)
        phrase = state.get("phrase_tendance") or tendance.get("resume", "")
        if phrase:
            story.extend([Spacer(1, 2 * mm), self._body(str(phrase))])

        evo = tendance.get("evolution_pct")
        rows = [
            ["Métrique", "Semaine actuelle", "Semaine précédente", "Évolution"],
            [
                "Tendance Mann-Kendall",
                format_value(tendance.get("direction_fr")),
                f"p={format_number(tendance.get('p_value'), 3)}",
                format_value(tendance.get("significant")),
            ],
            [
                "Évolution %",
                "—",
                "—",
                f"{format_number(evo, 1)} %" if evo is not None else "N/A",
            ],
        ]
        story.extend([
            Spacer(1, 3 * mm),
            self._simple_table(rows, [45 * mm, 38 * mm, 38 * mm, 39 * mm]),
            PageBreak(),
        ])
        return story

    # ── S6 Interprétations ──────────────────────────────

    def _section_6_interpretations(self, state: dict) -> list:
        interpretations = state.get("interpretations") or {}
        if not isinstance(interpretations, dict) or not interpretations:
            return [
                self._h1("INTERPRÉTATIONS PAR SPÉCIALISTE"),
                *self._placeholder("Analyses en cours..."),
                PageBreak(),
            ]

        story = [self._h1("INTERPRÉTATIONS PAR SPÉCIALISTE"), Spacer(1, 2 * mm)]
        for agent_name, text in interpretations.items():
            story.append(Paragraph(
                sanitize_for_pdf(str(agent_name)),
                self.styles["h2"],
            ))
            story.append(self._body(str(text)))
            metrics = self._metrics_for_agent(state, str(agent_name))
            if metrics:
                story.append(Spacer(1, 1 * mm))
                story.append(metrics)
            story.append(Spacer(1, 3 * mm))
        story.append(PageBreak())
        return story

    def _metrics_for_agent(self, state: dict, agent_name: str) -> Table | None:
        item = self._find_specialist(state, agent_name)
        if not item or not isinstance(item.get("result"), dict):
            return None
        result = item["result"]
        rows = [["Métrique", "Valeur"]]
        count = 0
        for key, val in result.items():
            if key in ("classification", "anomalies_timestamps"):
                continue
            if count >= 6:
                break
            rows.append([format_value(key), format_value(val)])
            count += 1
        if len(rows) <= 1:
            return None
        return self._simple_table(rows, [55 * mm, _CONTENT_WIDTH - 55 * mm], "TABLE_COMPACT")

    # ── S7 Causes ───────────────────────────────────────

    def _section_7_causes(self, state: dict) -> list:
        causes_block = state.get("causes") or {}
        causes_list: list = []
        bar_png = None
        note = _CAUSES_NOTE

        if isinstance(causes_block, dict):
            causes_list = causes_block.get("causes", []) or []
            bar_png = causes_block.get("bar_png")
            note = causes_block.get("note", note)
        elif isinstance(causes_block, list):
            causes_list = causes_block

        if not causes_list:
            return [
                self._h1("CAUSES PROBABLES"),
                *self._placeholder("Aucune cause identifiée."),
                PageBreak(),
            ]

        story = [self._h1("CAUSES PROBABLES"), Spacer(1, 2 * mm)]
        img = self._image_png(bar_png, 170, 80)
        if img:
            story.append(img)
            story.append(Spacer(1, 3 * mm))

        rows = [["Rang", "Cause", "Score /100", "Source", "Détail"]]
        for i, c in enumerate(causes_list[:5], 1):
            if not isinstance(c, dict):
                continue
            rows.append([
                str(i),
                format_value(c.get("label")),
                format_number(c.get("score"), 0),
                format_value(c.get("source")),
                sanitize_for_pdf(str(c.get("detail", "")))[:80],
            ])
        story.append(self._simple_table(
            rows,
            [12 * mm, 55 * mm, 22 * mm, 28 * mm, 53 * mm],
        ))
        story.extend([
            Spacer(1, 2 * mm),
            self._caption(note),
            PageBreak(),
        ])
        return story

    # ── S8 Heatmap ──────────────────────────────────────

    def _section_8_heatmap(self, state: dict) -> list:
        heatmap = state.get("heatmap") or {}
        if not isinstance(heatmap, dict) or not heatmap:
            return [
                self._h1("CORRÉLATIONS MULTIVARIÉES"),
                *self._placeholder("Matrice de corrélations non disponible."),
            ]

        story = [self._h1("CORRÉLATIONS MULTIVARIÉES"), Spacer(1, 2 * mm)]
        img = self._image_png(heatmap.get("heatmap_png"), 170, 100)
        if img:
            story.append(img)
        top = heatmap.get("top_correlations", [])
        rows = [["Variable A", "Variable B", "r", "Force"]]
        if isinstance(top, list):
            for pair in top[:10]:
                if isinstance(pair, dict):
                    rows.append([
                        format_value(pair.get("col_a")),
                        format_value(pair.get("col_b")),
                        format_number(pair.get("r"), 2),
                        format_value(pair.get("force")),
                    ])
        story.extend([
            Spacer(1, 3 * mm),
            self._simple_table(rows, [45 * mm, 45 * mm, 25 * mm, 35 * mm]),
            self._caption(
                f"Méthode : {format_value(heatmap.get('method', 'pearson'))}"
            ),
            Spacer(1, 4 * mm),
        ])
        return story

    # ── S9 Impact financier ─────────────────────────────

    def _section_9_financier(self, state: dict) -> list:
        fin = state.get("impact_financier") or {}
        if not isinstance(fin, dict) or not fin:
            return [
                self._h1("IMPACT FINANCIER ESTIMÉ"),
                *self._placeholder("Estimation financière non disponible."),
            ]

        story = [self._h1("IMPACT FINANCIER ESTIMÉ"), Spacer(1, 2 * mm)]
        img = self._image_png(fin.get("waterfall_png"), 170, 70)
        if img:
            story.append(img)

        rows = [
            ["Poste", "Montant"],
            ["Coût arrêt estimé", f"{format_number(fin.get('cout_arret_estime'), 2)} €"],
            ["Coût rebuts estimé", f"{format_number(fin.get('cout_rebuts_estime'), 2)} €"],
            [
                "Total estimé",
                f"{format_number(fin.get('cout_total_estime'), 2)} €",
            ],
        ]
        h_ap = fin.get("heures_avant_panne")
        if h_ap is not None:
            rows.append(["Heures avant panne", f"{format_number(h_ap, 1)} h"])

        tbl = self._simple_table(rows, [90 * mm, _CONTENT_WIDTH - 90 * mm])
        story.extend([
            Spacer(1, 3 * mm),
            tbl,
            Spacer(1, 2 * mm),
            self._caption("Estimation basée sur coût horaire config machine."),
        ])

        if self._priority(state) == "P1":
            alert = Paragraph(
                '<para backColor="#FEF2F2" borderColor="#DC2626" '
                'borderWidth="1" borderPadding="4">'
                "<b>Action immédiate requise</b></para>",
                self.styles["body"],
            )
            story.extend([Spacer(1, 2 * mm), alert])
        story.append(Spacer(1, 4 * mm))
        return story

    # ── S10 Recommandations + RAG ───────────────────────

    def _section_10_recommandations(self, state: dict) -> list:
        rapport = self._rapport_oapc(state)
        reco = sanitize_for_pdf(
            str(state.get("reco_enrichie") or rapport.get("prescrire", "N/A"))
        )
        priority = self._priority(state)
        delai = _DELAIS.get(priority, _DELAIS["P4"])
        responsable = format_value(state.get("responsable", "Équipe maintenance"))

        story = [
            self._h1("RECOMMANDATIONS"),
            Spacer(1, 2 * mm),
            self._body(reco),
            Spacer(1, 2 * mm),
            self._body(f"Délai d'intervention : {delai}"),
            self._body(f"Responsable : {responsable}"),
        ]

        rag = state.get("rag_context") or {}
        n_found = 0
        if isinstance(rag, dict):
            n_found = int(rag.get("n_found", 0) or 0)
        if n_found > 0 and isinstance(rag.get("results"), list) and rag["results"]:
            top = rag["results"][0]
            citation = format_value(top.get("citation", ""))
            extrait = sanitize_for_pdf(str(top.get("text", "")))[:200]
            rag_box = Paragraph(
                '<para backColor="#EBF4FF" borderPadding="6">'
                f"<b>Référence documentaire :</b> {citation}<br/>"
                f"{extrait}</para>",
                self.styles["body"],
            )
            story.extend([Spacer(1, 3 * mm), rag_box])
        story.append(PageBreak())
        return story

    # ── S11 Annexe technique ────────────────────────────

    def _section_11_annexe(self, state: dict) -> list:
        profile = self._profile(state)
        if profile not in ("ingenieur", "technicien"):
            return []

        story = [
            self._h1("ANNEXE TECHNIQUE"),
            Spacer(1, 2 * mm),
        ]

        sql = sanitize_for_pdf(str(state.get("sql_query", "N/A")))
        story.append(Paragraph(f"SQL :<br/><font name='Courier' size='7'>{sql}</font>", self.styles["code"]))

        cleaning = state.get("cleaning_stats", {})
        story.extend([
            Spacer(1, 2 * mm),
            self._body(f"Nettoyage Agent 3 : {format_dict(cleaning) if isinstance(cleaning, dict) else format_value(cleaning)}"),
        ])

        warnings = state.get("judge_warnings", [])
        if isinstance(warnings, list) and warnings:
            story.append(self._body(f"Judge warnings : {format_list(warnings, max_items=5)}"))
        else:
            story.append(self._body("Judge warnings : Aucun"))

        exec_times = state.get("execution_times", {})
        if isinstance(exec_times, dict) and exec_times:
            rows = [["Agent", "Durée (ms)"]]
            for agent, ms in sorted(exec_times.items(), key=lambda x: str(x[0])):
                rows.append([format_value(agent), format_number(ms, 0)])
            story.extend([
                Spacer(1, 2 * mm),
                self._simple_table(rows, [80 * mm, _CONTENT_WIDTH - 80 * mm], "TABLE_COMPACT"),
            ])

        models = (
            f"7b={OLLAMA_CONFIG.get('model_7b', 'N/A')}, "
            f"14b={OLLAMA_CONFIG.get('model_14b', 'N/A')}"
        )
        story.extend([Spacer(1, 2 * mm), self._caption(f"Modèles Ollama : {models}")])
        return story

    # ── S12 Traçabilité EN9100 ──────────────────────────

    def _section_12_tracabilite(self, state: dict) -> list:
        ts = datetime.now().isoformat(timespec="milliseconds")
        sha = self._compute_sha256(state, ts)
        n_pts = "N/A"
        df = state.get("df_propre")
        if isinstance(df, pd.DataFrame):
            n_pts = str(len(df))

        question = str(state.get("question", ""))
        if len(question) > 100:
            question = question[:97] + "..."

        meta_rows = [
            ["Champ", "Valeur"],
            ["Version IndustrIA", "v2.1"],
            ["Date génération", format_timestamp(datetime.now())],
            ["Profil rapport", format_value(self._profile(state))],
            ["Machine", format_value(state.get("machine_id", "N/A"))],
            ["Question analysée", sanitize_for_pdf(question)],
            ["Nb points analysés", n_pts],
            ["Spécialistes appelés", format_list(state.get("agents_called", []), max_items=8)],
        ]

        sig_height = 25 * mm
        sig_table = Table(
            [
                ["Technicien", "Responsable qualité"],
                ["", ""],
                ["Nom : ___________________", "Nom : ___________________"],
                ["Date : __________________", "Date : __________________"],
                ["Signature :", "Signature :"],
            ],
            colWidths=[_CONTENT_WIDTH / 2, _CONTENT_WIDTH / 2],
            rowHeights=[8 * mm, 6 * mm, 8 * mm, 8 * mm, sig_height - 30 * mm],
        )
        sig_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, COLORS["border"]),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))

        return [
            self._h1("TRAÇABILITÉ — EN9100"),
            Spacer(1, 2 * mm),
            self._simple_table(meta_rows, [50 * mm, _CONTENT_WIDTH - 50 * mm]),
            Spacer(1, 3 * mm),
            self._body("Empreinte numérique du rapport"),
            Paragraph(
                f'<font name="Courier" size="6">{sha}</font>',
                self.styles["code"],
            ),
            Spacer(1, 4 * mm),
            sig_table,
            Spacer(1, 3 * mm),
            self._caption("Document à conserver 10 ans — Réf. EN9100 Rev D"),
        ]


# Alias rétrocompatibilité pipeline existant
PDFReportAgent = Agent6cPDF


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = Agent6cPDF()
    state = {
        "question": "Anomalies sur four_3",
        "target_column": "four_3",
        "user_profile": "technicien",
        "priority": "P2",
        "machine_id": "PRESSE_01",
        "confidence": "moyenne",
        "rapport_oapc": {
            "observer": "Anomalies détectées.",
            "analyser": "Dérive possible.",
            "prescrire": "Vérifier le capteur.",
            "certifier": "IndustrIA v2.1",
            "priority": "P2",
        },
        "resume_executif": "Synthèse test.",
        "interpretations": {"ZScoreSpecialist": "13 anomalies."},
        "validated_results": [],
        "agents_called": ["agent_5_interpreter"],
    }
    out = agent.run(state)
    print(out)
