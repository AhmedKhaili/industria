"""
Agent Financier — impact coût arrêt / rebuts + waterfall PNG.
Python pur, zéro LLM.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.config import FINANCIAL_PARAMS, get_machine
from enterprise.report.charts import build_waterfall
from enterprise.report.formatters import format_number

logger = logging.getLogger(__name__)

_PRIORITY_HOURS_KEY = {
    "P1": "heures_arret_P1",
    "P2": "heures_arret_P2",
    "P3": "heures_arret_P3",
    "P4": "heures_arret_P4",
}


class AgentFinancier:
    """Estime les coûts d'arrêt et de rebuts selon la priorité ISA-18.2."""

    def run(
        self,
        priority: str,
        machine_id: str = "default",
        anomaly_pct: float = 0.0,
        slope_derive: float | None = None,
        seuil_critique: float | None = None,
        valeur_actuelle: float | None = None,
        nb_pieces_total: int = 0,
    ) -> dict:
        """
        Calcule coûts estimés et diagramme waterfall.

        Returns:
            dict: montants €, catégories waterfall, PNG, config machine.
        """
        machine_config = get_machine(machine_id)
        try:
            prio = self._normalize_priority(priority)
            hours_key = _PRIORITY_HOURS_KEY.get(prio, "heures_arret_P4")
            heures_arret = float(FINANCIAL_PARAMS.get(hours_key, 0))
            marge = float(FINANCIAL_PARAMS.get("marge_securite", 1.2))

            cout_horaire = float(
                machine_config.get("cout_horaire")
                or FINANCIAL_PARAMS.get("cout_horaire_defaut", 500)
            )
            cout_rebut_piece = float(
                FINANCIAL_PARAMS.get("cout_rebut_piece", 45)
            )

            cout_arret = max(
                0.0,
                heures_arret * cout_horaire * marge,
            )

            pct = max(0.0, float(anomaly_pct or 0))
            pieces = max(0, int(nb_pieces_total or 0))
            cout_rebuts = max(
                0.0,
                pieces * (pct / 100.0) * cout_rebut_piece * marge,
            )

            cout_total = cout_arret + cout_rebuts

            heures_avant_panne = self._heures_avant_panne(
                slope_derive,
                seuil_critique,
                valeur_actuelle,
            )

            categories = ["Coût arrêt", "Coût rebuts", "Total estimé"]
            values = [cout_arret, cout_rebuts, cout_total]

            png = build_waterfall(
                categories,
                values,
                title=f"Impact financier — {prio}",
                unit="€",
            )

            return {
                "cout_arret_estime": round(cout_arret, 2),
                "cout_rebuts_estime": round(cout_rebuts, 2),
                "cout_total_estime": round(cout_total, 2),
                "heures_avant_panne": heures_avant_panne,
                "categories_waterfall": categories,
                "values_waterfall": values,
                "waterfall_png": png,
                "machine_config": machine_config,
                "error": None,
            }
        except Exception as exc:
            logger.exception("AgentFinancier.run failed")
            return self._empty_result(machine_config, str(exc))

    def _empty_result(self, machine_config: dict, error: str) -> dict:
        categories = ["Coût arrêt", "Coût rebuts", "Total estimé"]
        values = [0.0, 0.0, 0.0]
        return {
            "cout_arret_estime": None,
            "cout_rebuts_estime": None,
            "cout_total_estime": None,
            "heures_avant_panne": None,
            "categories_waterfall": categories,
            "values_waterfall": values,
            "waterfall_png": build_waterfall(
                categories, values, title="Impact financier", unit="€"
            ),
            "machine_config": machine_config,
            "error": error,
        }

    @staticmethod
    def _normalize_priority(priority: str) -> str:
        p = str(priority or "P4").upper().strip()
        if p not in _PRIORITY_HOURS_KEY:
            return "P4"
        return p

    @staticmethod
    def _heures_avant_panne(
        slope_derive: float | None,
        seuil_critique: float | None,
        valeur_actuelle: float | None,
    ) -> float | None:
        if slope_derive is None or seuil_critique is None or valeur_actuelle is None:
            return None
        try:
            slope = float(slope_derive)
            if slope == 0:
                return None
            delta = float(seuil_critique) - float(valeur_actuelle)
            heures = delta / slope
            if heures < 0:
                return None
            return round(heures, 2)
        except (TypeError, ValueError):
            return None
