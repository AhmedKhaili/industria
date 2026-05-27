"""
Lecture d'une partition Parquet selon intent (pièce + opération).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from systems.s2.partitioner import cache_dir

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

MAX_VAGUE_ROWS = 500_000


def _resolve_piece_operation(intent: dict) -> tuple[str | None, str | None]:
    filtres = intent.get("filtres") or {}
    piece = intent.get("piece") or filtres.get("piece")
    operation = intent.get("operation") or filtres.get("operation")
    if isinstance(piece, list):
        piece = piece[0] if piece else None
    return piece, operation


def is_vague_intent(intent: dict) -> bool:
    filtres = intent.get("filtres") or {}
    piece, operation = _resolve_piece_operation(intent)
    has_date = bool(
        filtres.get("Date_debut")
        or filtres.get("Date_fin")
        or filtres.get("jeton")
    )
    return not piece and not operation and not has_date


def load_partition(
    yaml_path: str,
    context: "ClientContext",
    intent: dict,
) -> dict:
    try:
        if is_vague_intent(intent):
            return {
                "error": None,
                "df": None,
                "vague": True,
                "piece": None,
                "operation": None,
            }

        piece, operation = _resolve_piece_operation(intent)
        if not piece or not operation:
            return {
                "error": "Intent incomplet : pièce et opération requises pour S2",
                "df": None,
            }

        path = cache_dir(yaml_path) / str(operation) / f"{piece}.parquet"
        if not path.is_file():
            return {"error": f"Partition introuvable : {path}", "df": None}

        df = pd.read_parquet(path)
        col_piece = context.colonnes.get("piece", "Designation Reference")
        col_op = context.colonnes.get("operation", "Operation")
        df = df[df[col_op] == operation]
        df = df[df[col_piece] == piece]
        return {
            "error": None,
            "df": df,
            "vague": False,
            "piece": piece,
            "operation": operation,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "df": None}


def apply_temporal_filter(
    df: pd.DataFrame,
    context: "ClientContext",
    intent: dict,
) -> dict:
    try:
        filtres = intent.get("filtres") or {}
        col_date = context.colonnes.get("temps", "Date")
        if col_date not in df.columns:
            return {"error": f"Colonne date absente : {col_date}", "df": None}

        out = df.copy()
        out[col_date] = pd.to_datetime(out[col_date], errors="coerce")
        out = out[out[col_date].notna()]

        jeton = filtres.get("jeton")
        if jeton:
            resolved = _resolve_event_dates(jeton, context)
            if resolved.get("error"):
                return {"error": resolved["error"], "df": None}
            if resolved.get("ignored"):
                pass
            else:
                debut, fin = resolved["Date_debut"], resolved["Date_fin"]
                if debut:
                    out = out[out[col_date] >= pd.Timestamp(debut)]
                if fin:
                    out = out[out[col_date] <= pd.Timestamp(fin) + pd.Timedelta(days=1)]

        debut = filtres.get("Date_debut")
        fin = filtres.get("Date_fin")
        if debut:
            out = out[out[col_date] >= pd.Timestamp(debut)]
        if fin:
            out = out[out[col_date] <= pd.Timestamp(fin) + pd.Timedelta(days=1)]

        return {"error": None, "df": out, "jeton_ignored": bool(jeton and _resolve_event_dates(jeton, context).get("ignored"))}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "df": None}


def _resolve_event_dates(jeton: str, context: "ClientContext") -> dict[str, Any]:
    """Résout un jeton EVENT_* ; ignore si pas de source SQL locale."""
    evenements = context.temps.get("evenements", {})
    if not isinstance(evenements, dict):
        return {"ignored": True}

    for _key, cfg in evenements.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("jeton") != jeton:
            continue
        sql = cfg.get("requete_sql", "")
        if not sql:
            return {"ignored": True}
        # Pas de base événements locale branchée → ignorer le jeton (spec S2)
        return {"ignored": True}

    return {"ignored": True}
