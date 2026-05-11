"""
Simulateur du processus FORMAGE — pressions, LVDT, fours, métrologie, Cp/Cpk.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Deque

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.data.config import CONFIG

INTERVAL_S = 5
ANOMALY_START_PROB = 0.05
CSV_NAME = "formage.csv"
FENETRE_CP_CPk = 50

# Bruit métrologie (fraction demi-intervalle de tolérance)
MES_SIGMA_FRAC = 0.12

# Dérive pression (fraction) max en fin de série — impact géométrie
DERIVE_PRESSION_FRAC_MAX = 0.12
DERIVE_DIAM_MM_MAX = 0.04
DERIVE_HAUTEUR_MM_MAX = 0.06


def _formage_specs(modele: str) -> dict[str, dict[str, float]]:
    return CONFIG["pieces"][modele]["formage"]


def _conforme(val: float, lti: float, lst: float) -> bool:
    return lti <= val <= lst


def _horodatage() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _cp_cpk(
    echantillon: list[float],
    lsl: float,
    usl: float,
) -> tuple[float, float]:
    arr = np.asarray(echantillon, dtype=float)
    n = arr.size
    if n < 2:
        return float("nan"), float("nan")
    m = float(arr.mean())
    s = float(arr.std(ddof=1))
    if s < 1e-9:
        return float("nan"), float("nan")
    cp = (usl - lsl) / (6.0 * s)
    cpk = min((usl - m) / (3.0 * s), (m - lsl) / (3.0 * s))
    return round(cp, 4), round(cpk, 4)


@dataclass
class FormageState:
    anomaly_phase: int | None = None
    drift_sign: float = 1.0
    historique_d_ext: Deque[float] = field(default_factory=lambda: deque(maxlen=FENETRE_CP_CPk))
    historique_d_int: Deque[float] = field(default_factory=lambda: deque(maxlen=FENETRE_CP_CPk))
    historique_hauteur: Deque[float] = field(default_factory=lambda: deque(maxlen=FENETRE_CP_CPk))
    historique_paroi: Deque[float] = field(default_factory=lambda: deque(maxlen=FENETRE_CP_CPk))


def run_cycle(
    modele: str,
    rng: np.random.Generator,
    state: FormageState,
) -> dict[str, object]:
    pf = CONFIG["process"]["formage"]
    specs = _formage_specs(modele)

    sp_de = specs["diametre_exterieur_mm"]
    sp_di = specs["diametre_interieur_mm"]
    sp_h = specs["hauteur_piece_mm"]
    sp_p = specs["epaisseur_paroi_mm"]

    nom_de, lti_de, lst_de = sp_de["nominal"], sp_de["LTI"], sp_de["LST"]
    nom_di, lti_di, lst_di = sp_di["nominal"], sp_di["LTI"], sp_di["LST"]
    nom_h, lti_h, lst_h = sp_h["nominal"], sp_h["LTI"], sp_h["LST"]
    nom_p, lti_p, lst_p = sp_p["nominal"], sp_p["LTI"], sp_p["LST"]

    def sigma_for(tol: float) -> float:
        return max(1e-6, MES_SIGMA_FRAC * (tol / 2))

    regime = "normal"
    severity = 0.0
    ap = state.anomaly_phase
    if ap is not None and 1 <= ap <= 10:
        severity = ap / 10.0
        regime = f"derive_{ap}"

    drift = state.drift_sign * severity
    press_mult = 1.0 + drift * DERIVE_PRESSION_FRAC_MAX

    # --- Pressions ---
    v1_c = random.uniform(100.0, 300.0) * press_mult
    v1_r = v1_c * random.uniform(0.985, 1.015)
    v2_c = random.uniform(80.0, 250.0) * press_mult
    v2_r = v2_c * random.uniform(0.985, 1.015)
    fou_c = random.uniform(50.0, 150.0) * (1.0 + 0.5 * (press_mult - 1.0))
    fou_r = fou_c * random.uniform(0.98, 1.02)

    row: dict[str, object] = {
        "horodatage": _horodatage(),
        "pression_verin_1_consigne_bars": round(v1_c, 3),
        "pression_verin_1_reel_bars": round(v1_r, 3),
        "pression_verin_2_consigne_bars": round(v2_c, 3),
        "pression_verin_2_reel_bars": round(v2_r, 3),
        "pression_fouloir_consigne_bars": round(fou_c, 3),
        "pression_fouloir_reel_bars": round(fou_r, 3),
    }

    # --- Positions vérin 1 & 2 (1–4) + fouloir : consigne / LVDT réel ---
    for i in range(1, 5):
        c1 = round(random.uniform(0.5, 24.0), 3)
        r1 = round(c1 + float(rng.normal(0.0, 0.035)), 3)
        row[f"verin_1_position_{i}_consigne_mm"] = c1
        row[f"verin_1_position_{i}_lvdt_reel_mm"] = r1

        c2 = round(random.uniform(0.5, 24.0), 3)
        r2 = round(c2 + float(rng.normal(0.0, 0.035)), 3)
        row[f"verin_2_position_{i}_consigne_mm"] = c2
        row[f"verin_2_position_{i}_lvdt_reel_mm"] = r2

    fc = round(random.uniform(1.0, 18.0), 3)
    fr = round(fc + float(rng.normal(0.0, 0.04)), 3)
    row["fouloir_position_consigne_mm"] = fc
    row["fouloir_position_lvdt_reel_mm"] = fr

    # Valeurs brutes (counts type ADC, corrélées aux LVDT réels moyens)
    m1 = float(np.mean([row[f"verin_1_position_{k}_lvdt_reel_mm"] for k in range(1, 5)]))
    m2 = float(np.mean([row[f"verin_2_position_{k}_lvdt_reel_mm"] for k in range(1, 5)]))
    row["lvdt_brut_verin_1"] = int(round(8000 + 420 * m1 + rng.normal(0, 25)))
    row["lvdt_brut_verin_2"] = int(round(8000 + 420 * m2 + rng.normal(0, 25)))
    row["lvdt_brut_fouloir"] = int(round(6500 + 510 * fr + rng.normal(0, 30)))

    # --- Fours gauche / droit ---
    for label in (
        "four_gauche_1",
        "four_gauche_2",
        "four_droit_1",
        "four_droit_2",
    ):
        c = random.uniform(300.0, 500.0)
        r = c * random.uniform(0.97, 1.03)
        row[f"{label}_consigne_C"] = round(c, 2)
        row[f"{label}_reel_C"] = round(r, 2)

    row["matrice"] = random.choice(pf["matrices"])
    row["machine"] = random.choice(pf["machines"])
    row["numero_programme"] = modele
    row["statut_cycle"] = random.choice(pf["statuts_cycle"])
    row["modele"] = modele

    # --- Mesures produit (dérive pression -> diamètre & hauteur) ---
    d_shift = drift * DERIVE_DIAM_MM_MAX
    h_shift = drift * DERIVE_HAUTEUR_MM_MAX

    d_ext = nom_de + float(rng.normal(0.0, sigma_for(lst_de - lti_de))) + d_shift
    d_int = nom_di + float(rng.normal(0.0, sigma_for(lst_di - lti_di))) + 0.35 * d_shift
    haut = nom_h + float(rng.normal(0.0, sigma_for(lst_h - lti_h))) + h_shift
    paroi = nom_p + float(rng.normal(0.0, sigma_for(lst_p - lti_p))) + 0.12 * d_shift

    ok_de = _conforme(d_ext, lti_de, lst_de)
    ok_di = _conforme(d_int, lti_di, lst_di)
    ok_h = _conforme(haut, lti_h, lst_h)
    ok_p = _conforme(paroi, lti_p, lst_p)
    ok_g = ok_de and ok_di and ok_h and ok_p

    state.historique_d_ext.append(d_ext)
    state.historique_d_int.append(d_int)
    state.historique_hauteur.append(haut)
    state.historique_paroi.append(paroi)

    cp_de, cpk_de = _cp_cpk(list(state.historique_d_ext), lti_de, lst_de)
    cp_di, cpk_di = _cp_cpk(list(state.historique_d_int), lti_di, lst_di)
    cp_h, cpk_h = _cp_cpk(list(state.historique_hauteur), lti_h, lst_h)
    cp_p, cpk_p = _cp_cpk(list(state.historique_paroi), lti_p, lst_p)

    row.update(
        {
            "diametre_exterieur_mm": round(d_ext, 4),
            "diametre_interieur_mm": round(d_int, 4),
            "hauteur_piece_mm": round(haut, 3),
            "epaisseur_paroi_mm": round(paroi, 4),
            "conformite_diam_ext": "OK" if ok_de else "NOK",
            "conformite_diam_int": "OK" if ok_di else "NOK",
            "conformite_hauteur": "OK" if ok_h else "NOK",
            "conformite_paroi": "OK" if ok_p else "NOK",
            "conformite_globale": "OK" if ok_g else "NOK",
            "ecart_diam_ext_mm": round(d_ext - nom_de, 4),
            "ecart_diam_int_mm": round(d_int - nom_di, 4),
            "ecart_hauteur_mm": round(haut - nom_h, 3),
            "ecart_paroi_mm": round(paroi - nom_p, 4),
            "cp_diam_ext_50": cp_de,
            "cpk_diam_ext_50": cpk_de,
            "cp_diam_int_50": cp_di,
            "cpk_diam_int_50": cpk_di,
            "cp_hauteur_50": cp_h,
            "cpk_hauteur_50": cpk_h,
            "cp_paroi_50": cp_p,
            "cpk_paroi_50": cpk_p,
            "n_echantillon_cp": len(state.historique_d_ext),
            "regime_anomalie": regime,
        }
    )

    # --- Anomalie : dérive pression 10 cycles ---
    if state.anomaly_phase is None and random.random() < ANOMALY_START_PROB:
        state.anomaly_phase = 1
        state.drift_sign = float(random.choice([-1, 1]))
    elif state.anomaly_phase is not None and 1 <= state.anomaly_phase <= 10:
        if state.anomaly_phase < 10:
            state.anomaly_phase += 1
        else:
            state.anomaly_phase = None

    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulateur formage (cycle périodique)")
    parser.add_argument(
        "--modele",
        default="PIECE_A",
        choices=sorted(CONFIG["pieces"].keys()),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent / CSV_NAME,
    )
    parser.add_argument("--interval", type=float, default=float(INTERVAL_S))
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    state = FormageState()
    csv_path: Path = args.csv

    print(
        f"Formage — {args.modele}, CSV: {csv_path}, fenêtre Cp/Cpk={FENETRE_CP_CPk}, "
        f"intervalle {args.interval}s (Ctrl+C pour arrêter)",
        flush=True,
    )

    while True:
        row = run_cycle(args.modele, rng, state)
        df = pd.DataFrame([row])
        header = not csv_path.exists() or csv_path.stat().st_size == 0
        df.to_csv(csv_path, mode="a", header=header, index=False)
        print(df.to_string(index=False), flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
