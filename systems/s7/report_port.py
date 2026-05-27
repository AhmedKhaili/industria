"""
Port rapport S7 — chargement lazy enterprise/report/ (BSL) ou renderer_stub.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol

from systems.s7.document import ReportDocument
from systems.s7.renderer_stub import render_pdf as stub_render_pdf


class ReportRenderer(Protocol):
    def __call__(self, document: ReportDocument) -> bytes: ...


def _load_enterprise_modules() -> tuple[Any, Any] | None:
    try:
        styles = importlib.import_module("enterprise.report.styles")
        formatters = importlib.import_module("enterprise.report.formatters")
        return styles, formatters
    except ImportError:
        return None


def render_pdf(document: ReportDocument) -> bytes:
    """Prod : styles/formatters enterprise si disponibles ; sinon stub autonome."""
    loaded = _load_enterprise_modules()
    if loaded:
        styles_mod, formatters_mod = loaded
        return stub_render_pdf(document, styles_mod=styles_mod, formatters_mod=formatters_mod)
    return stub_render_pdf(document)


def get_renderer(prefer_enterprise: bool = True) -> ReportRenderer:
    if prefer_enterprise and _load_enterprise_modules():
        return render_pdf
    return stub_render_pdf
