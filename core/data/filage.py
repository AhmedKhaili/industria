"""
Simulateur du processus FILAGE — traçabilité, process, métrologie produit.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass
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
CSV_NAME = "filage.csv"

N_LVDT = 21
LVDT_ECART_MAX_MM = 0.1

# Bruit métrologie produit
DIAM_SIGMA_FRAC = 0.12
LONG_SIGMA_FRAC = 0.12
CONC_SIGMA_MM = 0.008

# Dérive température (°C) max sur les pyromètres à fin de série
DERIVE_PYRO_MAX_C = 42.0
# Impact direct sur diamètre (mm) à fin de dérive
DERIVE_DIAM_MM_MAX = 0.055


def _filage_specs(modele: str) -> dict[str, dict[str, float]]:
    return CONFIG["pieces"][modele]["filage"]


def _conforme(val: float, lti: float, lst: float) -> bool:
    return lti <= val <= lst


def _horodatage() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


@dataclass
class FilageState:
    prochaine_pastille_id: int = 10_000
    compteur_chauffe_ok: int = 0
    compteur_frappe_ok: int = 0
    anomaly_phase: int | None = None
    drift_sign: float = 1.0


def run_cycle(
    modele: str,
    rng: np.random.Generator,
    state: FilageState,
) -> dict[str, object]:
    pf = CONFIG["process"]["filage"]
    specs = _filage_specs(modele)
    sp_d = specs["diametre_apres_filage_mm"]
    sp_l = specs["longueur_apres_filage_mm"]
    sp_c = specs["concentricite_mm"]

    nom_d, lti_d, lst_d = sp_d["nominal"], sp_d["LTI"], sp_d["LST"]
    nom_l, lti_l, lst_l = sp_l["nominal"], sp_l["LTI"], sp_l["LST"]
    nom_c, lti_c, lst_c = sp_c["nominal"], sp_c["LTI"], sp_c["LST"]

    tol_d = lst_d - lti_d
    tol_l = lst_l - lti_l
    sigma_d = max(0.002, DIAM_SIGMA_FRAC * (tol_d / 2))
    sigma_l = max(0.02, LONG_SIGMA_FRAC * (tol_l / 2))

    regime = "normal"
    severity = 0.0
    ap = state.anomaly_phase
    if ap is not None and 1 <= ap <= 10:
        severity = ap / 10.0
        regime = f"derive_{ap}"

    drift_sign = state.drift_sign
    temp_shift = drift_sign * severity * DERIVE_PYRO_MAX_C
    diam_shift_process = drift_sign * severity * DERIVE_DIAM_MM_MAX

    # --- Traçabilité ---
    fournisseur = random.choice(pf["fournisseurs"])
    pastille_id = state.prochaine_pastille_id
    state.prochaine_pastille_id += 1
    pastille_retaillee = random.random() < 0.22
    numero_passage = random.randint(1, 5)

    four_consigne = random.uniform(400.0, 600.0)
    four_reel = four_consigne * random.uniform(0.95, 1.05)

    # --- Puissance inducteurs ---
    p1_c = random.uniform(50.0, 150.0)
    p2_c = random.uniform(50.0, 150.0)
    p1_r = p1_c * random.uniform(0.97, 1.03)
    p2_r = p2_c * random.uniform(0.97, 1.03)

    # --- Pyromètres & points (dérive = inducteur) ---
    py1 = random.uniform(800.0, 1200.0) + temp_shift
    py2 = random.uniform(800.0, 1200.0) + temp_shift * 0.92

    points: dict[str, float] = {}
    for ind in (1, 2):
        base = py1 if ind == 1 else py2
        for pt in range(1, 5):
            jitter = float(rng.normal(0, 8.0))
            v = base * random.uniform(0.97, 1.03) + jitter
            v = float(np.clip(v, 720.0, 1180.0))
            points[f"inducteur_{ind}_point_{pt}_C"] = round(v, 2)

    # --- Frettes ---
    fi_c = random.uniform(150.0, 200.0)
    fi_r = fi_c + float(rng.normal(0.0, 1.2))
    fe_c = random.uniform(120.0, 180.0)
    fe_r = fe_c + float(rng.normal(0.0, 1.2))

    # --- LVDT 1..21 ---
    lvdt: dict[str, float] = {}
    for i in range(1, N_LVDT + 1):
        cons = round(random.uniform(12.0, 48.0), 4)
        reel = cons + random.uniform(-LVDT_ECART_MAX_MM, LVDT_ECART_MAX_MM)
        reel = round(reel, 4)
        lvdt[f"lvdt_{i:02d}_consigne_mm"] = cons
        lvdt[f"lvdt_{i:02d}_reel_mm"] = reel
        lvdt[f"lvdt_{i:02d}_ecart_mm"] = round(reel - cons, 4)

    t_chauffe = random.uniform(10.0, 30.0)
    t_transition = random.uniform(2.0, 8.0)

    machine = random.choice(pf["machines"])
    nom_recette = random.choice(pf["recettes"])

    # Compteurs cumulés (chauffe si plage pyromètres nominale, frappe si diamètre OK)
    pyros_ok = 780.0 <= py1 <= 1220.0 and 780.0 <= py2 <= 1220.0
    if pyros_ok:
        state.compteur_chauffe_ok += 1

    # --- Mesures produit ---
    diam_mes = (
        nom_d
        + float(rng.normal(0.0, sigma_d))
        + diam_shift_process
        + 0.0008 * (temp_shift)
    )
    long_mes = (
        nom_l
        + float(rng.normal(0.0, sigma_l))
        + 0.15 * diam_shift_process
    )
    conc_mes = max(
        0.0,
        abs(float(rng.normal(0.0, CONC_SIGMA_MM)))
        + 0.02 * severity * abs(drift_sign),
    )

    ok_d = _conforme(diam_mes, lti_d, lst_d)
    ok_l = _conforme(long_mes, lti_l, lst_l)
    ok_c = _conforme(conc_mes, lti_c, lst_c)
    ok_global = ok_d and ok_l and ok_c

    if ok_d:
        state.compteur_frappe_ok += 1

    row: dict[str, object] = {
        "horodatage": _horodatage(),
        "modele": modele,
        "fournisseur_matiere": fournisseur,
        "numero_pastille": pastille_id,
        "pastille_retaillee": pastille_retaillee,
        "numero_passage": numero_passage,
        "four_consigne_C": round(four_consigne, 2),
        "four_reel_C": round(four_reel, 2),
        "inducteur_puissance_1_consigne_kW": round(p1_c, 3),
        "inducteur_puissance_1_reel_kW": round(p1_r, 3),
        "inducteur_puissance_2_consigne_kW": round(p2_c, 3),
        "inducteur_puissance_2_reel_kW": round(p2_r, 3),
        "pyrometre_inducteur_1_C": round(py1, 2),
        "pyrometre_inducteur_2_C": round(py2, 2),
        "frette_int_consigne_C": round(fi_c, 2),
        "frette_int_reel_C": round(fi_r, 2),
        "frette_ext_consigne_C": round(fe_c, 2),
        "frette_ext_reel_C": round(fe_r, 2),
        "temps_chauffe_inducteur_s": round(t_chauffe, 2),
        "temps_transition_s": round(t_transition, 2),
        "compteur_chauffe_ok": state.compteur_chauffe_ok,
        "compteur_frappe_ok": state.compteur_frappe_ok,
        "machine": machine,
        "nom_recette": nom_recette,
        "diametre_apres_filage_mm": round(diam_mes, 4),
        "longueur_apres_filage_mm": round(long_mes, 3),
        "concentricite_mm": round(conc_mes, 5),
        "conformite_diametre": "OK" if ok_d else "NOK",
        "conformite_longueur": "OK" if ok_l else "NOK",
        "conformite_concentricite": "OK" if ok_c else "NOK",
        "conformite_globale": "OK" if ok_global else "NOK",
        "ecart_diametre_mm": round(diam_mes - nom_d, 4),
        "ecart_longueur_mm": round(long_mes - nom_l, 3),
        "ecart_concentricite_mm": round(conc_mes - nom_c, 5),
        "regime_anomalie": regime,
    }
    row.update(points)
    row.update(lvdt)

    # --- Transition anomalie (dérive 10 cycles puis retour normal) ---
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
    parser = argparse.ArgumentParser(description="Simulateur filage (cycle périodique)")
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
    state = FilageState()
    csv_path: Path = args.csv

    print(
        f"Filage — {args.modele}, CSV: {csv_path}, intervalle {args.interval}s "
        f"(Ctrl+C pour arrêter)",
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
