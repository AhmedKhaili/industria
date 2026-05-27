"""
Agent 6b Tendance — une phrase de synthèse tendance (LLM reformulation uniquement).
Métriques calculées par agent_tendance.py (Python pur).
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
from enterprise.report.formatters import (
    format_bool,
    format_number,
    format_percentage,
    sanitize_for_pdf,
)

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
_DEFAULT_PROFILE = "technicien"
_MAX_JSON_KEYS = 5
_MAX_ATTEMPTS = 3
_MIN_PHRASE_LEN = 5
_MAX_PHRASE_LEN = 300
_MAX_PREDICT_TOKENS = 80
_LLM_TEMPERATURE = 0.2
_LLM_NUM_CTX = 2048

_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-zPp])-?\d+(?:[.,]\d+)?")


class Agent6bTendance:
    """Reformule en une phrase les résultats déjà calculés de AgentTendance."""

    def run(
        self,
        tendance_result: dict,
        target_col: str,
        user_profile: str = "technicien",
    ) -> dict:
        """
        Génère une phrase de tendance adaptée au profil utilisateur.

        Returns:
            dict: ``phrase_tendance``, ``profile_used``, ``fallback_used``, ``error``.
        """
        profile = self._normalize_profile(user_profile)
        target = sanitize_for_pdf(str(target_col or "capteur"))

        try:
            if not tendance_result or tendance_result.get("error"):
                phrase = self._build_fallback(tendance_result or {}, target, profile)
                return self._result(phrase, profile, True, tendance_result.get("error"))

            significant = bool(tendance_result.get("significant"))
            if not significant:
                phrase = self._build_fallback(tendance_result, target, profile)
                return self._result(phrase, profile, True, None)

            compact = self._build_json_compact(tendance_result, target, profile)
            forbidden = get_profile(profile).get("forbidden_words", [])

            phrase: str | None = None
            for _attempt in range(_MAX_ATTEMPTS):
                raw = self._call_ollama(compact, profile, forbidden)
                if raw is None:
                    continue
                normalized = self._normalize_text(raw)
                validation = self._validate_output(
                    normalized,
                    tendance_result,
                    target,
                    profile,
                    forbidden,
                )
                if validation["valid"]:
                    phrase = sanitize_for_pdf(normalized)
                    break

            if phrase is None:
                phrase = self._build_fallback(tendance_result, target, profile)
                return self._result(phrase, profile, True, None)

            return self._result(phrase, profile, False, None)
        except Exception as exc:
            logger.exception("Agent6bTendance.run failed")
            phrase = self._build_fallback(tendance_result or {}, target, profile)
            return self._result(phrase, profile, True, str(exc))

    @staticmethod
    def _result(
        phrase: str,
        profile: str,
        fallback_used: bool,
        error: str | None,
    ) -> dict:
        return {
            "phrase_tendance": sanitize_for_pdf(phrase),
            "profile_used": profile,
            "fallback_used": fallback_used,
            "error": error,
        }

    @staticmethod
    def _normalize_profile(user_profile: str) -> str:
        p = str(user_profile or _DEFAULT_PROFILE).strip().lower()
        if p in ("operateur", "technicien", "ingenieur", "directeur"):
            return p
        return _DEFAULT_PROFILE

    def _build_json_compact(
        self,
        tendance_result: dict,
        target: str,
        profile: str,
    ) -> dict:
        """JSON compact (max 5 clés) envoyé au LLM — valeurs déjà formatées."""
        compact: dict[str, Any] = {
            "target": target,
            "direction": format_value_dir(tendance_result.get("direction_fr")),
            "p_value": format_number(tendance_result.get("p_value"), 2),
            "pente": format_number(tendance_result.get("slope_sen"), 4),
            "significant": format_bool(tendance_result.get("significant")),
        }
        evolution = tendance_result.get("evolution_pct")
        if evolution is not None:
            try:
                compact["evolution_pct"] = format_percentage(float(evolution) / 100.0)
            except (TypeError, ValueError):
                compact["evolution_pct"] = format_number(evolution, 1)
        items = list(compact.items())[:_MAX_JSON_KEYS]
        return dict(items)

    def _call_ollama(
        self,
        json_compact: dict,
        profile: str,
        forbidden_words: list,
    ) -> str | None:
        profile_cfg = get_profile(profile)
        max_tokens = min(_MAX_PREDICT_TOKENS, int(profile_cfg.get("max_tokens", 80)))

        forbidden_txt = ", ".join(forbidden_words) if forbidden_words else "(aucun)"
        system = (
            "Tu es un système d'analyse de données capteurs industriels. "
            "Tu décris UNIQUEMENT ce que les chiffres montrent. "
            "INTERDIT : métaphores, généralités, introduction, contexte général. "
            "INTERDIT : commencer par 'Je' ou 'En tant que'. "
            "FORMAT OBLIGATOIRE : "
            "'[Variable] présente une [direction] significative "
            "(p=[valeur], pente=[valeur]).' "
            "Exemple : 'CR10_INTRADOS_FORME présente une hausse significative "
            "(p=0.00, pente=+0.001/mois).' "
            f"UNE seule phrase, max {max_tokens} mots, profil {profile}. "
            "Réponds UNIQUEMENT la phrase, rien d'autre. "
            f"Interdits supplémentaires : {forbidden_txt}"
        )
        payload_text = json.dumps(json_compact, ensure_ascii=False)
        prompt = (
            f"{system}\n\n"
            f"Données (JSON) :\n{payload_text}\n\n"
            "Phrase de tendance :"
        )

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
                        "num_predict": max_tokens,
                    },
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            text = str(data.get("response", "") or "").strip()
            return text if text else None
        except Exception:
            logger.exception("Agent6bTendance Ollama request failed")
            return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        cleaned = text.strip().strip('"').strip("'")
        cleaned = re.sub(r"```[a-zA-Z]*", "", cleaned)
        cleaned = cleaned.replace("```", "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _allowed_numbers(self, tendance_result: dict) -> set[float]:
        allowed: set[float] = set()

        def register(val: Any) -> None:
            if val is None or isinstance(val, bool):
                return
            try:
                n = float(val)
            except (TypeError, ValueError):
                return
            allowed.add(n)
            allowed.add(round(n, 3))
            allowed.add(round(n, 1))
            if n == int(n):
                allowed.add(float(int(n)))

        register(tendance_result.get("evolution_pct"))
        register(tendance_result.get("slope_sen"))
        register(tendance_result.get("p_value"))
        register(tendance_result.get("n_points"))
        return allowed

    @staticmethod
    def _number_whitelist_from_target(target: str) -> set[float]:
        whitelist: set[float] = set()
        for token in re.findall(r"\d+", target):
            whitelist.add(float(token))
        return whitelist

    def _validate_output(
        self,
        text: str,
        tendance_result: dict,
        target: str,
        profile: str,
        forbidden_words: list,
    ) -> dict:
        if len(text) <= _MIN_PHRASE_LEN:
            return {"valid": False, "error": "phrase trop courte"}
        if len(text) > _MAX_PHRASE_LEN:
            return {"valid": False, "error": "phrase trop longue"}

        lowered = text.lower()
        for word in forbidden_words:
            if word.lower() in lowered:
                return {"valid": False, "error": f"mot interdit: {word}"}

        allowed = self._allowed_numbers(tendance_result)
        whitelist = self._number_whitelist_from_target(target)
        text_for_numbers = re.sub(r"\bP\s*[1-4]\b", "", text, flags=re.IGNORECASE)

        for match in _NUMBER_TOKEN_RE.findall(text_for_numbers):
            try:
                number = float(match.replace(",", "."))
            except ValueError:
                continue
            if any(abs(number - w) < 0.001 for w in whitelist):
                continue
            if not any(abs(number - a) <= 0.5 for a in allowed):
                return {"valid": False, "error": f"chiffre inventé: {match}"}

        return {"valid": True}

    def _build_fallback(
        self,
        tendance_result: dict,
        target_col: str,
        user_profile: str,
    ) -> str:
        """Template Python pur — même logique par profil, sans LLM."""
        profile = self._normalize_profile(user_profile)
        target = sanitize_for_pdf(target_col)
        significant = bool(tendance_result.get("significant")) if tendance_result else False
        direction = str(tendance_result.get("direction_fr") or "stable").lower()
        slope = tendance_result.get("slope_sen")
        p_val = tendance_result.get("p_value")
        evolution = tendance_result.get("evolution_pct")
        n_pts = tendance_result.get("n_points")

        if not tendance_result or tendance_result.get("error"):
            return f"Analyse de tendance indisponible pour {target}."

        if not significant:
            return f"Aucune tendance significative détectée sur {target}."

        if profile == "operateur":
            if "hausse" in direction:
                return f"La valeur {target} est en hausse."
            if "baisse" in direction:
                return f"La valeur {target} est en baisse."
            return f"La valeur {target} est stable."

        if profile == "technicien":
            p_txt = format_number(p_val, 2) if p_val is not None else "N/A"
            s_txt = format_number(slope, 2) if slope is not None else "N/A"
            return (
                f"Tendance {direction} détectée sur {target} "
                f"(pente={s_txt}, p={p_txt})."
            )

        if profile == "ingenieur":
            p_txt = format_number(p_val, 2) if p_val is not None else "N/A"
            s_txt = format_number(slope, 2) if slope is not None else "N/A"
            n_txt = format_number(n_pts, 0) if n_pts is not None else "N/A"
            return (
                f"Mann-Kendall significatif sur {target} : "
                f"{direction} (Sen slope={s_txt}, p={p_txt}, n={n_txt})."
            )

        # directeur
        if evolution is not None:
            try:
                evo = format_percentage(float(evolution) / 100.0)
            except (TypeError, ValueError):
                evo = f"{format_number(evolution, 1)} %"
            return (
                f"Indicateur {target} en progression de {evo} "
                f"vs semaine précédente."
            )
        if "hausse" in direction:
            return f"Indicateur {target} en progression."
        if "baisse" in direction:
            return f"Indicateur {target} en régression."
        return f"Indicateur {target} stable sur la période analysée."


def format_value_dir(value: Any) -> str:
    if value is None:
        return "stable"
    return sanitize_for_pdf(str(value))
