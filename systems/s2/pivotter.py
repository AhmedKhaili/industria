"""
Pivot format LONG → LARGE (une colonne par tag).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def run(
    df: pd.DataFrame,
    context: "ClientContext",
    intent: dict,
) -> dict:
    try:
        col_tag = context.colonnes.get("tag", "Tag")
        col_value = context.colonnes.get("valeur", "Value")
        if col_tag not in df.columns or col_value not in df.columns:
            return {"error": f"Colonnes pivot manquantes : {col_tag}, {col_value}", "df": None}

        meta_keys = ("temps", "piece", "operation", "machine", "matrice")
        id_cols = [
            context.colonnes[k]
            for k in meta_keys
            if k in context.colonnes and context.colonnes[k] in df.columns
        ]
        pas_cols = [
            context.colonnes[k]
            for k in context.colonnes
            if k.startswith("pas_") and context.colonnes[k] in df.columns
        ]
        id_cols = list(dict.fromkeys(id_cols + pas_cols))
        id_cols = [c for c in id_cols if not df[c].isna().all()]
        if not id_cols:
            id_cols = [c for c in df.columns if c not in (col_tag, col_value, "LTI", "LTS")]

        variables = intent.get("variables") or []
        if variables:
            df = df[df[col_tag].isin(variables)]

        wide = df.pivot_table(
            index=id_cols,
            columns=col_tag,
            values=col_value,
            aggfunc="first",
        )
        wide = wide.reset_index()
        wide.columns = [
            str(c) if not isinstance(c, tuple) else str(c[-1]) for c in wide.columns
        ]

        return {"error": None, "df": wide}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "df": None}
