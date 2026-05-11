"""
Simulateur du processus ÉBAUCHE — données process et métrologie produit.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.data.config import CONFIG

INTERVAL_S = 5
ANOMALY_START_PROB = 0.05
CSV_NAME = "ebauche.csv"

# Bruit métrologie (écart-type) — proportionnel aux tolérances
POIDS_NOISE_SIGMA_FRAC = 0.15
LUB_NOISE_SIGMA_MM = 0.012

# Amplitude max de dérive (fraction du nominal / mm) à la fin des 10 cycles
DERIVE_POIDS_FRAC_MAX = 0.045
DERIVE_LUB_MM_MAX = 0.18


def _ebauche_specs(modele: str) -> tuple[dict[str, float], dict[str, float]]:
    spec = CONFIG["pieces"][modele]["ebauche"]
    return spec["poids_g"], spec["epaisseur_lubrifiant_mm"]


def _conforme(val: float, lti: float, lst: float) -> bool:
    return lti <= val <= lst


def _horodatage() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def run_cycle(
    modele: str,
    rng: np.random.Generator,
    anomaly_phase: int | None,
    drift_sign: float,
) -> tuple[dict, int | None, float]:
    """
    Génère une ligne de simulation. Retourne (ligne, nouveau anomaly_phase, drift_sign).
    drift_sign est mis à jour seulement au démarrage d'une anomalie (-1 ou +1).
    """
    sp_poids, sp_lub = _ebauche_specs(modele)
    nom_p, lti_p, lst_p = sp_poids["nominal"], sp_poids["LTI"], sp_poids["LST"]
    nom_l, lti_l, lst_l = sp_lub["nominal"], sp_lub["LTI"], sp_lub["LST"]

    tol_poids = lst_p - lti_p
    sigma_poids = max(0.5, POIDS_NOISE_SIGMA_FRAC * (tol_poids / 2))

    regime = "normal"
    severity = 0.0

    if anomaly_phase is not None and 1 <= anomaly_phase <= 10:
        severity = anomaly_phase / 10.0
        regime = f"derive_{anomaly_phase}"
    elif anomaly_phase == 11:
        severity = 1.0
        regime = "rupture"

    # --- Paramètres process ---
    vitesse = random.uniform(80.0, 200.0)
    debit = random.uniform(5.0, 20.0)
    poids_process = nom_p * random.uniform(0.98, 1.02)
    lub_process = random.uniform(0.1, 0.5)

    if severity > 0:
        # Dérive corrélée process (même signe que la dérive produit)
        vitesse *= 1.0 + drift_sign * 0.12 * severity
        debit *= 1.0 - drift_sign * 0.08 * severity
        poids_process += drift_sign * severity * nom_p * 0.015
        lub_process += drift_sign * severity * 0.06
        lub_process = float(np.clip(lub_process, 0.05, 0.55))

    derive_poids = drift_sign * severity * nom_p * DERIVE_POIDS_FRAC_MAX
    derive_lub = drift_sign * severity * DERIVE_LUB_MM_MAX

    if regime == "rupture":
        derive_poids = drift_sign * nom_p * 0.08
        derive_lub = drift_sign * 0.35
        vitesse = max(0.0, vitesse * 0.15)
        debit = max(0.0, debit * 0.4)

    # --- Mesures produit (nominal + gaussien + dérive) ---
    poids_final = (
        nom_p
        + float(rng.normal(0.0, sigma_poids))
        + derive_poids
    )
    lub_mes = (
        nom_l
        + float(rng.normal(0.0, LUB_NOISE_SIGMA_MM))
        + derive_lub
    )
    # Légère corrélation mesure / lubrifiant appliqué en process
    lub_mes += 0.25 * (lub_process - (lti_l + lst_l) / 2)

    ok_p = _conforme(poids_final, lti_p, lst_p)
    ok_l = _conforme(lub_mes, lti_l, lst_l)
    ok_global = ok_p and ok_l

    row = {
        "horodatage": _horodatage(),
        "modele": modele,
        "vitesse_coupe_m_min": round(vitesse, 3),
        "debit_coupe_l_min": round(debit, 3),
        "poids_piece_process_g": round(poids_process, 3),
        "epaisseur_lubrifiant_process_mm": round(lub_process, 4),
        "poids_final_g": round(poids_final, 3),
        "epaisseur_lubrifiant_mesuree_mm": round(lub_mes, 4),
        "conformite_poids": "OK" if ok_p else "KO",
        "conformite_lubrifiant": "OK" if ok_l else "KO",
        "conformite_globale": "OK" if ok_global else "KO",
        "ecart_poids_g": round(poids_final - nom_p, 3),
        "ecart_lubrifiant_mm": round(lub_mes - nom_l, 4),
        "regime_anomalie": regime,
    }

    # --- Transition état anomalie ---
    new_phase = anomaly_phase
    new_sign = drift_sign

    if anomaly_phase is None and random.random() < ANOMALY_START_PROB:
        new_phase = 1
        new_sign = float(random.choice([-1, 1]))
    elif anomaly_phase is not None and 1 <= anomaly_phase <= 10:
        if anomaly_phase < 10:
            new_phase = anomaly_phase + 1
        else:
            new_phase = 11
    elif anomaly_phase == 11:
        new_phase = None

    return row, new_phase, new_sign


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulateur ébauche (cycle 5 s)")
    parser.add_argument(
        "--modele",
        default="PIECE_A",
        choices=sorted(CONFIG["pieces"].keys()),
        help="Modèle de pièce",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent / CSV_NAME,
        help="Fichier CSV de sortie",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Graine numpy (reproductibilité)",
    )
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    csv_path: Path = args.csv
    anomaly_phase: int | None = None
    drift_sign = 1.0

    print(
        f"Ébauche — modèle {args.modele}, CSV: {csv_path}, "
        f"intervalle {INTERVAL_S}s (Ctrl+C pour arrêter)",
        flush=True,
    )

    while True:
        row, anomaly_phase, drift_sign = run_cycle(
            args.modele, rng, anomaly_phase, drift_sign
        )
        df = pd.DataFrame([row])
        header = not csv_path.exists() or csv_path.stat().st_size == 0
        df.to_csv(csv_path, mode="a", header=header, index=False)
        print(df.to_string(index=False), flush=True)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
