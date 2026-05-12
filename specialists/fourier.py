import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import fft, signal

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from specialists.base import BaseSpecialist

logger = logging.getLogger(__name__)


class FourierSpecialist(BaseSpecialist):
    """Frequency-domain analysis specialist using FFT."""

    def _validate_input(
        self,
        df: pd.DataFrame,
        target_column: str,
        min_rows: int = 5,
    ) -> dict:
        """
        Validate shared specialist inputs and FFT-specific constraints.

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

        if len(df.index) < 16:
            return {
                "valid": False,
                "warnings": validation["warnings"],
                "error": "Minimum 16 points pour analyse FFT",
            }

        return validation

    def _compute(
        self,
        df: pd.DataFrame,
        target_column: str,
        params: dict,
    ) -> dict:
        """
        Compute a windowed FFT and extract dominant harmonics.

        Args:
            df: Input DataFrame.
            target_column: Target numeric column from shared state.
            params: Specialist parameters containing `sampling_rate` and `n_harmonics`.

        Returns:
            dict: Frequency-domain summary with dominant harmonics.
        """
        sampling_rate = float(params.get("sampling_rate", 1.0))
        n_harmonics = int(params.get("n_harmonics", 5))

        if sampling_rate <= 0:
            raise ValueError("sampling_rate doit etre strictement positif")
        if n_harmonics <= 0:
            raise ValueError("n_harmonics doit etre strictement positif")

        series = pd.to_numeric(df[target_column], errors="coerce").dropna().to_numpy(dtype=float)
        n = len(series)

        if n < 16:
            raise ValueError("Minimum 16 points pour analyse FFT")

        series_centered = series - series.mean()

        window = signal.windows.hann(n)
        series_windowed = series_centered * window

        fft_values = fft.fft(series_windowed)
        fft_magnitude = np.abs(fft_values[: n // 2])
        freqs = fft.fftfreq(n, d=1.0 / sampling_rate)
        freqs_pos = freqs[: n // 2]

        fft_magnitude = fft_magnitude / (n / 2)

        positive_magnitude = fft_magnitude[1:]
        if positive_magnitude.size == 0:
            raise ValueError("Signal trop court pour extraire des frequences positives")

        indices_sorted = np.argsort(positive_magnitude)[::-1] + 1
        top_indices = indices_sorted[: min(n_harmonics, len(indices_sorted))]

        max_positive_amplitude = float(positive_magnitude.max()) if positive_magnitude.size else 0.0

        harmoniques: list[dict] = []
        for idx in top_indices:
            freq = float(freqs_pos[idx])
            amplitude = float(fft_magnitude[idx])
            periode = 1.0 / freq if freq > 0 else None
            energie_relative = (
                round(amplitude / max_positive_amplitude * 100, 2)
                if max_positive_amplitude > 0 else 0.0
            )
            harmoniques.append({
                "frequence_hz": round(freq, 6),
                "amplitude": round(amplitude, 4),
                "periode_s": round(periode, 3) if periode else None,
                "energie_relative": energie_relative,
            })

        energie_totale = float(np.sum(fft_magnitude ** 2))
        freq_dominante = harmoniques[0] if harmoniques else None

        periodique = any(
            harmonique["energie_relative"] > 30
            for harmonique in harmoniques
        )

        logger.info(
            "FFT calculee pour %s avec sampling_rate=%s Hz et %s harmoniques",
            target_column,
            sampling_rate,
            len(harmoniques),
        )

        return {
            "colonne": target_column,
            "n": n,
            "sampling_rate_hz": sampling_rate,
            "frequence_dominante": freq_dominante,
            "harmoniques": harmoniques,
            "energie_totale": round(energie_totale, 4),
            "signal_periodique": periodique,
            "interpretation": (
                f"Signal periodique detecte - frequence dominante : "
                f"{freq_dominante['frequence_hz']} Hz "
                f"(periode : {freq_dominante['periode_s']}s)"
                if periodique and freq_dominante
                else "Aucune periodicite dominante detectee"
            ),
        }


if __name__ == "__main__":
    np.random.seed(42)
    n = 256
    sampling_rate = 10.0

    t = np.linspace(0, n / sampling_rate, n)

    signal_test = (
        5 * np.sin(2 * np.pi * 1.0 * t)
        + 2 * np.sin(2 * np.pi * 3.0 * t)
        + np.random.normal(0, 0.5, n)
    )

    df_test = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-01-01", periods=n, freq="100ms"
        ),
        "vibration": signal_test,
    })

    state = {"target_column": "vibration"}
    params = {
        "sampling_rate": sampling_rate,
        "n_harmonics": 5,
    }

    specialist = FourierSpecialist()
    result = specialist.run(df_test, state, params)

    print(f"Agent      : {result['agent']}")
    print(f"Status     : {result['status']}")
    print(f"Periodique : {result['result']['signal_periodique']}")
    print("\nHarmoniques :")
    for harmonique in result["result"]["harmoniques"]:
        print(
            f"  {harmonique['frequence_hz']:.3f} Hz -> "
            f"amp={harmonique['amplitude']:.3f} "
            f"energie={harmonique['energie_relative']:.1f}%"
        )
    print(f"\nInterpret  : {result['result']['interpretation']}")
    print(f"Temps      : {result['execution_time_ms']}ms")
    print(f"Erreur     : {result['error']}")
