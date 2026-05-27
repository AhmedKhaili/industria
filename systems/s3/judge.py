"""
Validation de cohérence des résultats spécialistes (Python pur).
"""

from __future__ import annotations

_AGENT_ALIASES = {
    "ZScoreSpecialist": "zscore",
    "CpCpkSpecialist": "cp_cpk",
    "AnovaKruskalSpecialist": "anova_kruskal",
    "SpcSpecialist": "spc",
    "MannKendallSpecialist": "mann_kendall",
    "EwmaCusumSpecialist": "ewma_cusum",
    "RegressionSpecialist": "regression",
}

_HEAVY_AGENTS = {"cp_cpk", "anova_kruskal", "regression"}


def _canonical(agent: str | None) -> str:
    if not agent:
        return ""
    return _AGENT_ALIASES.get(agent, str(agent).strip().lower())


def _extract_n(payload: dict) -> int | None:
    for key in ("n", "total_points", "n_points", "n_observations"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _find_result(results: list[dict], name: str) -> dict | None:
    for result in results:
        if _canonical(result.get("agent")) == name:
            return result
    return None


def _has_non_normal_anova(payload: dict) -> bool:
    normalite_residus = payload.get("normalite_residus")
    if isinstance(normalite_residus, dict) and normalite_residus.get("normale") is False:
        return True
    normalite_par_groupe = payload.get("normalite_par_groupe")
    if isinstance(normalite_par_groupe, dict):
        for stats in normalite_par_groupe.values():
            if isinstance(stats, dict) and stats.get("normale") is False:
                return True
    return False


def validate_results(specialist_results: list[dict]) -> dict:
    try:
        validated: list[dict] = []
        global_warnings: list[str] = []

        for result in specialist_results:
            entry = dict(result)
            judge_warnings: list[str] = []
            judge_valid = result.get("status") == "success"

            if result.get("status") == "skipped":
                entry["judge_valid"] = True
                entry["judge_warnings"] = []
                validated.append(entry)
                continue

            payload = result.get("result") or {}
            if not isinstance(payload, dict):
                payload = {}

            agent = _canonical(result.get("agent"))
            n_value = _extract_n(payload)

            if agent == "anova_kruskal":
                methode = str(payload.get("methode_choisie", "")).upper()
                if methode.startswith("ANOVA") and _has_non_normal_anova(payload):
                    judge_valid = False
                    judge_warnings.append(
                        "ANOVA sur données non normales — préférer Kruskal-Wallis"
                    )

            if agent == "cp_cpk" and payload.get("normale") is False:
                judge_warnings.append(
                    "Cp/Cpk sur distribution non normale — interpréter avec prudence"
                )

            if agent in _HEAVY_AGENTS and isinstance(n_value, int) and n_value < 30:
                if judge_valid:
                    judge_warnings.append(
                        "Moins de 30 points — résultats à interpréter avec prudence"
                    )

            entry["judge_valid"] = judge_valid
            entry["judge_warnings"] = judge_warnings
            validated.append(entry)
            global_warnings.extend(judge_warnings)

        return {
            "error": None,
            "specialist_results": validated,
            "warnings": list(dict.fromkeys(global_warnings)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "specialist_results": specialist_results, "warnings": []}


def build_metrics_summary(specialist_results: list[dict]) -> dict:
    """Résumé compact pour S4/S5."""
    summary: dict = {"by_agent": {}, "success_count": 0, "skipped_count": 0}
    for result in specialist_results:
        agent = _canonical(result.get("agent"))
        status = result.get("status")
        if status == "success":
            summary["success_count"] += 1
        elif status == "skipped":
            summary["skipped_count"] += 1
        payload = result.get("result") or {}
        if agent == "cp_cpk" and status == "success" and isinstance(payload, dict):
            col = payload.get("colonne", "unknown")
            summary.setdefault("cpk_by_column", {})[col] = {
                "Cpk": payload.get("Cpk"),
                "Cp": payload.get("Cp"),
                "conforme_EN9100": payload.get("conforme_EN9100"),
            }
        if agent == "anova_kruskal" and status == "success":
            summary["anova"] = {
                "methode": payload.get("methode_choisie"),
                "p_value": payload.get("p_value"),
                "significatif": payload.get("significatif"),
            }
        if agent == "mann_kendall" and status == "success":
            col = payload.get("colonne", "unknown")
            summary.setdefault("tendance_by_column", {})[col] = {
                "tendance": payload.get("tendance"),
                "p_value": payload.get("p_value"),
                "sen_slope": payload.get("sen_slope"),
            }
        summary["by_agent"][agent] = summary["by_agent"].get(agent, 0) + 1
    return summary
