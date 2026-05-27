"""
Source de vérité unique pour les paramètres métier IndustrIA.
Jamais de LLM — lire depuis les agents, jamais hardcoder ailleurs.
"""

from __future__ import annotations

# ── Machine / process ───────────────────────────────────
MACHINE_CONFIG = {
    "default": {
        "nom": "Machine inconnue",
        "cout_horaire": 500,
        "unite_production": "pièces/h",
        "capacite_nominale": 100,
        "mtbf_cible_h": 2000,
        "lsl": None,
        "usl": None,
        "capteurs": [],
    },
    "PRESSE_01": {
        "nom": "Presse hydraulique 01",
        "cout_horaire": 750,
        "unite_production": "pièces/h",
        "capacite_nominale": 120,
        "mtbf_cible_h": 1500,
        "lsl": 95.0,
        "usl": 105.0,
        "capteurs": ["pression_bar", "temperature_c", "vitesse_mm_s"],
    },
}

# ── Paramètres financiers ───────────────────────────────
FINANCIAL_PARAMS = {
    "cout_horaire_defaut": 500,
    "cout_rebut_piece": 45,
    "heures_arret_P1": 8,
    "heures_arret_P2": 2,
    "heures_arret_P3": 0.5,
    "heures_arret_P4": 0,
    "marge_securite": 1.2,
}

# ── Golden batch (références qualité) ──────────────────
GOLDEN_BATCH_IDS: list[str] = [
    # Identifiants des lots de référence en production
    # À remplir avec données terrain LISI
]

# ── Seuils alertes ISA-18.2 ─────────────────────────────
ALERT_THRESHOLDS = {
    "P1": {"cpk_max": 0.67, "anomaly_pct_min": 20},
    "P2": {"zscore_min": 5, "anomaly_pct_min": 10},
    "P3": {"anomaly_pct_min": 5},
    "P4": {"mann_kendall_p_max": 0.05},
}

# ── Monitoring cron ─────────────────────────────────────
MONITORING_CONFIG = {
    "cron_interval_minutes": 60,
    "zscore_window": 20,
    "zscore_threshold": 3.0,
    "escalade_p1_minutes": 5,
    "sql_timeout_ms": 1000,
    "ollama_timeout_s": 30,
    "sql_limit": 100,
}

# ── Profils utilisateurs ────────────────────────────────
USER_PROFILES = {
    "operateur": {
        "max_tokens": 150,
        "temperature": 0.1,
        "forbidden_words": [
            "z-score",
            "zscore",
            "écart-type",
            "variance",
            "p-value",
            "shapiro",
            "anova",
            "médiane",
            "percentile",
            "sigma",
            "UCL",
            "LCL",
            "Cpk",
            "EWMA",
            "CUSUM",
        ],
    },
    "technicien": {
        "max_tokens": 250,
        "temperature": 0.2,
        "forbidden_words": [],
    },
    "ingenieur": {
        "max_tokens": 350,
        "temperature": 0.3,
        "forbidden_words": [],
    },
    "directeur": {
        "max_tokens": 200,
        "temperature": 0.2,
        "forbidden_words": [
            "z-score",
            "zscore",
            "UCL",
            "LCL",
            "Shapiro",
            "ANOVA",
            "p-value",
            "EWMA",
            "CUSUM",
        ],
    },
}

# ── Modèles Ollama ──────────────────────────────────────
OLLAMA_CONFIG = {
    "model_7b": "qwen2.5-coder:7b",
    "model_14b": "qwen2.5-coder:14b",
    "keep_alive": -1,
    "num_ctx": 4096,
}


def get_machine(machine_id: str) -> dict:
    """Retourne config machine ou config default si inconnue."""
    return MACHINE_CONFIG.get(machine_id, MACHINE_CONFIG["default"])


def get_profile(profile: str) -> dict:
    """Retourne config profil ou technicien si inconnu."""
    return USER_PROFILES.get(profile, USER_PROFILES["technicien"])
