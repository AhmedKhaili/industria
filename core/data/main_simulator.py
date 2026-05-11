"""
Orchestrateur principal — Ébauche, Filage et Formage en parallèle (threads).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from core.data import ebauche as mod_ebauche
from core.data import filage as mod_filage
from core.data import formage as mod_formage
from core.data.config import CONFIG
from core.data.filage import FilageState
from core.data.formage import FormageState

DATA_DIR = Path(__file__).resolve().parent

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CLEAR_SCREEN = "\033[2J\033[H"


@dataclass
class ProcessSnapshot:
    pieces: int = 0
    conformes: int = 0
    last_row: dict = field(default_factory=dict)


@dataclass
class LiveBoard:
    lock: threading.Lock = field(default_factory=threading.Lock)
    ebauche: ProcessSnapshot = field(default_factory=ProcessSnapshot)
    filage: ProcessSnapshot = field(default_factory=ProcessSnapshot)
    formage: ProcessSnapshot = field(default_factory=ProcessSnapshot)


def _conforme_globale(row: dict) -> bool:
    cg = str(row.get("conformite_globale", "")).upper()
    return cg == "OK"


def _regime_anomalie(row: dict) -> str:
    return str(row.get("regime_anomalie", "normal"))


def _alerte_processus(nom: str, row: dict) -> list[str]:
    msgs: list[str] = []
    reg = _regime_anomalie(row)
    if reg != "normal":
        msgs.append(f"{nom}: régime {reg}")
    if not _conforme_globale(row):
        msgs.append(f"{nom}: conformité globale NOK/KO")
    return msgs


def _pct(conformes: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return 100.0 * conformes / total


def _append_csv(row: dict, path: Path) -> None:
    df = pd.DataFrame([row])
    header = not path.exists() or path.stat().st_size == 0
    df.to_csv(path, mode="a", header=header, index=False)


def worker_ebauche(
    stop: threading.Event,
    modele: str,
    csv_path: Path,
    interval: float,
    rng: np.random.Generator,
    board: LiveBoard,
) -> None:
    phase: int | None = None
    drift_sign = 1.0
    while not stop.is_set():
        row, phase, drift_sign = mod_ebauche.run_cycle(modele, rng, phase, drift_sign)
        _append_csv(row, csv_path)
        ok = _conforme_globale(row)
        with board.lock:
            s = board.ebauche
            s.pieces += 1
            if ok:
                s.conformes += 1
            s.last_row = dict(row)
        if stop.wait(timeout=interval):
            break


def worker_filage(
    stop: threading.Event,
    modele: str,
    csv_path: Path,
    interval: float,
    rng: np.random.Generator,
    board: LiveBoard,
) -> None:
    state = FilageState()
    while not stop.is_set():
        row = mod_filage.run_cycle(modele, rng, state)
        _append_csv(row, csv_path)
        ok = _conforme_globale(row)
        with board.lock:
            s = board.filage
            s.pieces += 1
            if ok:
                s.conformes += 1
            s.last_row = dict(row)
        if stop.wait(timeout=interval):
            break


def worker_formage(
    stop: threading.Event,
    modele: str,
    csv_path: Path,
    interval: float,
    rng: np.random.Generator,
    board: LiveBoard,
) -> None:
    state = FormageState()
    while not stop.is_set():
        row = mod_formage.run_cycle(modele, rng, state)
        _append_csv(row, csv_path)
        ok = _conforme_globale(row)
        with board.lock:
            s = board.formage
            s.pieces += 1
            if ok:
                s.conformes += 1
            s.last_row = dict(row)
        if stop.wait(timeout=interval):
            break


def render_dashboard(
    board: LiveBoard,
    modele: str,
    interval_s: float,
    csv_names: tuple[str, str, str],
) -> None:
    with board.lock:
        eb = board.ebauche
        fi = board.filage
        fo = board.formage

    lines: list[str] = []
    lines.append(f"{BOLD}IndustrIA Simulator v0.1 — LISI Aerospace{RESET}")
    lines.append(
        f"{BOLD}Processus actifs :{RESET} Ébauche {DIM}|{RESET} Filage "
        f"{DIM}|{RESET} Formage",
    )
    lines.append(f"{BOLD}Tableau de bord temps réel{RESET}")
    lines.append(DIM + "Ctrl+C pour arrêt propre (CSV déjà écrits sur disque)." + RESET)
    lines.append(
        f"Modèle {BOLD}{modele}{RESET}  ·  cycle {interval_s}s  ·  "
        f"CSV : {csv_names[0]}, {csv_names[1]}, {csv_names[2]}",
    )
    lines.append("")

    def bloc(nom: str, snap: ProcessSnapshot, capteurs: list[tuple[str, str]]) -> None:
        n, c = snap.pieces, snap.conformes
        pct = _pct(c, n)
        col = GREEN if pct >= 95 and n else YELLOW if pct >= 85 or not n else RED
        lines.append(f"{BOLD}{nom}{RESET}  pièces: {n}  taux conformité: {col}{pct:.1f}%{RESET}")
        if not snap.last_row:
            lines.append(f"  {DIM}(en attente de la 1ʳᵉ mesure…){RESET}")
        else:
            for label, key in capteurs:
                v = snap.last_row.get(key, "—")
                lines.append(f"  · {label}: {v}")
        lines.append("")

    bloc(
        "ÉBAUCHE",
        eb,
        [
            ("Vitesse coupe (m/min)", "vitesse_coupe_m_min"),
            ("Débit coupe (L/min)", "debit_coupe_l_min"),
            ("Poids final (g)", "poids_final_g"),
            ("Lubrifiant mesuré (mm)", "epaisseur_lubrifiant_mesuree_mm"),
            ("Régime", "regime_anomalie"),
            ("Conformité", "conformite_globale"),
        ],
    )
    bloc(
        "FILAGE",
        fi,
        [
            ("Pyromètre inducteur 1 (°C)", "pyrometre_inducteur_1_C"),
            ("Pyromètre inducteur 2 (°C)", "pyrometre_inducteur_2_C"),
            ("Diamètre après filage (mm)", "diametre_apres_filage_mm"),
            ("Machine", "machine"),
            ("Régime", "regime_anomalie"),
            ("Conformité", "conformite_globale"),
        ],
    )
    bloc(
        "FORMAGE",
        fo,
        [
            ("Pression vérin 1 réel (bar)", "pression_verin_1_reel_bars"),
            ("Pression vérin 2 réel (bar)", "pression_verin_2_reel_bars"),
            ("Diamètre ext. (mm)", "diametre_exterieur_mm"),
            ("Hauteur pièce (mm)", "hauteur_piece_mm"),
            ("Statut cycle", "statut_cycle"),
            ("Régime", "regime_anomalie"),
            ("Conformité", "conformite_globale"),
        ],
    )

    alertes: list[str] = []
    if eb.last_row:
        alertes.extend(_alerte_processus("Ébauche", eb.last_row))
    if fi.last_row:
        alertes.extend(_alerte_processus("Filage", fi.last_row))
    if fo.last_row:
        alertes.extend(_alerte_processus("Formage", fo.last_row))

    lines.append(f"{BOLD}Alertes{RESET}")
    if not alertes:
        lines.append(f"  {GREEN}Aucune alerte active.{RESET}")
    else:
        for a in alertes:
            lines.append(f"  {RED}▌ {a}{RESET}")

    text = "\n".join(lines)
    # Efface l’écran et replace le curseur (sans dépendre de `clear` externe)
    sys.stdout.write(CLEAR_SCREEN + text + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orchestrateur simulateur aéronautique (3 fils)",
    )
    parser.add_argument(
        "--modele",
        default="PIECE_A",
        choices=sorted(CONFIG["pieces"].keys()),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(mod_ebauche.INTERVAL_S),
        help="Intervalle entre pièces par processus (s)",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--refresh",
        type=float,
        default=0.4,
        help="Période rafraîchissement dashboard (s)",
    )
    args = parser.parse_args()

    base = args.seed
    if base is None:
        base = int(time.time()) % 100_000
    rng_e = np.random.default_rng(base)
    rng_f = np.random.default_rng(base + 11)
    rng_g = np.random.default_rng(base + 23)

    csv_e = DATA_DIR / mod_ebauche.CSV_NAME
    csv_f = DATA_DIR / mod_filage.CSV_NAME
    csv_g = DATA_DIR / mod_formage.CSV_NAME

    stop = threading.Event()
    board = LiveBoard()

    threads = [
        threading.Thread(
            target=worker_ebauche,
            name="ebauche",
            args=(stop, args.modele, csv_e, args.interval, rng_e, board),
            daemon=False,
        ),
        threading.Thread(
            target=worker_filage,
            name="filage",
            args=(stop, args.modele, csv_f, args.interval, rng_f, board),
            daemon=False,
        ),
        threading.Thread(
            target=worker_formage,
            name="formage",
            args=(stop, args.modele, csv_g, args.interval, rng_g, board),
            daemon=False,
        ),
    ]

    csv_triple = (csv_e.name, csv_f.name, csv_g.name)
    print(DIM + "Démarrage des fils d’exécution…" + RESET)
    time.sleep(0.2)

    for t in threads:
        t.start()

    try:
        while not stop.is_set():
            render_dashboard(board, args.modele, args.interval, csv_triple)
            time.sleep(max(0.1, args.refresh))
    except KeyboardInterrupt:
        stop.set()

    for t in threads:
        t.join(timeout=args.interval + 2.0)

    # Dernière image + message de fin
    render_dashboard(board, args.modele, args.interval, csv_triple)
    print()
    print(
        f"{GREEN}Arrêt demandé.{RESET} Fichiers CSV enregistrés sous : "
        f"{os.fspath(DATA_DIR)}",
    )
    print(f"  · {csv_e.name}")
    print(f"  · {csv_f.name}")
    print(f"  · {csv_g.name}")


if __name__ == "__main__":
    main()
