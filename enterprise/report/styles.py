"""Styles ReportLab centralisés pour les rapports IndustrIA."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import TableStyle

# ── Couleurs industrielles ──────────────────────────────
COLORS = {
    "P1": colors.HexColor("#DC2626"),
    "P2": colors.HexColor("#EA580C"),
    "P3": colors.HexColor("#CA8A04"),
    "P4": colors.HexColor("#16A34A"),
    "header": colors.HexColor("#1E3A5F"),
    "light_blue": colors.HexColor("#EBF4FF"),
    "border": colors.HexColor("#CBD5E1"),
    "text_dark": colors.HexColor("#1E293B"),
    "text_light": colors.white,
    "bg_ok": colors.HexColor("#F0FDF4"),
    "bg_warn": colors.HexColor("#FFF7ED"),
    "bg_critical": colors.HexColor("#FEF2F2"),
}

# ── Constantes mise en page ─────────────────────────────
PAGE_MARGIN = 15 * mm
HEADER_HEIGHT = 12 * mm
FOOTER_HEIGHT = 10 * mm

_TABLE_STYLES: dict[str, TableStyle] = {}


def build_styles() -> dict[str, ParagraphStyle]:
    """Construit et retourne tous les styles paragraphe nommés."""
    base = getSampleStyleSheet()
    header = COLORS["header"]
    text_dark = COLORS["text_dark"]

    styles = {
        "title": ParagraphStyle(
            "title",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=24,
            textColor=COLORS["text_light"],
            backColor=header,
            alignment=TA_CENTER,
            spaceAfter=12,
            leading=28,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=header,
            spaceAfter=8,
            leading=18,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=header,
            spaceAfter=6,
            leading=14,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=text_dark,
            leading=14,
            alignment=TA_LEFT,
        ),
        "body_small": ParagraphStyle(
            "body_small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=text_dark,
            leading=11,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7,
            textColor=text_dark,
            leading=9,
        ),
        "verdict_go": ParagraphStyle(
            "verdict_go",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=COLORS["P4"],
            alignment=TA_CENTER,
            leading=20,
        ),
        "verdict_nogo": ParagraphStyle(
            "verdict_nogo",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=COLORS["P1"],
            alignment=TA_CENTER,
            leading=20,
        ),
        "badge": ParagraphStyle(
            "badge",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=COLORS["text_light"],
            alignment=TA_CENTER,
            leading=12,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7,
            textColor=text_dark,
            leading=9,
        ),
    }
    return styles


def _build_table_styles() -> None:
    """Initialise les styles TableStyle réutilisables (lazy, une seule fois)."""
    if _TABLE_STYLES:
        return

    border = COLORS["border"]
    header = COLORS["header"]
    light = COLORS["light_blue"]

    _TABLE_STYLES["TABLE_HEADER"] = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), header),
            ("TEXTCOLOR", (0, 0), (-1, 0), COLORS["text_light"]),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, border),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
        ]
    )

    _TABLE_STYLES["TABLE_ROW"] = TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), COLORS["text_dark"]),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, border),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, light]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
    )

    _TABLE_STYLES["TABLE_COMPACT"] = TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), COLORS["text_dark"]),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, border),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, light]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
    )

    _TABLE_STYLES["TABLE_KPI"] = TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (-1, -1), COLORS["text_dark"]),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 2, header),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border),
            ("BACKGROUND", (0, 0), (-1, 0), light),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]
    )


def get_table_style(name: str) -> TableStyle:
    """Retourne un style tableau par nom (TABLE_HEADER, TABLE_ROW, …)."""
    _build_table_styles()
    key = name.upper() if not name.startswith("TABLE_") else name
    if key not in _TABLE_STYLES:
        raise KeyError(f"Style tableau inconnu : {name!r}")
    return _TABLE_STYLES[key]


def draw_header(canvas, doc, title: str, machine: str, timestamp: str) -> None:
    """En-tête : IndustrIA à gauche, titre au centre, date à droite."""
    canvas.saveState()
    width, height = doc.pagesize
    top_y = height - PAGE_MARGIN

    canvas.setFont("Helvetica-Bold", 11)
    canvas.setFillColor(COLORS["header"])
    canvas.drawString(PAGE_MARGIN, top_y - 4 * mm, "IndustrIA")

    if machine:
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(COLORS["text_dark"])
        canvas.drawString(PAGE_MARGIN, top_y - 7.5 * mm, machine)

    canvas.setFont("Helvetica-Bold", 10)
    canvas.setFillColor(COLORS["header"])
    canvas.drawCentredString(width / 2, top_y - 5 * mm, title[:80])

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(COLORS["text_dark"])
    canvas.drawRightString(width - PAGE_MARGIN, top_y - 5 * mm, timestamp)

    line_y = top_y - HEADER_HEIGHT
    canvas.setStrokeColor(COLORS["header"])
    canvas.setLineWidth(0.8)
    canvas.line(PAGE_MARGIN, line_y, width - PAGE_MARGIN, line_y)
    canvas.restoreState()


def draw_footer(canvas, doc, page_num: int, total_pages: int) -> None:
    """Pied de page : confidentialité à gauche, numéro de page à droite."""
    canvas.saveState()
    width, _height = doc.pagesize
    footer_top = FOOTER_HEIGHT + 2 * mm

    canvas.setStrokeColor(COLORS["header"])
    canvas.setLineWidth(0.8)
    canvas.line(PAGE_MARGIN, footer_top, width - PAGE_MARGIN, footer_top)

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(COLORS["text_dark"])
    canvas.drawString(PAGE_MARGIN, FOOTER_HEIGHT - 2 * mm, "CONFIDENTIEL — EN9100")
    canvas.drawRightString(
        width - PAGE_MARGIN,
        FOOTER_HEIGHT - 2 * mm,
        f"Page {page_num}/{total_pages}",
    )
    canvas.restoreState()
