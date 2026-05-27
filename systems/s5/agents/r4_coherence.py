"""
R4 — Cohérence inter-spécialistes (Python pur).
"""

from __future__ import annotations

from systems.s5 import prep


def run(interpretations: list[dict], specialist_results: list[dict]) -> dict:
    try:
        warnings: list[str] = []
        flagged: set[int] = set()

        cpk_ok = False
        anova_sig = False
        mk_sig = False
        zscore_anomalies = False

        for result in specialist_results:
            if result.get("status") != "success":
                continue
            agent = prep.canonical_agent(result.get("agent"))
            p = result.get("result") or {}

            if agent == "cp_cpk":
                cpk = p.get("Cpk")
                if isinstance(cpk, (int, float)) and float(cpk) >= 1.33:
                    cpk_ok = True
            if agent == "anova_kruskal" and p.get("significatif"):
                anova_sig = True
            if agent == "mann_kendall" and p.get("significatif"):
                mk_sig = True
            if agent == "zscore":
                pct = p.get("pourcentage_anomalies")
                if isinstance(pct, (int, float)) and float(pct) > 0:
                    zscore_anomalies = True

        if anova_sig and cpk_ok:
            warnings.append(
                "ANOVA significatif alors que Cpk >= 1,33 : interpréter le contexte métier."
            )

        if zscore_anomalies and not mk_sig:
            for i, item in enumerate(interpretations):
                if prep.canonical_agent(item.get("specialist")) == "mann_kendall":
                    warnings.append(
                        "Anomalies ponctuelles sans tendance Mann-Kendall significative."
                    )
                    flagged.add(i)

        for idx in flagged:
            if idx < len(interpretations):
                interpretations[idx]["statut"] = "Review"

        return {"error": None, "warnings": warnings, "interpretations": interpretations}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "warnings": [], "interpretations": interpretations}
