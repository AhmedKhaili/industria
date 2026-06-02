"""Fixtures partagées tests S7."""

from __future__ import annotations

import pytest

from systems.s7 import prep


@pytest.fixture
def enable_f2_narratif(monkeypatch: pytest.MonkeyPatch) -> None:
    """Active le narratif F2 expérimental (désactivé par défaut produit)."""
    original = prep.rapport_pdf_config

    def _wrap(context):
        cfg = original(context)
        merged = dict(cfg)
        merged["f2_narratif_enabled"] = True
        return merged

    monkeypatch.setattr(prep, "rapport_pdf_config", _wrap)
