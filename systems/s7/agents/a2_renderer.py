"""
A2 — Rendu PDF via report_port (Python pur).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from systems.s7.document import ReportDocument


def run(
    document: "ReportDocument",
    render_fn: Callable[["ReportDocument"], bytes],
) -> dict:
    try:
        pdf_bytes = render_fn(document)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            return {"pdf_bytes": b"", "error": "PDF invalide ou vide"}
        return {"pdf_bytes": pdf_bytes, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"pdf_bytes": b"", "error": str(exc)}
