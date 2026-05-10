"""
Moteur d'anomalies progressives pour simulateur industriel aéronautique.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class AnomalyEngine:
    """
    Dérives linéaires, pics, conformité, capabilité (Cp/Cpk), précurseurs de rebut.
    """

    def __init__(
        self,
        n_cycles_drift: int = 10,
        rupture_surplus_frac: float = 0.35,
        rng: np.random.Generator | None = None,
    ) -> None:
        """
        n_cycles_drift : nombre de cycles de rampe linéaire avant rupture franche.
        rupture_surplus_frac : fraction de ``amplitude`` ajoutée au-delà de la rampe.
        """
        self.n_cycles_drift = max(1, int(n_cycles_drift))
        self.rupture_surplus_frac = float(rupture_surplus_frac)
        self.rng = rng if rng is not None else np.random.default_rng()

    def inject_drift(self, valeur: float, cycle: int, amplitude: float) -> float:
        """
        Dérive progressive linéaire sur ``n_cycles_drift`` cycles, puis rupture franche.

        - ``cycle`` : indice courant (1 = premier cycle de dérive).
        - ``amplitude`` : écart ajouté en fin de rampe (signé : direction de la dérive).

        Pour ``cycle`` > ``n_cycles_drift``, applique la rampe complète + surplus de rupture
        (même signe que ``amplitude``).
        """
        v = float(valeur)
        amp = float(amplitude)
        c = int(cycle)
        n = self.n_cycles_drift

        if c <= 0:
            return v

        rampe_complete = amp
        if c <= n:
            return v + (c / n) * amp

        surplus = abs(amp) * self.rupture_surplus_frac
        sign = 1.0 if amp >= 0 else -1.0
        return v + rampe_complete + sign * surplus

    def inject_spike(self, valeur: float, amplitude: float) -> float:
        """Pic ponctuel aléatoire uniforme dans ``[-amplitude, amplitude]``."""
        v = float(valeur)
        a = abs(float(amplitude))
        if a == 0.0:
            return v
        delta = float(self.rng.uniform(-a, a))
        return v + delta

    def check_conformite(
        self,
        mesure: float,
        nominal: float,
        lti: float,
        lst: float,
    ) -> dict[str, Any]:
        """
        Retourne conformité OK/NOK, écart au nominal, % hors tolérance.

        ``pct_hors_tolerance`` : 0 si dans [LTI, LST], sinon distance hors bornes
        rapportée à l'intervalle (LST-LTI) en pourcentage.
        """
        m = float(mesure)
        nom = float(nominal)
        lo = float(lti)
        hi = float(lst)
        ecart = m - nom

        if lo > hi:
            lo, hi = hi, lo

        span = hi - lo
        if span <= 0:
            raise ValueError("LST doit être strictement supérieur à LTI.")

        ok = lo <= m <= hi
        if ok:
            pct = 0.0
        elif m < lo:
            pct = (lo - m) / span * 100.0
        else:
            pct = (m - hi) / span * 100.0

        return {
            "conformite": "OK" if ok else "NOK",
            "ecart": round(ecart, 6),
            "pct_hors_tolerance": round(pct, 4),
        }

    def calculer_cp_cpk(
        self,
        mesures: list[float] | np.ndarray | pd.Series,
        nominal: float,
        lti: float,
        lst: float,
    ) -> dict[str, float]:
        """
        Cp = (LST - LTI) / (6 * sigma)
        Cpk = min((LST - mean) / (3 * sigma), (mean - LTI) / (3 * sigma))

        ``mesures`` : les N dernières mesures (déjà fenêtrées côté appelant si besoin).
        """
        _ = float(nominal)  # réservé cohérence API / traçabilité métier
        lo = float(lti)
        hi = float(lst)
        if lo > hi:
            lo, hi = hi, lo

        s = pd.Series(mesures, dtype=float).dropna()
        arr = s.to_numpy()
        n = arr.size
        if n < 2:
            return {"cp": float("nan"), "cpk": float("nan"), "n": float(n)}

        mean = float(arr.mean())
        sigma = float(arr.std(ddof=1))
        if sigma < 1e-12:
            return {"cp": float("nan"), "cpk": float("nan"), "n": float(n)}

        cp = (hi - lo) / (6.0 * sigma)
        cpk = min((hi - mean) / (3.0 * sigma), (mean - lo) / (3.0 * sigma))
        return {
            "cp": round(cp, 6),
            "cpk": round(cpk, 6),
            "n": float(n),
        }

    def detect_precurseur(
        self,
        historique: list[float] | np.ndarray | pd.Series,
        fenetre: int = 10,
        *,
        lti: float | None = None,
        lst: float | None = None,
    ) -> dict[str, Any]:
        """
        Détecte une dérive susceptible de précéder une sortie de tolérance.

        Ajuste une droite sur les ``fenetre`` derniers points ; si ``lti``/``lst`` sont
        fournis et que la mesure courante est encore conforme, estime le nombre de
        cycles avant franchissement (extrapolation linéaire).

        Retourne :
        - ``derive_detectee`` : True si tendance significative vers une limite
        - ``cycles_restants_estimes`` : float ou None (None si indéterminé)
        - ``pente`` : pente par cycle sur la fenêtre
        """
        f = max(3, int(fenetre))
        ser = pd.Series(historique, dtype=float).dropna()
        if ser.size < f:
            y = ser.to_numpy()
        else:
            y = ser.iloc[-f:].to_numpy()
        n = y.size
        if n < 3:
            return {
                "derive_detectee": False,
                "cycles_restants_estimes": None,
                "pente": float("nan"),
            }

        x = np.arange(n, dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        slope = float(slope)
        dernier = float(y[-1])

        if lti is None or lst is None:
            # Dérive « générique » : pente non nulle vs bruit (seuil empirique simple)
            resid = y - (intercept + slope * x)
            noise = float(np.std(resid, ddof=1)) if n > 2 else 0.0
            thresh = max(1e-9, 0.35 * noise if noise > 0 else abs(slope))
            derive = abs(slope) > thresh
            return {
                "derive_detectee": bool(derive),
                "cycles_restants_estimes": None,
                "pente": round(slope, 8),
            }

        lo = float(lti)
        hi = float(lst)
        if lo > hi:
            lo, hi = hi, lo

        if not (lo <= dernier <= hi):
            return {
                "derive_detectee": False,
                "cycles_restants_estimes": 0.0,
                "pente": round(slope, 8),
            }

        if abs(slope) < 1e-12:
            return {
                "derive_detectee": False,
                "cycles_restants_estimes": None,
                "pente": 0.0,
            }

        # Indices continus x ; dernier indice = n - 1. Temps jusqu'au franchissement.
        candidates: list[float] = []
        for bound in (lo, hi):
            t_star = (bound - intercept) / slope
            if t_star > n - 1 + 1e-9:
                candidates.append(float(t_star))

        if not candidates:
            return {
                "derive_detectee": False,
                "cycles_restants_estimes": None,
                "pente": round(slope, 8),
            }

        t_hit = min(candidates)
        cycles_restants = t_hit - (n - 1)

        derive = 0 < cycles_restants < 1e6

        return {
            "derive_detectee": bool(derive),
            "cycles_restants_estimes": float(round(cycles_restants, 4))
            if derive
            else None,
            "pente": round(slope, 8),
        }
