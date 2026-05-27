"""
Agent 6b Reco — reformulation recommandation + contexte RAG manuel.
LLM reformulation uniquement — zéro calcul.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import requests

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.config import OLLAMA_CONFIG, get_profile
from enterprise.report.formatters import format_value, sanitize_for_pdf

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
_DEFAULT_PROFILE = "technicien"
_MAX_JSON_KEYS = 6
_MAX_ATTEMPTS = 3
_MIN_RECO_LEN = 10
_MAX_RECO_LEN = 500
_LLM_TEMPERATURE = 0.2
_LLM_NUM_CTX = 2048

_PROFILE_NUM_PREDICT = {
    "operateur": 80,
    "technicien": 150,
    "ingenieur": 200,
    "directeur": 100,
}

_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-zPp])-?\d+(?:[.,]\d+)?")


class Agent6bReco:
    """Enrichit la recommandation Agent 5 PRESCRIRE avec le contexte RAG manuel."""

    def run(
        self,
        recommandation: str,
        rag_result: dict,
        target_col: str,
        priority: str,
        user_profile: str = "technicien",
    ) -> dict:
        """
        Reformule la recommandation en intégrant le manuel si disponible.

        Returns:
            dict: ``reco_enrichie``, ``citation_rag``, ``rag_used``, etc.
        """
        profile = self._normalize_profile(user_profile)
        reco_raw = sanitize_for_pdf(str(recommandation or ""))
        target = sanitize_for_pdf(str(target_col or "capteur"))
        prio = sanitize_for_pdf(str(priority or "P4").upper())

        rag_text = ""
        citation_rag = ""
        rag_used = False

        try:
            results = []
            if isinstance(rag_result, dict):
                results = rag_result.get("results") or []
            n_found = int(rag_result.get("n_found", 0) or 0) if isinstance(rag_result, dict) else 0

            if results and n_found > 0:
                top = results[0] if isinstance(results[0], dict) else {}
                rag_text = sanitize_for_pdf(str(top.get("text", "")))
                citation_rag = sanitize_for_pdf(str(top.get("citation", "")))
                rag_used = bool(rag_text and rag_text != "N/A")

            compact = self._build_json_compact(
                reco_raw,
                rag_text,
                target,
                prio,
                profile,
                rag_used,
            )
            forbidden = get_profile(profile).get("forbidden_words", [])

            reco_enrichie: str | None = None
            for _attempt in range(_MAX_ATTEMPTS):
                raw = self._call_ollama(compact, profile, forbidden)
                if raw is None:
                    continue
                normalized = self._normalize_text(raw)
                validation = self._validate_output(
                    normalized,
                    compact,
                    profile,
                    forbidden,
                    target,
                    prio,
                )
                if validation["valid"]:
                    reco_enrichie = sanitize_for_pdf(normalized)
                    break

            if reco_enrichie is None:
                reco_enrichie = self._build_fallback(reco_raw, citation_rag)
                return {
                    "reco_enrichie": reco_enrichie,
                    "citation_rag": citation_rag,
                    "rag_used": rag_used,
                    "profile_used": profile,
                    "fallback_used": True,
                    "error": None,
                }

            return {
                "reco_enrichie": reco_enrichie,
                "citation_rag": citation_rag,
                "rag_used": rag_used,
                "profile_used": profile,
                "fallback_used": False,
                "error": None,
            }
        except Exception as exc:
            logger.exception("Agent6bReco.run failed")
            fallback = self._build_fallback(reco_raw, citation_rag)
            return {
                "reco_enrichie": fallback,
                "citation_rag": citation_rag,
                "rag_used": rag_used,
                "profile_used": profile,
                "fallback_used": True,
                "error": str(exc),
            }

    @staticmethod
    def _normalize_profile(user_profile: str) -> str:
        p = str(user_profile or _DEFAULT_PROFILE).strip().lower()
        if p in ("operateur", "technicien", "ingenieur", "directeur"):
            return p
        return _DEFAULT_PROFILE

    def _build_json_compact(
        self,
        recommandation: str,
        rag_text: str,
        target: str,
        priority: str,
        profile: str,
        rag_disponible: bool,
    ) -> dict:
        reco = recommandation[:200] if len(recommandation) > 200 else recommandation
        ctx = rag_text[:300] if len(rag_text) > 300 else rag_text
        compact = {
            "recommandation": sanitize_for_pdf(reco),
            "contexte_manuel": sanitize_for_pdf(ctx) if rag_disponible else "",
            "target": target,
            "priority": priority,
            "profile": profile,
            "rag_disponible": format_value(rag_disponible),
        }
        return dict(list(compact.items())[:_MAX_JSON_KEYS])

    def _call_ollama(
        self,
        json_compact: dict,
        profile: str,
        forbidden_words: list,
    ) -> str | None:
        num_predict = _PROFILE_NUM_PREDICT.get(profile, 150)
        forbidden_txt = ", ".join(forbidden_words) if forbidden_words else "(aucun)"

        system = (
            "Tu reformules une recommandation de maintenance industrielle. "
            "INTERDIT : commencer par 'Je', 'En tant que', 'La recommandation indique'. "
            "INTERDIT : métaphores, généralités. "
            "FORMAT : action concrète + délai + référence procédure si disponible. "
            "Exemple : 'Inspecter le capteur CR10 section intrados. "
            "Vérifier dérive ±0.02mm. Délai : < 4h.' "
            f"Max {num_predict} mots, profil {profile}. "
            "Si manuel disponible : cite la procédure concernée. "
            "Réponds UNIQUEMENT la recommandation reformulée. "
            f"Interdits supplémentaires : {forbidden_txt}"
        )
        payload_text = json.dumps(json_compact, ensure_ascii=False)
        prompt = (
            f"{system}\n\n"
            f"Données (JSON) :\n{payload_text}\n\n"
            "Recommandation reformulée :"
        )

        timeout = 30
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_CONFIG["model_14b"],
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": _LLM_TEMPERATURE,
                        "num_ctx": _LLM_NUM_CTX,
                        "num_predict": num_predict,
                    },
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            text = str(data.get("response", "") or "").strip()
            return text if text else None
        except Exception:
            logger.exception("Agent6bReco Ollama request failed")
            return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        cleaned = text.strip().strip('"').strip("'")
        cleaned = re.sub(r"```[a-zA-Z]*", "", cleaned)
        cleaned = cleaned.replace("```", "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _allowed_numbers_from_compact(compact: dict) -> set[float]:
        allowed: set[float] = set()

        def register(val: Any) -> None:
            if val is None or isinstance(val, bool):
                return
            if isinstance(val, str):
                for match in _NUMBER_TOKEN_RE.findall(val):
                    try:
                        allowed.add(float(match.replace(",", ".")))
                    except ValueError:
                        pass
                return
            try:
                n = float(val)
                allowed.add(n)
                allowed.add(round(n, 1))
            except (TypeError, ValueError):
                pass

        register(compact.get("target"))
        priority = compact.get("priority", "")
        if isinstance(priority, str):
            m = re.match(r"P(\d)", priority.upper())
            if m:
                allowed.add(float(m.group(1)))
        return allowed

    def _validate_output(
        self,
        text: str,
        json_compact: dict,
        profile: str,
        forbidden_words: list,
        target: str,
        priority: str,
    ) -> dict:
        if len(text) < _MIN_RECO_LEN:
            return {"valid": False, "error": "texte trop court"}
        if len(text) > _MAX_RECO_LEN:
            return {"valid": False, "error": "texte trop long"}

        lowered = text.lower()
        for word in forbidden_words:
            if word.lower() in lowered:
                return {"valid": False, "error": f"mot interdit: {word}"}

        allowed = self._allowed_numbers_from_compact(json_compact)
        for token in re.findall(r"\d+", target):
            allowed.add(float(token))
        m = re.match(r"P(\d)", priority.upper())
        if m:
            allowed.add(float(m.group(1)))

        text_for_numbers = re.sub(r"\bP\s*[1-4]\b", "", text, flags=re.IGNORECASE)
        for match in _NUMBER_TOKEN_RE.findall(text_for_numbers):
            try:
                number = float(match.replace(",", "."))
            except ValueError:
                continue
            if any(abs(number - a) <= 0.5 for a in allowed):
                continue
            # Autoriser chiffres déjà présents dans la recommandation source
            reco_src = str(json_compact.get("recommandation", ""))
            if match.replace(",", ".") in reco_src.replace(",", "."):
                continue
            return {"valid": False, "error": f"chiffre inventé: {match}"}

        return {"valid": True}

    @staticmethod
    def _build_fallback(recommandation: str, citation_rag: str) -> str:
        """Recommandation originale + citation RAG si disponible."""
        reco = sanitize_for_pdf(recommandation) or "Suivre la procédure maintenance en vigueur."
        if citation_rag and citation_rag != "N/A":
            return f"{reco} Référence : {citation_rag}"
        return reco
