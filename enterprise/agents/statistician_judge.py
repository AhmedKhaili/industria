import logging
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from state.schema import AgentState

logger = logging.getLogger(__name__)


class StatisticianJudge:
    """Validate specialist outputs with hard-coded methodological rules."""

    _AGENT_NAME_MAP = {
        "ZScoreSpecialist": "zscore",
        "zscore": "zscore",
        "CpCpkSpecialist": "cp_cpk",
        "cp_cpk": "cp_cpk",
        "CorrelationSpecialist": "correlation",
        "correlation": "correlation",
        "AnovaKruskalSpecialist": "anova_kruskal",
        "anova_kruskal": "anova_kruskal",
        "SpcSpecialist": "spc",
        "spc": "spc",
        "RegressionSpecialist": "regression",
        "regression": "regression",
    }

    _HEAVY_ML_AGENTS = {
        "cp_cpk",
        "anova_kruskal",
        "regression",
    }

    def _canonical_agent_name(self, agent_name: str | None) -> str:
        """
        Normalize result agent names across dispatcher and specialist outputs.

        Args:
            agent_name: Raw agent name present in a specialist payload.

        Returns:
            str: Canonical short agent name.
        """
        if not isinstance(agent_name, str):
            return ""
        return self._AGENT_NAME_MAP.get(agent_name, agent_name.strip().lower())

    def _extract_n(self, payload: dict) -> int | None:
        """
        Extract a sample size from heterogeneous specialist payloads.

        Args:
            payload: Specialist `result` payload.

        Returns:
            int | None: Detected sample size when available.
        """
        for key in ("n", "total_points", "n_points", "n_observations"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        return None

    def _find_result(self, all_results: list[dict], canonical_name: str) -> dict | None:
        """
        Locate a specialist result by its canonical agent name.

        Args:
            all_results: All specialist results.
            canonical_name: Canonical short name to search.

        Returns:
            dict | None: Matching result if found.
        """
        for result in all_results:
            agent_name = self._canonical_agent_name(result.get("agent"))
            if agent_name == canonical_name:
                return result
        return None

    def _has_non_normal_group(self, payload: dict) -> bool:
        """
        Detect non-normality information in ANOVA-style payloads.

        Supports both the prompt test format (`normalite_par_groupe`) and the
        current specialist format (`normalite_residus`).

        Args:
            payload: Specialist `result` payload.

        Returns:
            bool: True when non-normality is explicitly detected.
        """
        normalite_par_groupe = payload.get("normalite_par_groupe")
        if isinstance(normalite_par_groupe, dict):
            for group_stats in normalite_par_groupe.values():
                if isinstance(group_stats, dict) and group_stats.get("normale") is False:
                    return True

        normalite_residus = payload.get("normalite_residus")
        if isinstance(normalite_residus, dict) and normalite_residus.get("normale") is False:
            return True

        return False

    def _has_pearson(self, correlations: Any) -> bool:
        """
        Check whether a correlation payload includes at least one Pearson result.

        Args:
            correlations: Correlation list payload.

        Returns:
            bool: True when `pearson_r` appears in at least one item.
        """
        if not isinstance(correlations, list):
            return False

        for item in correlations:
            if isinstance(item, dict) and "pearson_r" in item:
                return True
        return False

    def _validate_result(
        self,
        result: dict,
        all_results: list[dict],
    ) -> dict:
        """
        Validate one specialist result against the hard-coded judge rules.

        Args:
            result: Individual specialist result payload.
            all_results: Full specialist result list for cross-checks.

        Returns:
            dict: Original result enriched with `judge_valid` and `judge_warnings`.
        """
        validated = dict(result)
        judge_warnings: list[str] = []
        judge_valid = result.get("status") == "success"

        payload = result.get("result", {})
        if not isinstance(payload, dict):
            payload = {}

        agent_name = self._canonical_agent_name(result.get("agent"))
        n_value = self._extract_n(payload)

        if agent_name == "anova_kruskal":
            methode = str(payload.get("methode_choisie", "")).strip().upper()
            if methode.startswith("ANOVA") and self._has_non_normal_group(payload):
                judge_valid = False
                judge_warnings.append(
                    "ANOVA appliquee sur donnees non normales - resultat statistiquement invalide. "
                    "Utiliser Kruskal-Wallis."
                )

        if agent_name == "cp_cpk" and payload.get("normale") is False:
            judge_warnings.append(
                "Cp/Cpk calcule sur distribution non normale - interpreter avec precaution. "
                "Envisager des indices non-parametriques."
            )

        if agent_name == "correlation" and isinstance(n_value, int) and n_value < 10:
            judge_valid = False
            judge_warnings.append(
                "Correlation sur moins de 10 points - resultat non fiable"
            )

        if agent_name == "correlation" and self._has_pearson(payload.get("correlations")):
            zscore_result = self._find_result(all_results, "zscore")
            zscore_payload = zscore_result.get("result", {}) if isinstance(zscore_result, dict) else {}
            anomaly_ratio = zscore_payload.get("pourcentage_anomalies")
            if isinstance(anomaly_ratio, (int, float)) and float(anomaly_ratio) > 20.0:
                judge_warnings.append(
                    "Presence d'anomalies importantes - preferer Spearman a Pearson"
                )

        if agent_name in self._HEAVY_ML_AGENTS and isinstance(n_value, int) and n_value < 30:
            judge_valid = False
            judge_warnings.append(
                "Moins de 30 points - resultats statistiques a interpreter avec prudence"
            )

        validated["judge_valid"] = judge_valid
        validated["judge_warnings"] = judge_warnings
        return validated

    def run(self, state: AgentState | dict) -> dict:
        """
        Validate all specialist outputs and update the shared state.

        Args:
            state: Shared pipeline state containing `specialist_results`.

        Returns:
            dict: Structured judge result payload.
        """
        start_time = time.time()

        if isinstance(state, dict):
            state.setdefault("errors", [])
            state.setdefault("judge_warnings", [])
            state.setdefault("validated_results", [])
            state.setdefault("agents_called", [])
            state["agents_called"].append("statistician_judge")

        try:
            specialist_results = state.get("specialist_results", []) if isinstance(state, dict) else []
            if not isinstance(specialist_results, list):
                specialist_results = []

            if not specialist_results:
                warning = "Aucun resultat de specialiste a valider"
                if isinstance(state, dict):
                    state["validated_results"] = []
                    state["judge_warnings"] = state.get("judge_warnings", []) + [warning]

                execution_time_ms = int((time.time() - start_time) * 1000)
                return {
                    "agent": "statistician_judge",
                    "status": "success",
                    "total_results": 0,
                    "valid_count": 0,
                    "invalid_count": 0,
                    "warnings": [warning],
                    "validated_results": [],
                    "execution_time_ms": execution_time_ms,
                    "error": None,
                }

            validated: list[dict] = []
            all_warnings: list[str] = []

            for result in specialist_results:
                if not isinstance(result, dict):
                    continue
                validated_result = self._validate_result(result, specialist_results)
                validated.append(validated_result)
                all_warnings.extend(validated_result.get("judge_warnings", []))

            zscore_r = self._find_result(validated, "zscore")
            spc_r = self._find_result(validated, "spc")
            if zscore_r and spc_r:
                zscore_payload = zscore_r.get("result", {})
                spc_payload = spc_r.get("result", {})
                zscore_anomalies = 0
                spc_sous_controle = True

                if isinstance(zscore_payload, dict):
                    anomalies_value = zscore_payload.get("anomalies_count", 0)
                    if isinstance(anomalies_value, (int, float)):
                        zscore_anomalies = int(anomalies_value)

                if isinstance(spc_payload, dict):
                    spc_sous_controle = bool(spc_payload.get("sous_controle", True))

                if zscore_anomalies > 0 and spc_sous_controle is True:
                    all_warnings.append(
                        "Resultats contradictoires entre Z-Score et SPC - analyser manuellement"
                    )

            if isinstance(state, dict):
                state["validated_results"] = validated
                state["judge_warnings"] = state.get("judge_warnings", []) + all_warnings

            n_valid = sum(1 for item in validated if item.get("judge_valid", True))
            n_invalid = len(validated) - n_valid
            execution_time_ms = int((time.time() - start_time) * 1000)

            return {
                "agent": "statistician_judge",
                "status": "success",
                "total_results": len(specialist_results),
                "valid_count": n_valid,
                "invalid_count": n_invalid,
                "warnings": all_warnings,
                "validated_results": validated,
                "execution_time_ms": execution_time_ms,
                "error": None,
            }
        except Exception as exc:
            logger.exception("statistician_judge failed")
            if isinstance(state, dict):
                state.setdefault("errors", [])
                state["errors"].append(str(exc))
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "statistician_judge",
                "status": "error",
                "total_results": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "warnings": [],
                "validated_results": [],
                "execution_time_ms": execution_time_ms,
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    state = {
        "specialist_results": [
            {
                "agent": "ZScoreSpecialist",
                "status": "success",
                "result": {
                    "anomalies_count": 25,
                    "pourcentage_anomalies": 25.0,
                    "total_points": 100,
                },
                "execution_time_ms": 15,
                "error": None,
            },
            {
                "agent": "SpcSpecialist",
                "status": "success",
                "result": {
                    "sous_controle": True,
                    "hors_limites_x": [],
                },
                "execution_time_ms": 4,
                "error": None,
            },
            {
                "agent": "AnovaKruskalSpecialist",
                "status": "success",
                "result": {
                    "methode_choisie": "ANOVA",
                    "normalite_par_groupe": {
                        "A": {"normale": True},
                        "B": {"normale": False},
                    },
                    "p_value": 0.02,
                    "significatif": True,
                    "n": 40,
                },
                "execution_time_ms": 16,
                "error": None,
            },
            {
                "agent": "CpCpkSpecialist",
                "status": "success",
                "result": {
                    "Cp": 1.2,
                    "Cpk": 0.9,
                    "normale": False,
                    "n": 25,
                },
                "execution_time_ms": 1,
                "error": None,
            },
            {
                "agent": "CorrelationSpecialist",
                "status": "success",
                "result": {
                    "n": 8,
                    "correlations": [
                        {"pearson_r": 0.85},
                    ],
                },
                "execution_time_ms": 6,
                "error": None,
            },
            {
                "agent": "RegressionSpecialist",
                "status": "success",
                "result": {
                    "n": 20,
                    "regressions": [],
                },
                "execution_time_ms": 7,
                "error": None,
            },
        ],
    }

    judge = StatisticianJudge()
    result = judge.run(state)

    logger.info("Agent    : %s", result["agent"])
    logger.info("Total    : %s", result["total_results"])
    logger.info("Valides  : %s", result["valid_count"])
    logger.info("Invalides: %s", result["invalid_count"])
    logger.info("Warnings (%s):", len(result["warnings"]))
    for warning in result["warnings"]:
        logger.info("  WARNING %s", warning)
    logger.info("Detail par agent:")
    for item in result["validated_results"]:
        logger.info(
            "  %s -> %s %s warning(s)",
            item["agent"],
            "VALID" if item.get("judge_valid", True) else "INVALID",
            len(item.get("judge_warnings", [])),
        )
    logger.info("Temps    : %sms", result["execution_time_ms"])
