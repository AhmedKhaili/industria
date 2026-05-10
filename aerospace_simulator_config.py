"""
Configuration pour un simulateur de données industrielles aéronautiques.

LTI / LST : bornes de tolérance (limite inférieure / limite supérieure).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Mesure : nominal + tolérances
# ---------------------------------------------------------------------------


def _m(nominal: float, lti: float, lst: float) -> dict[str, float]:
    return {"nominal": nominal, "LTI": lti, "LST": lst}


CONFIG: dict[str, Any] = {
    "pieces": {
        "PIECE_A": {
            "ebauche": {
                "poids_g": _m(450, 445, 455),
                "epaisseur_lubrifiant_mm": _m(0.3, 0.1, 0.5),
            },
            "filage": {
                "diametre_apres_filage_mm": _m(28.50, 28.45, 28.55),
                "longueur_apres_filage_mm": _m(125.0, 124.8, 125.2),
                "concentricite_mm": _m(0.0, 0.0, 0.05),
            },
            "formage": {
                "diametre_exterieur_mm": _m(45.00, 44.95, 45.05),
                "diametre_interieur_mm": _m(28.50, 28.45, 28.55),
                "hauteur_piece_mm": _m(38.00, 37.90, 38.10),
                "epaisseur_paroi_mm": _m(8.25, 8.22, 8.28),
            },
        },
        "PIECE_B": {
            "ebauche": {
                "poids_g": _m(620, 614, 626),
                "epaisseur_lubrifiant_mm": _m(0.35, 0.1, 0.5),
            },
            "filage": {
                "diametre_apres_filage_mm": _m(34.00, 33.94, 34.06),
                "longueur_apres_filage_mm": _m(148.0, 147.7, 148.3),
                "concentricite_mm": _m(0.0, 0.0, 0.05),
            },
            "formage": {
                "diametre_exterieur_mm": _m(52.00, 51.94, 52.06),
                "diametre_interieur_mm": _m(34.00, 33.94, 34.06),
                "hauteur_piece_mm": _m(45.00, 44.88, 45.12),
                "epaisseur_paroi_mm": _m(9.00, 8.96, 9.04),
            },
        },
        "PIECE_C": {
            "ebauche": {
                "poids_g": _m(380, 376, 384),
                "epaisseur_lubrifiant_mm": _m(0.25, 0.1, 0.5),
            },
            "filage": {
                "diametre_apres_filage_mm": _m(22.00, 21.95, 22.05),
                "longueur_apres_filage_mm": _m(98.0, 97.8, 98.2),
                "concentricite_mm": _m(0.0, 0.0, 0.05),
            },
            "formage": {
                "diametre_exterieur_mm": _m(36.00, 35.94, 36.06),
                "diametre_interieur_mm": _m(22.00, 21.95, 22.05),
                "hauteur_piece_mm": _m(30.00, 29.90, 30.10),
                "epaisseur_paroi_mm": _m(7.00, 6.97, 7.03),
            },
        },
    },
    "process": {
        "filage": {
            "machines": ["M2224", "M2225"],
            "recettes": ["3M1L1A_C", "3M1L2A_C", "3M1L3A_C"],
            "fournisseurs": ["FournA", "FournB", "FournC"],
        },
        "formage": {
            "machines": ["M1565G", "M1565D", "M1566G", "M1566D"],
            "matrices": ["MAT_1", "MAT_2", "MAT_3", "MAT_4"],
            "statuts_cycle": [
                "attente",
                "compression",
                "decompression",
                "ejection",
            ],
        },
    },
}


def get_piece_config(modele: str) -> dict[str, Any]:
    """
    Retourne la configuration complète pour un modèle de pièce :
    métrologie (ébauche, filage, formage) + paramètres process nominaux partagés.
    """
    key = modele.strip().upper() if modele else ""
    pieces = CONFIG["pieces"]
    if key not in pieces:
        known = ", ".join(sorted(pieces))
        raise KeyError(f"Modèle inconnu: {modele!r}. Modèles disponibles: {known}")
    return {
        "modele": key,
        "metrologie": pieces[key],
        "process": CONFIG["process"],
    }
