"""
Rendu PDF ReportLab autonome — CI et fallback sans modifier enterprise/.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from systems.s7.document import ReportDocument

_CONTENT_WIDTH = 180 * mm
_PRIO_COLORS = {
    "P1": colors.HexColor("#DC2626"),
    "P2": colors.HexColor("#EA580C"),
    "P3": colors.HexColor("#CA8A04"),
    "P4": colors.HexColor("#16A34A"),
}
_HEADER = colors.HexColor("#1E3A5F")


def _default_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=colors.white,
            backColor=_HEADER,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=_HEADER,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontSize=9,
            leading=13,
            alignment=TA_LEFT,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER,
        ),
        "verdict": ParagraphStyle(
            "verdict",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
    }


def _enterprise_styles(styles_mod: Any) -> dict[str, ParagraphStyle]:
    if hasattr(styles_mod, "build_styles"):
        return styles_mod.build_styles()
    return _default_styles()


def _sanitize(text: str, formatters_mod: Any | None) -> str:
    if formatters_mod is not None and hasattr(formatters_mod, "sanitize_for_pdf"):
        return formatters_mod.sanitize_for_pdf(text)
    return str(text or "N/A").replace("None", "N/A")


def render_pdf(
    document: ReportDocument,
    *,
    styles_mod: Any | None = None,
    formatters_mod: Any | None = None,
) -> bytes:
    styles = _enterprise_styles(styles_mod) if styles_mod else _default_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="Rapport IndustrIA",
    )
    story: list[Any] = []
    meta = document.meta

    for block in document.blocks:
        btype = block.block_type
        data = block.data

        if btype == "cover":
            m = data.get("meta", meta)
            story.append(Paragraph("RAPPORT QUALITÉ IndustrIA", styles["title"]))
            story.append(Spacer(1, 4 * mm))
            ts_raw = m.get("timestamp", "")
            if formatters_mod is not None and hasattr(formatters_mod, "format_timestamp"):
                date_display = formatters_mod.format_timestamp(ts_raw)
            else:
                date_display = _sanitize(str(ts_raw), formatters_mod)[:19].replace("T", " ")
            cover_rows = [
                ["Client", _sanitize(str(m.get("client", "")), formatters_mod)],
                ["Pièce", _sanitize(str(m.get("piece", "")), formatters_mod)],
                ["Opération", _sanitize(str(m.get("operation", "")), formatters_mod)],
                ["Profil", _sanitize(str(m.get("profile", "")), formatters_mod)],
                ["Date", date_display],
            ]
            tbl = Table(cover_rows, colWidths=[40 * mm, _CONTENT_WIDTH - 40 * mm])
            tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ]
                )
            )
            story.extend([tbl, Spacer(1, 4 * mm)])
            q = _sanitize(str(m.get("question", "")), formatters_mod)
            story.append(Paragraph(f"<b>Question :</b> {q}", styles["body"]))
            story.append(PageBreak())

        elif btype == "verdict":
            label = _sanitize(str(data.get("label", "")), formatters_mod)
            prio = str(data.get("priorite_max", "P4")).upper()
            color = _PRIO_COLORS.get(prio, _HEADER)
            vstyle = ParagraphStyle(
                "verdict_dyn",
                parent=styles.get("verdict", styles["h1"]),
                textColor=color,
            )
            story.append(Paragraph(label, vstyle))
            story.append(Spacer(1, 6 * mm))

        elif btype == "executive":
            story.append(Paragraph("RÉSUMÉ EXÉCUTIF", styles["h1"]))
            s5_txt = data.get("synthese_s5")
            s6_txt = data.get("synthese_s6")
            if s5_txt:
                story.append(Paragraph("<b>Synthèse analyse</b>", styles.get("h2", styles["h1"])))
                story.append(Paragraph(_sanitize(str(s5_txt), formatters_mod), styles["body"]))
                story.append(Spacer(1, 2 * mm))
            if s6_txt:
                story.append(Paragraph("<b>Synthèse actions</b>", styles.get("h2", styles["h1"])))
                story.append(Paragraph(_sanitize(str(s6_txt), formatters_mod), styles["body"]))
                story.append(Spacer(1, 2 * mm))
            if not s5_txt and not s6_txt:
                for para in data.get("paragraphs") or []:
                    story.append(Paragraph(_sanitize(str(para), formatters_mod), styles["body"]))
                    story.append(Spacer(1, 2 * mm))
            story.append(PageBreak())

        elif btype == "recommendations":
            story.append(Paragraph("PLAN D'ACTION", styles["h1"]))
            items = data.get("items") or []
            if not items:
                story.append(Paragraph("Aucune recommandation.", styles["body"]))
            else:
                body_style = styles["body"]
                rows: list[list[Any]] = [
                    [
                        Paragraph("<b>Priorité</b>", body_style),
                        Paragraph("<b>Action</b>", body_style),
                        Paragraph("<b>Responsable</b>", body_style),
                        Paragraph("<b>Délai</b>", body_style),
                    ]
                ]
                row_styles: list[tuple] = [
                    ("BACKGROUND", (0, 0), (-1, 0), _HEADER),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
                for idx, it in enumerate(items, start=1):
                    prio = str(it.get("priorite", "")).upper()
                    rows.append(
                        [
                            Paragraph(_sanitize(prio, formatters_mod), body_style),
                            Paragraph(
                                _sanitize(str(it.get("action", "")), formatters_mod),
                                body_style,
                            ),
                            Paragraph(
                                _sanitize(str(it.get("responsable", "")), formatters_mod),
                                body_style,
                            ),
                            Paragraph(
                                _sanitize(str(it.get("delai", "")), formatters_mod),
                                body_style,
                            ),
                        ]
                    )
                    bg = _PRIO_COLORS.get(prio)
                    if bg:
                        row_styles.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#F8FAFC")))
                        row_styles.append(("TEXTCOLOR", (0, idx), (0, idx), bg))
                tbl = Table(
                    rows,
                    colWidths=[16 * mm, 96 * mm, 34 * mm, 34 * mm],
                    repeatRows=1,
                )
                tbl.setStyle(
                    TableStyle(
                        [
                            *row_styles,
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                story.extend([tbl, Spacer(1, 4 * mm)])
            story.append(PageBreak())

        elif btype == "charts":
            story.append(Paragraph("PREUVES VISUELLES", styles["h1"]))
            items = data.get("items") or []
            if not items:
                story.append(Paragraph("Aucun graphique disponible.", styles["body"]))
            for it in items:
                title = _sanitize(str(it.get("title", "Graphique")), formatters_mod)
                story.append(Paragraph(title, styles["h1"]))
                png = it.get("png_bytes")
                if png:
                    try:
                        img = Image(io.BytesIO(png), width=160 * mm, height=90 * mm)
                        story.append(img)
                    except Exception:
                        story.append(
                            Paragraph(
                                "Image non disponible (flux PNG invalide).",
                                styles["body"],
                            )
                        )
                elif it.get("error"):
                    story.append(
                        Paragraph(
                            f"Graphique indisponible : {_sanitize(str(it['error']), formatters_mod)}",
                            styles["body"],
                        )
                    )
                cap = it.get("caption")
                if cap:
                    story.append(Paragraph(_sanitize(str(cap), formatters_mod), styles["caption"]))
                story.append(Spacer(1, 4 * mm))
            story.append(PageBreak())

        elif btype == "metrics_table":
            story.append(Paragraph("MÉTRIQUES DÉTAILLÉES", styles["h1"]))
            structured = data.get("tables") or []
            if not structured:
                legacy = data.get("rows") or []
                if legacy:
                    structured = [
                        {
                            "title": "Synthèse",
                            "columns": ["Élément", "Valeur"],
                            "rows": legacy,
                        }
                    ]
            if not structured:
                story.append(Paragraph("Aucune métrique certifiée.", styles["body"]))
            else:
                body_style = styles["body"]
                for tdef in structured:
                    title = tdef.get("title")
                    if title:
                        story.append(Paragraph(_sanitize(str(title), formatters_mod), styles["h1"]))
                    cols = list(tdef.get("columns") or [])
                    rows_in = list(tdef.get("rows") or [])
                    if not cols or not rows_in:
                        continue
                    table_rows: list[list[Any]] = [
                        [Paragraph(f"<b>{_sanitize(str(c), formatters_mod)}</b>", body_style) for c in cols]
                    ]
                    for row in rows_in:
                        cells = [
                            Paragraph(_sanitize(str(c), formatters_mod), body_style)
                            for c in row
                        ]
                        while len(cells) < len(cols):
                            cells.append(Paragraph("", body_style))
                        table_rows.append(cells[: len(cols)])
                    col_w = _CONTENT_WIDTH / max(len(cols), 1)
                    tbl = Table(
                        table_rows,
                        colWidths=[col_w] * len(cols),
                        repeatRows=1,
                    )
                    tbl.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), _HEADER),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ]
                        )
                    )
                    story.extend([tbl, Spacer(1, 4 * mm)])
            story.append(PageBreak())

        elif btype == "interpretations":
            story.append(Paragraph("INTERPRÉTATIONS", styles["h1"]))
            items = data.get("items") or []
            if not items:
                story.append(Paragraph("Aucune interprétation textuelle.", styles["body"]))
            for it in items:
                spec = _sanitize(str(it.get("specialist", "")), formatters_mod)
                badge = _sanitize(str(it.get("badge", "")), formatters_mod)
                text = _sanitize(str(it.get("text", "")), formatters_mod)
                story.append(Paragraph(f"<b>{spec}</b> — <i>{badge}</i>", styles["body"]))
                story.append(Paragraph(text, styles["body"]))
                story.append(Spacer(1, 3 * mm))
            story.append(PageBreak())

        elif btype == "traceability":
            story.append(Paragraph("TRAÇABILITÉ", styles["h1"]))
            sha = _sanitize(str(data.get("sha256", "")), formatters_mod)
            lines = [
                f"Empreinte SHA-256 : {sha}",
                f"Horodatage : {_sanitize(str(data.get('timestamp', '')), formatters_mod)}",
                f"Fidélité interprétations : {data.get('fidelite_score', 0)}",
                f"Version IndustrIA : {_sanitize(str(data.get('industria_version', '')), formatters_mod)}",
            ]
            for line in lines:
                story.append(Paragraph(line, styles["body"]))

        elif btype == "annexe_warnings":
            count = int(data.get("count", 0))
            story.append(Spacer(1, 4 * mm))
            story.append(
                Paragraph(
                    f"Annexe — {count} avertissement(s) système (détail non reproduit).",
                    styles["caption"],
                )
            )
            specs = data.get("specialists") or []
            if specs:
                story.append(
                    Paragraph(
                        "Spécialistes exécutés : " + ", ".join(_sanitize(str(s), formatters_mod) for s in specs),
                        styles["caption"],
                    )
                )

    doc.build(story)
    return buf.getvalue()
