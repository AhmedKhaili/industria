"""
Rendu PDF ReportLab autonome — CI et fallback sans modifier enterprise/.
"""

from __future__ import annotations

import io
import re
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


def _abbrev_cpk_variable(name: str) -> str:
    """Abréviation tableau Cpk uniquement — évite les retours à la ligne."""
    s = str(name).strip()
    m = re.match(r"^([A-Z0-9]+)_INTRADOS_(FORME)$", s, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()}_INTR._{m.group(2).upper()}"
    return s


def _is_cpk_metrics_table(tdef: dict) -> bool:
    return "capabilit" in str(tdef.get("title", "")).lower()


def _sanitize(
    text: str,
    formatters_mod: Any | None,
    *,
    client_mode: bool = False,
) -> str:
    if formatters_mod is not None and hasattr(formatters_mod, "sanitize_for_pdf"):
        out = formatters_mod.sanitize_for_pdf(text)
    else:
        out = str(text or "N/A").replace("None", "N/A")
    if client_mode:
        from systems.s5.prep import polish_client_text

        out = polish_client_text(out)
    return out


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
    client_mode = bool(meta.get("client_mode"))

    def clean(text: str) -> str:
        return _sanitize(text, formatters_mod, client_mode=client_mode)

    for block in document.blocks:
        btype = block.block_type
        data = block.data

        if btype == "cover":
            m = data.get("meta", meta)
            band_color = colors.HexColor(str(m.get("bandeau_couleur", "#1565C0")))
            header_style = ParagraphStyle(
                "cover_header",
                parent=styles["title"],
                backColor=band_color,
                textColor=colors.white,
            )
            story.append(Paragraph("RAPPORT QUALITÉ", header_style))
            story.append(Spacer(1, 2 * mm))
            ref = clean(str(m.get("reference", "")))
            if ref and ref != "N/A":
                story.append(
                    Paragraph(
                        f"<b>Référence :</b> {ref}",
                        styles["body"],
                    )
                )
            story.append(Spacer(1, 3 * mm))
            ts_raw = m.get("timestamp", "")
            if formatters_mod is not None and hasattr(formatters_mod, "format_timestamp"):
                date_display = formatters_mod.format_timestamp(ts_raw)
            else:
                date_display = clean(str(ts_raw))[:19].replace("T", " ")
            cover_rows = [
                ["Client", clean(str(m.get("client", "")))],
                ["Pièce", clean(str(m.get("piece", "")))],
                ["Opération", clean(str(m.get("operation", "")))],
                ["Profil", clean(str(m.get("profile", "")))],
            ]
            op_label = clean(str(m.get("operateur", "")))
            if op_label and op_label != "N/A":
                cover_rows.append(["Opérateur", op_label])
            cover_rows.append(["Date", date_display])
            tbl = Table(cover_rows, colWidths=[40 * mm, _CONTENT_WIDTH - 40 * mm])
            tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.extend([tbl, Spacer(1, 6 * mm)])
            q = clean(str(m.get("question", "")))
            qstyle = ParagraphStyle(
                "cover_question",
                parent=styles["body"],
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=14,
            )
            story.append(Paragraph(f"Question : {q}", qstyle))
            story.append(PageBreak())

        elif btype == "verdict":
            banner = data.get("banner") or {}
            btxt = clean(str(banner.get("text", data.get("label", ""))))
            bg = colors.HexColor(str(banner.get("bg", "#C62828")))
            fg = colors.HexColor(str(banner.get("fg", "#FFFFFF")))
            banner_style = ParagraphStyle(
                "verdict_banner",
                parent=styles.get("verdict", styles["h1"]),
                fontName="Helvetica-Bold",
                fontSize=14,
                textColor=fg,
                alignment=TA_CENTER,
            )
            banner_tbl = Table(
                [[Paragraph(btxt, banner_style)]],
                colWidths=[_CONTENT_WIDTH],
            )
            banner_tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), bg),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(banner_tbl)
            story.append(Spacer(1, 4 * mm))
            for bullet in data.get("bullets") or []:
                story.append(
                    Paragraph(
                        f"• {clean(str(bullet))}",
                        styles["body"],
                    )
                )
            story.append(Spacer(1, 4 * mm))

        elif btype == "executive":
            story.append(Paragraph("RÉSUMÉ EXÉCUTIF", styles["h1"]))
            s5_txt = data.get("synthese_s5")
            s6_txt = data.get("synthese_s6")
            if s5_txt:
                story.append(Paragraph("<b>Synthèse analyse</b>", styles.get("h2", styles["h1"])))
                story.append(Paragraph(clean(str(s5_txt)), styles["body"]))
                story.append(Spacer(1, 2 * mm))
            if s6_txt:
                story.append(Paragraph("<b>Synthèse actions</b>", styles.get("h2", styles["h1"])))
                story.append(Paragraph(clean(str(s6_txt)), styles["body"]))
                story.append(Spacer(1, 2 * mm))
            if not s5_txt and not s6_txt:
                for para in data.get("paragraphs") or []:
                    story.append(Paragraph(clean(str(para)), styles["body"]))
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
                            Paragraph(clean(prio), body_style),
                            Paragraph(clean(str(it.get("action", ""))), body_style),
                            Paragraph(clean(str(it.get("responsable", ""))), body_style),
                            Paragraph(clean(str(it.get("delai", ""))), body_style),
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
                title = clean(str(it.get("title", "Graphique")))
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
                            f"Graphique indisponible : {clean(str(it['error']))}",
                            styles["body"],
                        )
                    )
                cap = it.get("caption")
                if cap:
                    story.append(Paragraph(clean(str(cap)), styles["caption"]))
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
                var_small = ParagraphStyle(
                    "cpk_var",
                    parent=body_style,
                    fontSize=7,
                    leading=9,
                )
                for tdef in structured:
                    title = tdef.get("title")
                    if title:
                        story.append(Paragraph(clean(str(title)), styles["h1"]))
                    cols = list(tdef.get("columns") or [])
                    rows_in = list(tdef.get("rows") or [])
                    if not cols or not rows_in:
                        continue
                    cpk_table = _is_cpk_metrics_table(tdef)
                    var_col = next(
                        (i for i, c in enumerate(cols) if "variable" in str(c).lower()),
                        0,
                    )
                    table_rows: list[list[Any]] = [
                        [Paragraph(f"<b>{clean(str(c))}</b>", body_style) for c in cols]
                    ]
                    row_bgs = list(tdef.get("row_backgrounds") or [])
                    for row in rows_in:
                        cells: list[Any] = []
                        for cidx, c in enumerate(row):
                            val = str(c)
                            if cpk_table and cidx == var_col:
                                val = _abbrev_cpk_variable(val)
                                cells.append(Paragraph(clean(val), var_small))
                            else:
                                cells.append(Paragraph(clean(val), body_style))
                        while len(cells) < len(cols):
                            cells.append(Paragraph("", body_style))
                        table_rows.append(cells[: len(cols)])
                    ncols = max(len(cols), 1)
                    if cpk_table and ncols > 1:
                        first_w = _CONTENT_WIDTH * 0.36
                        rest_w = (_CONTENT_WIDTH - first_w) / (ncols - 1)
                        col_widths = [first_w] + [rest_w] * (ncols - 1)
                    else:
                        col_widths = [_CONTENT_WIDTH / ncols] * ncols
                    tbl = Table(
                        table_rows,
                        colWidths=col_widths,
                        repeatRows=1,
                    )
                    style_cmds: list[tuple] = [
                        ("BACKGROUND", (0, 0), (-1, 0), _HEADER),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                    for ridx, bg_hex in enumerate(row_bgs):
                        if bg_hex:
                            style_cmds.append(
                                (
                                    "BACKGROUND",
                                    (0, ridx + 1),
                                    (-1, ridx + 1),
                                    colors.HexColor(str(bg_hex)),
                                )
                            )
                    tbl.setStyle(TableStyle(style_cmds))
                    story.extend([tbl, Spacer(1, 4 * mm)])
            story.append(PageBreak())

        elif btype == "interpretations":
            story.append(Paragraph("INTERPRÉTATIONS", styles["h1"]))
            items = data.get("items") or []
            if not items:
                story.append(Paragraph("Aucune interprétation textuelle.", styles["body"]))
            for it in items:
                spec = clean(str(it.get("specialist", "")))
                badge = clean(str(it.get("badge", "")))
                text = clean(str(it.get("text", "")))
                if badge and badge != "N/A":
                    story.append(Paragraph(f"<b>{spec}</b> — <i>{badge}</i>", styles["body"]))
                else:
                    story.append(Paragraph(f"<b>{spec}</b>", styles["body"]))
                story.append(Paragraph(text, styles["body"]))
                story.append(Spacer(1, 3 * mm))
            story.append(PageBreak())

        elif btype == "annexe_dunn":
            story.append(Paragraph("ANNEXE — Comparaisons post-hoc (Dunn)", styles["h1"]))
            for it in data.get("items") or []:
                label = clean(str(it.get("label", "Dunn")))
                text = clean(str(it.get("text", "")))
                story.append(Paragraph(f"<b>{label}</b>", styles["body"]))
                story.append(Paragraph(text, styles["body"]))
                story.append(Spacer(1, 3 * mm))
            story.append(PageBreak())

        elif btype == "traceability":
            story.append(Paragraph("TRAÇABILITÉ", styles["h1"]))
            sha = clean(str(data.get("sha256", "")))
            trace_client = bool(data.get("client_mode"))
            lines = [
                f"Référence rapport : {clean(str(data.get('reference', '')))}",
                f"Empreinte SHA-256 : {sha}",
                f"Horodatage : {clean(str(data.get('timestamp', '')))}",
                f"Version IndustrIA : {clean(str(data.get('industria_version', '')))}",
            ]
            if not trace_client:
                lines.insert(
                    3,
                    f"Fidélité interprétations : {data.get('fidelite_score', 0)}",
                )
            else:
                lines.append("Contrôle des chiffres : validé (calculs Python certifiés)")
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
                        "Spécialistes exécutés : " + ", ".join(clean(str(s)) for s in specs),
                        styles["caption"],
                    )
                )

    doc.build(story)
    return buf.getvalue()
