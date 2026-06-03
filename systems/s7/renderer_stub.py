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
from systems.s7.f2_compact_display import looks_like_matrix_group_code

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


def _show_chart_interpretation(text: str) -> bool:
    t = str(text or "").strip()
    return t not in ("", "N/A", "NA", "NONE", "—", "-")


def _append_paragraphs(
    story: list[Any],
    paragraphs: list[Any] | None,
    styles: dict[str, ParagraphStyle],
    clean,
) -> None:
    for para in paragraphs or []:
        txt = clean(str(para))
        if txt and txt != "N/A":
            story.append(Paragraph(txt, styles["body"]))
            story.append(Spacer(1, 2 * mm))


def _render_table_from_columns(
    story: list[Any],
    columns: list[str],
    rows: list[Any],
    styles: dict[str, ParagraphStyle],
    clean,
    *,
    title: str | None = None,
) -> None:
    if title:
        story.append(Paragraph(clean(title), styles["h1"]))
    if not columns or not rows:
        story.append(Paragraph("Aucune donnée.", styles["body"]))
        return
    body_style = styles["body"]
    table_rows: list[list[Any]] = [
        [Paragraph(f"<b>{clean(str(c))}</b>", body_style) for c in columns]
    ]
    for row in rows:
        if isinstance(row, dict):
            cells = [
                Paragraph(clean(str(row.get(c, row.get(_col_key(c), "—")))), body_style)
                for c in columns
            ]
        else:
            cells = [Paragraph(clean(str(c)), body_style) for c in row]
        while len(cells) < len(columns):
            cells.append(Paragraph("", body_style))
        table_rows.append(cells[: len(columns)])
    ncols = max(len(columns), 1)
    tbl = Table(
        table_rows,
        colWidths=[_CONTENT_WIDTH / ncols] * ncols,
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


def _col_key(label: str) -> str:
    mapping = {
        "Groupe": "group_value",
        "n": "n",
        "Moyenne": "mean_display",
        "Écart-type": "std_display",
        "% hors tol.": "out_of_tolerance_rate_display",
        "Cp": "cp_display",
        "Cpk": "cpk_display",
        "Rang": "rank",
        "Niveau": "severity_display",
    }
    return mapping.get(label, label)


_F2_BLOCK_TYPES = frozenset(
    {
        "business_synthesis",
        "conclusion_key",
        "business_context",
        "key_indicators",
        "how_to_read_cpk",
        "group_comparison_table",
        "statistical_reliability",
        "statistical_test",
        "business_reading",
        "final_verdict",
        "excluded_groups",
        "interpretation_limits",
    }
)


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
    is_f2_compact = str(meta.get("render_mode", "")) == "f2_compact"

    def clean(text: str) -> str:
        return _sanitize(text, formatters_mod, client_mode=client_mode)

    def clean_cell(text: str) -> str:
        """Préserve les codes matrices (ex. O5220910A2-2) en F2 compact."""
        raw = str(text or "")
        if is_f2_compact and looks_like_matrix_group_code(raw):
            out = raw.replace("None", "N/A")
            if formatters_mod is not None and hasattr(formatters_mod, "sanitize_for_pdf"):
                out = formatters_mod.sanitize_for_pdf(out)
            return out
        return clean(raw)

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
            if is_f2_compact:
                report_title = clean(str(m.get("report_title", "")))
                if report_title and report_title != "N/A":
                    title_style = ParagraphStyle(
                        "cover_report_title",
                        parent=styles["body"],
                        fontName="Helvetica-Bold",
                        fontSize=12,
                        leading=15,
                    )
                    story.append(Paragraph(report_title, title_style))
                    story.append(Spacer(1, 3 * mm))
                q_tech = str(
                    m.get("question_technique") or m.get("question") or ""
                ).strip()
                if q_tech:
                    tech_style = ParagraphStyle(
                        "cover_question_technique",
                        parent=styles["body"],
                        fontSize=9,
                        leading=12,
                        textColor=colors.grey,
                    )
                    story.append(
                        Paragraph(
                            f"Référence technique : {clean(q_tech)}",
                            tech_style,
                        )
                    )
            else:
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

        elif btype == "portrait_statistique":
            story.append(Paragraph("PORTRAIT STATISTIQUE", styles["h1"]))
            variables = data.get("variables") or []
            if not variables:
                story.append(
                    Paragraph("Aucune donnée descriptive certifiée.", styles["body"])
                )
            body_style = styles["body"]
            for card in variables:
                var = clean(str(card.get("variable", "")))
                story.append(Paragraph(f"<b>{var}</b>", styles["h1"]))
                cols = list(card.get("columns") or ["Indicateur", "Valeur"])
                rows_in = list(card.get("rows") or [])
                if rows_in:
                    table_rows: list[list[Any]] = [
                        [Paragraph(f"<b>{clean(str(c))}</b>", body_style) for c in cols]
                    ]
                    for row in rows_in:
                        cells = [
                            Paragraph(clean(str(c)), body_style)
                            for c in row[: len(cols)]
                        ]
                        while len(cells) < len(cols):
                            cells.append(Paragraph("", body_style))
                        table_rows.append(cells)
                    tbl = Table(
                        table_rows,
                        colWidths=[_CONTENT_WIDTH * 0.45, _CONTENT_WIDTH * 0.55],
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
                    story.extend([tbl, Spacer(1, 3 * mm)])
                vn = clean(str(card.get("verdict_normalite", "")))
                if vn and vn != "N/A":
                    story.append(
                        Paragraph(
                            f"<b>Verdict normalité :</b> {vn}",
                            styles["body"],
                        )
                    )
                loi = clean(str(card.get("loi_retenue", "")))
                if loi and loi != "N/A":
                    story.append(
                        Paragraph(
                            f"<b>Loi retenue :</b> {loi}",
                            styles["body"],
                        )
                    )
                story.append(Spacer(1, 4 * mm))
            story.append(PageBreak())

        elif btype == "facteurs_influents":
            story.append(Paragraph("FACTEURS INFLUENTS", styles["h1"]))
            intro = data.get("intro")
            if intro:
                story.append(Paragraph(clean(str(intro)), styles["body"]))
                story.append(Spacer(1, 3 * mm))
            body_style = styles["body"]
            for tdef in data.get("tables") or []:
                title = tdef.get("title")
                if title:
                    story.append(Paragraph(clean(str(title)), styles["h1"]))
                cols = list(tdef.get("columns") or [])
                rows_in = list(tdef.get("rows") or [])
                if not cols or not rows_in:
                    continue
                table_rows: list[list[Any]] = [
                    [Paragraph(f"<b>{clean(str(c))}</b>", body_style) for c in cols]
                ]
                for row in rows_in:
                    cells = [
                        Paragraph(clean(str(c)), body_style) for c in row[: len(cols)]
                    ]
                    while len(cells) < len(cols):
                        cells.append(Paragraph("", body_style))
                    table_rows.append(cells)
                ncols = max(len(cols), 1)
                tbl = Table(
                    table_rows,
                    colWidths=[_CONTENT_WIDTH / ncols] * ncols,
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
            for line in data.get("dunn_summary") or []:
                story.append(
                    Paragraph(f"• {clean(str(line))}", styles["body"])
                )
            story.append(PageBreak())

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
            charts_title = str(data.get("section_title") or "PREUVES VISUELLES")
            story.append(Paragraph(charts_title, styles["h1"]))
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
                if _show_chart_interpretation(str(cap or "")):
                    story.append(Paragraph(clean(str(cap)), styles["caption"]))
                interp = it.get("interpretation")
                if _show_chart_interpretation(str(interp or "")):
                    story.append(Spacer(1, 2 * mm))
                    story.append(Paragraph(clean(str(interp)), styles["body"]))
                story.append(Spacer(1, 4 * mm))
            if not is_f2_compact:
                story.append(PageBreak())

        elif btype == "metrics_table":
            metrics_title = str(
                data.get("section_title")
                or meta.get("metrics_section_title")
                or "MÉTRIQUES DÉTAILLÉES"
            )
            story.append(Paragraph(metrics_title, styles["h1"]))
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

        elif btype in _F2_BLOCK_TYPES:
            if btype == "business_synthesis":
                lines = list(data.get("lines") or [])
                if lines:
                    story.append(Paragraph(clean(str(lines[0])), styles["h1"]))
                    for line in lines[1:]:
                        txt = clean(str(line))
                        if txt and txt != "N/A":
                            story.append(Paragraph(txt, styles["body"]))
                            story.append(Spacer(1, 2 * mm))
            else:
                title = clean(str(data.get("title", btype.replace("_", " ").upper())))
                story.append(Paragraph(title, styles["h1"]))
            if btype == "conclusion_key":
                for fact in data.get("facts") or []:
                    if not isinstance(fact, dict):
                        continue
                    lbl = fact.get("key", "")
                    val = fact.get("value")
                    unit = fact.get("unit") or ""
                    grp = fact.get("group", "")
                    disp = f"{val}{unit}" if unit == "%" else str(val)
                    story.append(
                        Paragraph(
                            f"• {clean(str(lbl))} ({clean(str(grp))}) : {clean(disp)}",
                            styles["body"],
                        )
                    )
                _append_paragraphs(story, data.get("paragraphs"), styles, clean)
            elif btype == "business_context":
                tol = data.get("tolerances") or {}
                if tol.get("interval_display"):
                    story.append(
                        Paragraph(
                            f"<b>Tolérances :</b> {clean(str(tol['interval_display']))}",
                            styles["body"],
                        )
                    )
                hdef = data.get("hors_tolerance_definition")
                if hdef:
                    story.append(Paragraph(clean(str(hdef)), styles["body"]))
                _append_paragraphs(story, data.get("paragraphs"), styles, clean)
            elif btype == "key_indicators":
                rows = [
                    [
                        clean(str(r.get("label", ""))),
                        clean_cell(str(r.get("value", ""))),
                    ]
                    for r in data.get("rows") or []
                    if isinstance(r, dict)
                ]
                _render_table_from_columns(
                    story,
                    ["Indicateur", "Valeur"],
                    rows,
                    styles,
                    clean,
                )
            elif btype == "how_to_read_cpk":
                _append_paragraphs(story, data.get("paragraphs"), styles, clean)
                note = data.get("case_note")
                if note:
                    story.append(Paragraph(clean(str(note)), styles["body"]))
            elif btype == "group_comparison_table":
                cols = list(data.get("columns") or [])
                cell_clean = clean_cell if is_f2_compact else clean
                _render_table_from_columns(
                    story,
                    cols,
                    list(data.get("rows") or []),
                    styles,
                    cell_clean,
                )
                foot = data.get("footnote")
                if foot:
                    story.append(Paragraph(clean(str(foot)), styles["caption"]))
            elif btype == "statistical_reliability":
                note = data.get("measure_annex_note")
                if note:
                    story.append(Paragraph(clean(str(note)), styles["body"]))
                rel_cols = list(data.get("columns") or [])
                rel_rows = list(data.get("rows") or [])
                cell_clean = clean_cell if is_f2_compact else clean
                if rel_cols and rel_rows:
                    cap_style = ParagraphStyle(
                        "reliability_cell",
                        parent=styles["caption"],
                        fontSize=7,
                        leading=9,
                    )
                    table_rows: list[list[Any]] = [
                        [
                            Paragraph(f"<b>{clean(str(c))}</b>", cap_style)
                            for c in rel_cols
                        ]
                    ]
                    for row in rel_rows:
                        if not isinstance(row, dict):
                            continue
                        table_rows.append(
                            [
                                Paragraph(
                                    cell_clean(str(row.get(c, "—"))),
                                    cap_style,
                                )
                                for c in rel_cols
                            ]
                        )
                    widths = [
                        _CONTENT_WIDTH * w
                        for w in (0.18, 0.06, 0.1, 0.14, 0.1, 0.16, 0.08, 0.18)
                    ]
                    if len(widths) != len(rel_cols):
                        widths = [_CONTENT_WIDTH / len(rel_cols)] * len(rel_cols)
                    tbl = Table(table_rows, colWidths=widths, repeatRows=1)
                    tbl.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                ("FONTSIZE", (0, 0), (-1, -1), 7),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ]
                        )
                    )
                    story.extend([tbl, Spacer(1, 3 * mm)])
                else:
                    for grp in data.get("groups") or []:
                        if not isinstance(grp, dict):
                            continue
                        gv = clean(str(grp.get("group_value", "")))
                        story.append(Paragraph(f"<b>{gv}</b>", styles["body"]))
                lim = data.get("limits_paragraph")
                if lim:
                    story.append(Paragraph(clean(str(lim)), styles["body"]))
            elif btype == "statistical_test":
                _append_paragraphs(story, data.get("paragraphs"), styles, clean)
            elif btype == "excluded_groups":
                summary = data.get("summary")
                if summary:
                    story.append(Paragraph(clean(str(summary)), styles["caption"]))
                ex_rows = [
                    [
                        clean_cell(str(r.get("group_value", ""))),
                        clean(str(r.get("n", "—"))),
                        clean(str(r.get("reason_label", ""))),
                        clean(str(r.get("detail", ""))),
                    ]
                    for r in data.get("rows") or []
                    if isinstance(r, dict)
                ]
                if ex_rows:
                    cap_style = ParagraphStyle(
                        "excluded_cell",
                        parent=styles["caption"],
                        fontSize=7,
                        leading=9,
                    )
                    table_rows: list[list[Any]] = [
                        [
                            Paragraph(f"<b>{clean(c)}</b>", cap_style)
                            for c in ("Groupe", "n", "Motif", "Détail")
                        ]
                    ]
                    for row in ex_rows:
                        table_rows.append(
                            [Paragraph(c, cap_style) for c in row]
                        )
                    tbl = Table(
                        table_rows,
                        colWidths=[
                            _CONTENT_WIDTH * 0.22,
                            _CONTENT_WIDTH * 0.08,
                            _CONTENT_WIDTH * 0.25,
                            _CONTENT_WIDTH * 0.45,
                        ],
                        repeatRows=1,
                    )
                    tbl.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                ("FONTSIZE", (0, 0), (-1, -1), 7),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ]
                        )
                    )
                    story.extend([tbl, Spacer(1, 3 * mm)])
            elif btype == "business_reading":
                for sec in data.get("sections") or []:
                    if not isinstance(sec, dict):
                        continue
                    heading = sec.get("heading")
                    if heading:
                        story.append(Paragraph(clean(str(heading)), styles["h1"]))
                    _append_paragraphs(story, sec.get("paragraphs"), styles, clean)
            elif btype == "final_verdict":
                for item in data.get("group_hierarchy") or []:
                    if not isinstance(item, dict):
                        continue
                    story.append(
                        Paragraph(
                            f"• {clean(str(item.get('rank')))}. "
                            f"{clean_cell(str(item.get('group_value')))} "
                            f"({clean(str(item.get('severity_display', '')))})",
                            styles["body"],
                        )
                    )
                _append_paragraphs(story, data.get("paragraphs"), styles, clean)
            elif btype == "interpretation_limits":
                _append_paragraphs(story, data.get("paragraphs"), styles, clean)
            if not is_f2_compact:
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
