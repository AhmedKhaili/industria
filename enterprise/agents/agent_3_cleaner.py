import logging
import time

import numpy as np
import pandas as pd
from scipy.signal import medfilt

logger = logging.getLogger(__name__)


class DataCleaner:
    """Clean raw sensor data using robust signal-processing heuristics."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
    ) -> dict:
        """
        Validate the raw DataFrame and target column before cleaning.

        Args:
            df: Raw DataFrame from the SQL agent.
            target_column: Target numeric column to clean.

        Returns:
            dict: Validation status, warnings, and optional error message.
        """
        warnings: list[str] = []

        if df is None or df.empty:
            return {"valid": False, "warnings": warnings, "error": "DataFrame vide"}

        if target_column not in df.columns:
            return {
                "valid": False,
                "warnings": warnings,
                "error": f"Colonne cible absente: {target_column}",
            }

        if not pd.api.types.is_numeric_dtype(df[target_column]):
            return {
                "valid": False,
                "warnings": warnings,
                "error": f"Colonne cible non numérique: {target_column}",
            }

        if len(df.index) < 5:
            warnings.append("Moins de 5 lignes: nettoyage moins fiable")

        if "timestamp" not in df.columns:
            warnings.append("Colonne timestamp absente")

        return {"valid": True, "warnings": warnings, "error": None}

    def _apply_median_filter(
        self,
        series: pd.Series,
        window: int = 3,
    ) -> pd.Series:
        """
        Apply a median filter to a numeric series.

        Args:
            series: Numeric series to filter.
            window: Odd kernel size for the median filter.

        Returns:
            pd.Series: Filtered series.
        """
        if window % 2 == 0:
            window += 1

        series_num = pd.to_numeric(series, errors="coerce")
        fill_value = float(series_num.median()) if series_num.notna().any() else 0.0
        series_filled = series_num.fillna(fill_value)
        filtered = medfilt(series_filled.to_numpy(dtype=float), kernel_size=window)
        return pd.Series(filtered, index=series.index, name=series.name)

    def _compute_mad_zscore(
        self,
        series: pd.Series,
        window: int = 20,
    ) -> pd.Series:
        """
        Compute a rolling robust MAD-based z-score.

        Args:
            series: Numeric series.
            window: Rolling window size.

        Returns:
            pd.Series: Robust z-score series.
        """
        series = pd.to_numeric(series, errors="coerce")
        rolling_median = series.rolling(
            window=window, min_periods=1
        ).median()

        mad = series.rolling(
            window=window, min_periods=1
        ).apply(
            lambda x: np.median(
                np.abs(x - np.median(x))), raw=True
        )

        positive_mad = mad[mad > 0]
        replacement = positive_mad.median() if not positive_mad.empty else 1
        mad = mad.replace(0, replacement)
        mad = mad.fillna(1)

        zscore = 0.6745 * (series - rolling_median) / mad
        return pd.Series(zscore, index=series.index, name="zscore")

    def _detect_plateaux(
        self,
        series: pd.Series,
        timestamps: pd.Series,
        min_duration_minutes: int = 5,
    ) -> pd.Series:
        """
        Detect sensor plateaus (blocked sensors) over a minimum duration.

        Args:
            series: Numeric signal series.
            timestamps: Timestamp series if available.
            min_duration_minutes: Minimum plateau duration.

        Returns:
            pd.Series: Boolean mask where True means plateau detected.
        """
        series_num = pd.to_numeric(series, errors="coerce")
        _ = series_num.diff()
        plateau_mask = pd.Series(False, index=series.index, name="plateau")

        change_groups = series_num.ne(series_num.shift()).cumsum()
        ts = None
        if timestamps is not None:
            ts = pd.to_datetime(timestamps, errors="coerce")

        for _, idx in series_num.groupby(change_groups).groups.items():
            index_group = list(idx)
            if len(index_group) <= 1:
                continue

            if ts is not None and ts.notna().any():
                start_ts = ts.loc[index_group[0]]
                end_ts = ts.loc[index_group[-1]]
                if pd.notna(start_ts) and pd.notna(end_ts):
                    duration = (end_ts - start_ts).total_seconds() / 60.0
                else:
                    duration = float(len(index_group))
            else:
                duration = float(len(index_group))

            if duration >= min_duration_minutes:
                plateau_mask.loc[index_group] = True

        return plateau_mask

    def _apply_physical_limits(
        self,
        df: pd.DataFrame,
        config: dict = None,
    ) -> pd.Series:
        """
        Flag rows containing physically impossible numeric values.

        Args:
            df: Working DataFrame.
            config: Optional per-column physical bounds.

        Returns:
            pd.Series: Boolean row mask where True means physically impossible.
        """
        numeric_df = df.select_dtypes(include=[np.number]).copy()
        if numeric_df.empty:
            return pd.Series(False, index=df.index, name="physical_impossible")

        impossible = pd.Series(False, index=df.index, name="physical_impossible")

        for column in numeric_df.columns:
            col = pd.to_numeric(numeric_df[column], errors="coerce")

            if config and column in config and isinstance(config[column], dict):
                min_value = config[column].get("min", -1e6)
                max_value = config[column].get("max", 1e6)
            else:
                min_value = -1e6
                max_value = 1e6

            column_impossible = (
                col.isna()
                | np.isinf(col)
                | (col < min_value)
                | (col > max_value)
            )
            impossible = impossible | column_impossible

        return impossible

    def _classify_anomalies(
        self,
        zscore: pd.Series,
        seuil: float = 3.5,
        min_consecutive: int = 5,
    ) -> pd.Series:
        """
        Classify each point as normal, sensor noise, or process anomaly.

        Args:
            zscore: Robust z-score series.
            seuil: Detection threshold.
            min_consecutive: Minimum run length for process anomalies.

        Returns:
            pd.Series: String labels per row.
        """
        zscore = pd.to_numeric(zscore, errors="coerce").fillna(0.0)
        above = zscore.abs() > seuil
        groups = above.ne(above.shift(fill_value=False)).cumsum()
        run_lengths = above.groupby(groups).transform("size")

        classification = pd.Series("normal", index=zscore.index, name="classification")
        classification.loc[above & (run_lengths < min_consecutive)] = "bruit_capteur"
        classification.loc[above & (run_lengths >= min_consecutive)] = "anomalie_process"
        return classification

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
    ) -> dict:
        """
        Compute all cleaning steps and derive clean/anomaly DataFrames plus stats.

        Args:
            df: Raw validated DataFrame.
            target_column: Numeric target column.

        Returns:
            dict: Cleaned outputs, stats, and warnings.
        """
        df_work = df.copy()
        warnings: list[str] = []

        series = pd.to_numeric(df_work[target_column], errors="coerce")
        series_filtered = self._apply_median_filter(series, window=3)
        zscore = self._compute_mad_zscore(series_filtered, window=20)

        timestamps = df_work["timestamp"] if "timestamp" in df_work.columns else None
        if timestamps is None:
            warnings.append("Détection plateau sans timestamp réel")
        plateaux = self._detect_plateaux(series, timestamps, min_duration_minutes=5)
        physical = self._apply_physical_limits(df_work)
        classification = self._classify_anomalies(zscore, seuil=3.5, min_consecutive=5)

        type_anomalie = classification.copy()
        type_anomalie.loc[plateaux] = "capteur_bloque"
        type_anomalie.loc[physical] = "valeur_physique_impossible"

        anomaly_mask = type_anomalie != "normal"
        normal_mask = ~anomaly_mask

        df_propre = df_work.loc[normal_mask].copy()
        if not df_propre.empty:
            df_propre[target_column] = series_filtered.loc[normal_mask]

        df_anomalies = df_work.loc[anomaly_mask].copy()
        if not df_anomalies.empty:
            df_anomalies["type_anomalie"] = type_anomalie.loc[anomaly_mask]
            df_anomalies["zscore"] = zscore.loc[anomaly_mask]

        stats = {
            "total_points": int(len(df_work.index)),
            "bruit_capteur_count": int((type_anomalie == "bruit_capteur").sum()),
            "anomalie_process_count": int((type_anomalie == "anomalie_process").sum()),
            "capteur_bloque_count": int((type_anomalie == "capteur_bloque").sum()),
            "valeur_impossible_count": int((type_anomalie == "valeur_physique_impossible").sum()),
            "df_propre_count": int(len(df_propre.index)),
            "df_anomalies_count": int(len(df_anomalies.index)),
            "warnings": warnings,
        }

        return {
            "df_propre": df_propre,
            "df_anomalies": df_anomalies,
            "stats": stats,
        }

    def run(
        self,
        df: pd.DataFrame,
        state: dict,
    ) -> dict:
        """
        Validate input, run the cleaning pipeline, update state, and return structured output.

        Args:
            df: Raw DataFrame from agent_2_sql.
            state: Shared LangGraph-like state dictionary.

        Returns:
            dict: Structured cleaner result.
        """
        start_time = time.time()
        state.setdefault("errors", [])

        try:
            numeric_columns = list(df.select_dtypes(include=[np.number]).columns)
            target_column = state.get(
                "target_column",
                numeric_columns[0] if numeric_columns else "",
            )

            validation = self._validate_input(df, target_column)
            warnings = list(validation["warnings"])
            if not validation["valid"]:
                if validation["error"]:
                    state["errors"].append(validation["error"])
                return {
                    "agent": "agent_3_cleaner",
                    "status": "error",
                    "result": {
                        "total_points": int(len(df.index)) if df is not None else 0,
                        "bruit_capteur_count": 0,
                        "anomalie_process_count": 0,
                        "capteur_bloque_count": 0,
                        "valeur_impossible_count": 0,
                        "df_propre_count": 0,
                        "df_anomalies_count": 0,
                        "warnings": warnings,
                    },
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                    "error": validation["error"],
                }

            computed = self._compute(df, target_column)
            stats = computed["stats"]
            stats["warnings"] = warnings + stats["warnings"]

            df_propre = computed["df_propre"]
            # Supprimer les colonnes booléennes de df_propre
            # pour éviter que les spécialistes les utilisent
            bool_cols = df_propre.select_dtypes(
                include=['bool']).columns.tolist()
            if bool_cols:
                df_propre = df_propre.drop(
                    columns=bool_cols)
                logger.info(
                    f"Colonnes booléennes supprimées "
                    f"de df_propre : {bool_cols}")

            state["df_propre"] = df_propre
            state["df_anomalies"] = computed["df_anomalies"]
            state["cleaning_stats"] = stats

            return {
                "agent": "agent_3_cleaner",
                "status": "success",
                "result": stats,
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "error": None,
            }
        except Exception as exc:
            logger.exception("agent_3_cleaner failed")
            state["errors"].append(str(exc))
            return {
                "agent": "agent_3_cleaner",
                "status": "error",
                "result": {
                    "total_points": int(len(df.index)) if df is not None else 0,
                    "bruit_capteur_count": 0,
                    "anomalie_process_count": 0,
                    "capteur_bloque_count": 0,
                    "valeur_impossible_count": 0,
                    "df_propre_count": 0,
                    "df_anomalies_count": 0,
                    "warnings": [],
                },
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    np.random.seed(42)
    n = 200

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="1min"
        ),
        "capteur_a": np.random.normal(100, 5, n),
        "capteur_b": np.random.normal(50, 3, n),
    })

    df_test.loc[[20, 50, 80], "capteur_a"] = df_test.loc[[20, 50, 80], "capteur_a"] * 10
    df_test.loc[100:107, "capteur_a"] = df_test.loc[100:107, "capteur_a"] * 3
    df_test.loc[150:159, "capteur_b"] = 42.0

    state = {"target_column": "capteur_a"}

    cleaner = DataCleaner()
    result = cleaner.run(df_test, state)

    print(f"Total points     : {result['result']['total_points']}")
    print(f"Bruits capteur   : {result['result']['bruit_capteur_count']}")
    print(f"Anomalies process: {result['result']['anomalie_process_count']}")
    print(f"Capteurs bloqués : {result['result']['capteur_bloque_count']}")
    print(f"Points propres   : {result['result']['df_propre_count']}")
    print(f"Points anomalies : {result['result']['df_anomalies_count']}")
    print(f"Temps            : {result['execution_time_ms']}ms")
    print(f"Erreur           : {result['error']}")
