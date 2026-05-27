"""
Résolution des ambiguïtés (scores 0.70–0.85) — LLM classifie parmi candidats uniquement.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import requests

from data.config import OLLAMA_CONFIG

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_TIMEOUT_S = 10
LLM_MAX_RETRIES = 3


class Agent3Disambiguator:
    def run(
        self,
        ambiguites: list[dict],
        context: "ClientContext",
    ) -> dict:
        del context  # réservé extensions futures
        resolutions: dict = {}
        try:
            for amb in ambiguites:
                terme = amb["terme"]
                candidats = amb["candidats"][:3]
                if not candidats:
                    continue
                chosen, fallback = self._disambiguate(terme, candidats)
                resolutions[terme] = {
                    "value": chosen,
                    "score": next(
                        (c["score"] for c in candidats if c.get("value") == chosen),
                        0.75,
                    ),
                    "fallback": fallback,
                }
            return {"resolutions": resolutions, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"resolutions": resolutions, "error": str(exc)}

    def _disambiguate(self, terme: str, candidats: list[dict]) -> tuple[str, bool]:
        labels = [str(c.get("value", c.get("key", ""))) for c in candidats]
        for attempt in range(LLM_MAX_RETRIES):
            idx = self._call_llm_index(terme, labels)
            if idx is not None and 0 <= idx < len(labels):
                return labels[idx], False
        return labels[0], True

    def _call_llm_index(self, terme: str, labels: list[str]) -> int | None:
        payload = {
            "model": OLLAMA_CONFIG["model_7b"],
            "prompt": self._build_prompt(terme, labels),
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 8},
        }
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT_S)
            resp.raise_for_status()
            text = (resp.json().get("response") or "").strip()
        except Exception:
            return None

        m = re.search(r"-?\d+", text)
        if not m:
            return None
        idx = int(m.group())
        if idx == -1:
            return None
        return idx

    @staticmethod
    def _build_prompt(terme: str, labels: list[str]) -> str:
        lines = "\n".join(f"{i}: {lab}" for i, lab in enumerate(labels))
        return (
            "Tu reçois un terme extrait d'une question industrielle et des candidats.\n"
            "Réponds UNIQUEMENT avec l'index du meilleur candidat (0, 1 ou 2) "
            "ou -1 si aucun ne convient. Rien d'autre.\n\n"
            f'Terme: "{terme}"\n'
            f"Candidats:\n{lines}\n\n"
            "Index:"
        )
