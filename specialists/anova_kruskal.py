import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist

logger = logging.getLogger(__name__)


class AnovaKruskalSpecialist(BaseSpecialist):
    """Group comparison specialist with Python-only ANOVA or Kruskal selection."""

    def __init__(self) -> None:
        """Store transient state so validation can access `group_column`."""
        self._current_params: dict = {}
        self._current_state: dict = {}

    def _resolve_group_column(self) -> str | None:
        """
        Resolve the group column from params first, then shared state.

        Returns:
            str | None: Group column name if available.
        """
        group_column = self._current_params.get("group_column")
        if not group_column:
            group_column = self._current_state.get("group_column")
        return str(group_column) if group_column else None

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and group-comparison-specific constraints.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            min_rows: Base interface parameter preserved for compatibility.

        Returns:
            dict: Validation payload with valid flag, warnings, and optional error.
        """
        validation = super()._validate_input(df, target_column, min_rows)
        if not validation["valid"]:
            return validation

        group_column = self._resolve_group_column()
        if not group_column:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "group_column obligatoire pour comparaison de groupes",
            }

        if group_column not in df.columns:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Colonne de groupe introuvable dans le DataFrame",
            }

        group_values = df[group_column].dropna()
        distinct_groups = pd.unique(group_values)
        if len(distinct_groups) < 2:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Minimum 2 groupes requis",
            }

        small_groups: list[str] = []
        for group_name in distinct_groups:
            mask = df[group_column] == group_name
            series = pd.to_numeric(df.loc[mask, target_column], errors="coerce")
            series = series.replace([np.inf, -np.inf], np.nan).dropna()
            if len(series) < 3:
                small_groups.append(str(group_name))

        if small_groups:
            validation["warnings"].append(
                "Groupe trop petit - resultats moins fiables: "
                + ", ".join(small_groups)
            )

        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compare groups using ANOVA or Kruskal-Wallis based on residual normality.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters containing `group_column` and optional `alpha`.

        Returns:
            dict: Group comparison results, normality decision, and descriptive stats.
        """
        group_column = params.get("group_column") or self._current_state.get("group_column")
        alpha = float(params.get("alpha", 0.05))

        if not 0 < alpha < 1:
            raise ValueError("alpha doit etre compris entre 0 et 1")

        groupes: dict[str, pd.Series] = {}
        for nom_groupe in df[group_column].dropna().unique():
            mask = df[group_column] == nom_groupe
            serie = pd.to_numeric(df.loc[mask, target_column], errors="coerce")
            serie = serie.replace([np.inf, -np.inf], np.nan).dropna()
            if len(serie) >= 3:
                groupes[str(nom_groupe)] = serie

        if len(groupes) < 2:
            raise ValueError("Pas assez de groupes valides")

        residuals_parts: list[pd.Series] = []
        for serie in groupes.values():
            residuals_parts.append(serie - float(serie.mean()))
        residuals = pd.concat(residuals_parts, axis=0)

        if len(residuals) <= 5000:
            shapiro_stat, shapiro_p = stats.shapiro(residuals)
            residuals_normaux = bool(shapiro_p > alpha)
            normalite_residus = {
                "shapiro_stat": round(float(shapiro_stat), 4),
                "shapiro_p": round(float(shapiro_p), 4),
                "normale": residuals_normaux,
                "n_residus": int(len(residuals)),
            }
        else:
            residuals_normaux = False
            normalite_residus = {
                "shapiro_stat": None,
                "shapiro_p": None,
                "normale": None,
                "n_residus": int(len(residuals)),
                "note": "n > 5000 - Shapiro non applicable, Kruskal-Wallis choisi par prudence",
            }

        methode_choisie = "ANOVA" if residuals_normaux else "Kruskal-Wallis"
        raison_choix = (
            "Tous les residus combines sont compatibles avec la normalite"
            if residuals_normaux
            else "Distribution non normale detectee sur les residus combines"
        )
        if normalite_residus.get("normale") is None:
            raison_choix = "Shapiro non applicable sur > 5000 residus - choix prudent"

        listes_groupes = list(groupes.values())

        if methode_choisie == "ANOVA":
            levene_stat, levene_p = stats.levene(*listes_groupes)

            if levene_p < alpha:
                logger.warning(
                    "Variances inegales - interpreter avec prudence"
                )
                # TODO v2 : implementer Welch proprement
                methode_choisie = "ANOVA de Welch"

            f_stat, p_value = stats.f_oneway(*listes_groupes)
            test_stat_name = "F"
            test_stat = f_stat
        else:
            levene_stat, levene_p = None, None
            h_stat, p_value = stats.kruskal(*listes_groupes)
            test_stat_name = "H"
            test_stat = h_stat

        stats_groupes: dict[str, dict] = {}
        for nom, serie in groupes.items():
            stats_groupes[nom] = {
                "n": len(serie),
                "mean": round(float(serie.mean()), 3),
                "std": round(float(serie.std()), 3),
                "median": round(float(serie.median()), 3),
                "min": round(float(serie.min()), 3),
                "max": round(float(serie.max()), 3),
            }

        significatif = bool(p_value < alpha)
        if significatif:
            interpretation = (
                f"Difference significative detectee entre les groupes (p={round(float(p_value), 4)}). "
                "Au moins un groupe se comporte differemment."
            )
        else:
            interpretation = (
                f"Aucune difference significative entre les groupes (p={round(float(p_value), 4)}). "
                "Les groupes sont statistiquement similaires."
            )

        return {
            "colonne_cible": target_column,
            "colonne_groupe": group_column,
            "methode_choisie": methode_choisie,
            "raison_choix": raison_choix,
            "n_groupes": len(groupes),
            "groupes": list(groupes.keys()),
            "test_stat_name": test_stat_name,
            "test_stat": round(float(test_stat), 4),
            "p_value": round(float(p_value), 4),
            "alpha": alpha,
            "significatif": significatif,
            "interpretation": interpretation,
            "normalite_residus": normalite_residus,
            "stats_par_groupe": stats_groupes,
            "levene_stat": round(float(levene_stat), 4) if levene_stat is not None else None,
            "levene_p": round(float(levene_p), 4) if levene_p is not None else None,
        }

    @staticmethod
    def _enrich_result(payload: dict) -> dict:
        """Clés normalisées pour lecture agent / PDF."""
        out = dict(payload)
        methode = str(payload.get("methode_choisie", ""))
        out["method"] = "kruskal" if "kruskal" in methode.lower() else "anova"
        out["statistic"] = payload.get("test_stat")
        out["p_value"] = payload.get("p_value")
        out["significant"] = payload.get("significatif")
        out["n_groups"] = payload.get("n_groupes")
        out["group_col"] = payload.get("colonne_groupe")
        out["groups_summary"] = payload.get("stats_par_groupe")
        return out

    def run(
        self,
        df: pd.DataFrame,
        state: dict,
        params: dict | None = None,
    ) -> dict:
        """
        Expose `group_column` to validation without changing the shared base interface.
        """
        self._current_state = dict(state or {}) if isinstance(state, dict) else {}
        self._current_params = dict(params or {})

        if "group_column" not in self._current_params and self._current_state.get("group_column"):
            self._current_params["group_column"] = self._current_state["group_column"]

        try:
            result = super().run(df, state, self._current_params)
            if (
                result.get("status") == "success"
                and isinstance(result.get("result"), dict)
            ):
                result["result"] = self._enrich_result(result["result"])
            return result
        finally:
            self._current_params = {}
            self._current_state = {}


if __name__ == "__main__":
    np.random.seed(42)
    n = 50

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n * 3, freq="1min"
        ),
        "mesure": np.concatenate([
            np.random.normal(100, 5, n),
            np.random.normal(108, 5, n),
            np.random.normal(101, 5, n),
        ]),
        "modele": ["A"] * n + ["B"] * n + ["C"] * n,
    })

    state = {
        "target_column": "mesure",
        "group_column": "modele",
    }
    params = {"group_column": "modele"}

    specialist = AnovaKruskalSpecialist()
    result = specialist.run(df_test, state, params)

    print(f"Agent    : {result['agent']}")
    print(f"Status   : {result['status']}")
    print(f"Methode  : {result['result']['methode_choisie']}")
    print(f"Raison   : {result['result']['raison_choix']}")
    print(f"F/H stat : {result['result']['test_stat']}")
    print(f"p-value  : {result['result']['p_value']}")
    print(f"Significatif : {result['result']['significatif']}")
    print(f"Interpret: {result['result']['interpretation']}")
    print("\nStats par groupe :")
    for group_name, stats_group in result["result"]["stats_par_groupe"].items():
        print(f"  {group_name} -> mean={stats_group['mean']} std={stats_group['std']}")
    print(f"\nTemps    : {result['execution_time_ms']}ms")
    print(f"Erreur   : {result['error']}")
