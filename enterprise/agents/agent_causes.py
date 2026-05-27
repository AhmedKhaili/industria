"""
Agent Causes — scores indépendants /100 par méthode statistique.
Python pur, zéro LLM. Max 5 causes, ne somment pas à 100 %.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from enterprise.report.charts import build_bar_horizontal
from enterprise.report.formatters import format_number

logger = logging.getLogger(__name__)

NOTE_SCORES = "Scores indépendants /100 — ne somment pas à 100%"

_AGENT_ALIASES = {
    "zscorespecialist": "zscore",
    "zscore": "zscore",
    "cpcpkspecialist": "cp_cpk",
    "cp_cpk": "cp_cpk",
    "ewmacusumspecialist": "ewma_cusum",
    "ewma_cusum": "ewma_cusum",
    "mannkendallspecialist": "mann_kendall",
    "mann_kendall": "mann_kendall",
    "spcspecialist": "spc",
    "spc": "spc",
    "regressionspecialist": "regression",
    "regression": "regression",
}


class AgentCauses:
    """Attribue des scores /100 déterministes à partir des résultats spécialistes."""

    def run(
        self,
        specialist_results: list,
        judge_warnings: list | None = None,
    ) -> dict:
        """
        Args:
            specialist_results: Liste de dicts ``{agent, status, result, ...}``.
            judge_warnings: Avertissements du Statistician Judge (+10 score max 95).

        Returns:
            dict: causes triées, note obligatoire, bar_png, ``error``.
        """
        base = {
            "causes": [],
            "note": NOTE_SCORES,
            "bar_png": b"",
            "error": None,
        }
        warnings = judge_warnings or []
        bonus = 10 if warnings else 0

        try:
            causes: list[dict] = []
            for item in specialist_results or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status", "")).lower() != "success":
                    continue
                if item.get("judge_valid") is False:
                    continue
                agent = self._canonical_agent(item.get("agent"))
                payload = item.get("result", {})
                if not isinstance(payload, dict):
                    continue
                causes.extend(self._score_agent(agent, payload, bonus))

            causes = self._dedupe_max_score(causes)
            causes.sort(key=lambda c: c["score"], reverse=True)
            causes = causes[:5]

            labels = [c["label"] for c in causes]
            scores = [c["score"] for c in causes]
            png = build_bar_horizontal(
                labels or ["Aucune cause"],
                scores or [0],
                title="Causes probables",
            )

            base["causes"] = causes
            base["bar_png"] = png
            return base
        except Exception as exc:
            logger.exception("AgentCauses.run failed")
            base["error"] = str(exc)
            base["bar_png"] = build_bar_horizontal(
                ["Erreur"], [0], title="Causes probables"
            )
            return base

    @staticmethod
    def _canonical_agent(agent_name: Any) -> str:
        if not isinstance(agent_name, str):
            return ""
        key = agent_name.strip().lower().replace(" ", "")
        return _AGENT_ALIASES.get(key, agent_name.strip().lower())

    @staticmethod
    def _apply_bonus(score: int, bonus: int) -> int:
        return min(int(score) + bonus, 95)

    def _score_agent(
        self,
        agent: str,
        payload: dict,
        bonus: int,
    ) -> list[dict]:
        if agent == "zscore":
            return self._score_zscore(payload, bonus)
        if agent == "cp_cpk":
            return self._score_cp_cpk(payload, bonus)
        if agent == "ewma_cusum":
            return self._score_ewma(payload, bonus)
        if agent == "mann_kendall":
            return self._score_mann_kendall(payload, bonus)
        if agent == "spc":
            return self._score_spc(payload, bonus)
        if agent == "regression":
            return self._score_regression(payload, bonus)
        return []

    def _score_zscore(self, payload: dict, bonus: int) -> list[dict]:
        z = float(payload.get("max_zscore", 0) or 0)
        if z > 5:
            score, label = 90, "Anomalie capteur critique"
        elif z > 3:
            score, label = 70, "Anomalie capteur significative"
        elif z > 2:
            score, label = 40, "Anomalie capteur légère"
        else:
            return []
        return [{
            "label": label,
            "score": self._apply_bonus(score, bonus),
            "source": "zscore",
            "detail": f"max_zscore={format_number(z, 2)}",
        }]

    def _score_cp_cpk(self, payload: dict, bonus: int) -> list[dict]:
        cpk = float(payload.get("Cpk", payload.get("cpk", 999)) or 999)
        if cpk < 0.67:
            score, label = 85, "Procédé hors capabilité"
        elif cpk < 1.0:
            score, label = 60, "Capabilité insuffisante"
        elif cpk < 1.33:
            score, label = 30, "Capabilité limite"
        else:
            return []
        return [{
            "label": label,
            "score": self._apply_bonus(score, bonus),
            "source": "cp_cpk",
            "detail": f"Cpk={format_number(cpk, 2)}",
        }]

    def _score_ewma(self, payload: dict, bonus: int) -> list[dict]:
        if not bool(payload.get("derive_detectee", False)):
            return []
        return [{
            "label": "Dérive progressive détectée",
            "score": self._apply_bonus(75, bonus),
            "source": "ewma_cusum",
            "detail": str(payload.get("tendance_direction", "")),
        }]

    def _score_mann_kendall(self, payload: dict, bonus: int) -> list[dict]:
        sig = bool(payload.get("significatif", payload.get("significant", False)))
        if not sig:
            return []
        tendance = str(payload.get("tendance", payload.get("trend", ""))).lower()
        if "hausse" in tendance or "increasing" in tendance:
            label = "Tendance hausse"
        elif "baisse" in tendance or "decreasing" in tendance:
            label = "Tendance baisse"
        else:
            return []
        return [{
            "label": label,
            "score": self._apply_bonus(65, bonus),
            "source": "mann_kendall",
            "detail": f"p={format_number(payload.get('p_value'), 2)}",
        }]

    def _score_spc(self, payload: dict, bonus: int) -> list[dict]:
        if bool(payload.get("sous_controle", True)):
            return []
        return [{
            "label": "Hors contrôle statistique",
            "score": self._apply_bonus(55, bonus),
            "source": "spc",
            "detail": f"hors_limites={payload.get('hors_limites_x_count', 'N/A')}",
        }]

    def _score_regression(self, payload: dict, bonus: int) -> list[dict]:
        r2 = self._extract_r_squared(payload)
        if r2 is None or r2 <= 0.8:
            return []
        return [{
            "label": "Forte influence variable explicative",
            "score": self._apply_bonus(50, bonus),
            "source": "regression",
            "detail": f"R²={format_number(r2, 2)}",
        }]

    @staticmethod
    def _extract_r_squared(payload: dict) -> float | None:
        meilleure = payload.get("meilleure_variable")
        if isinstance(meilleure, dict):
            try:
                return float(meilleure.get("r_squared", 0) or 0)
            except (TypeError, ValueError):
                pass
        try:
            return float(payload.get("r_squared", 0) or 0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _dedupe_max_score(causes: list[dict]) -> list[dict]:
        best: dict[str, dict] = {}
        for cause in causes:
            key = cause["label"]
            if key not in best or cause["score"] > best[key]["score"]:
                best[key] = cause
        return list(best.values())
