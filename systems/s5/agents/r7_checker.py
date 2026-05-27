"""
R7 — Vérification synthèse (forbidden_words, tokens_max) — Python pur.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from systems.s5 import prep

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def run(synthese: str, context: "ClientContext", profile: str) -> dict:
    try:
        cfg = prep.profile_config(context, profile)
        tokens_max = int(cfg.get("tokens_max", 250))
        forbidden = [str(w).lower() for w in cfg.get("forbidden_words", [])]

        text = synthese
        warnings: list[str] = []

        for word in forbidden:
            if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
                text = re.sub(rf"\b{re.escape(word)}\b", "", text, flags=re.IGNORECASE)
                warnings.append(f"Terme interdit retiré pour profil {profile} : {word}")

        text = re.sub(r"\s+", " ", text).strip()

        if _estimate_tokens(text) > tokens_max:
            words = text.split()
            max_words = max(20, int(tokens_max * 0.75))
            text = " ".join(words[:max_words]) + "…"
            warnings.append(f"Synthèse tronquée à ~{tokens_max} tokens (profil {profile}).")

        return {"error": None, "synthese": text, "warnings": warnings}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "synthese": synthese, "warnings": []}
