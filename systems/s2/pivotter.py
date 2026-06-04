"""
Pivot format LONG → LARGE (une colonne par tag).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

# Comportement S2 avant pivot_index_keys (Phase I2) — ordre conservé pour fallback.
_LEGACY_PIVOT_INDEX_KEYS = ("temps", "piece", "operation", "machine", "matrice")


def _pas_index_columns(context: "ClientContext", df: pd.DataFrame) -> list[str]:
    """Colonnes pastilles déclarées dans colonnes.* (clés pas_*), si présentes dans df."""
    return [
        context.colonnes[k]
        for k in context.colonnes
        if k.startswith("pas_") and context.colonnes[k] in df.columns
    ]


def _resolve_index_keys(context: "ClientContext") -> list[str] | None:
    """Clés logiques pivot_index_keys du YAML, ou None pour fallback legacy."""
    dataset = context.raw.get("dataset", {})
    if not isinstance(dataset, dict):
        return None
    keys = dataset.get("pivot_index_keys")
    if not isinstance(keys, list) or not keys:
        return None
    return [str(k) for k in keys]


def _build_pivot_id_columns(df: pd.DataFrame, context: "ClientContext") -> list[str]:
    """
    Colonnes d'index pour pivot_table : clés dataset.pivot_index_keys (si définies)
    sinon meta legacy ; toujours complété par colonnes pas_* présentes dans df.
    """
    yaml_keys = _resolve_index_keys(context)
    logical_keys = yaml_keys if yaml_keys is not None else list(_LEGACY_PIVOT_INDEX_KEYS)

    id_cols: list[str] = []
    for key in logical_keys:
        if key not in context.colonnes:
            continue
        col = context.colonnes[key]
        if col in df.columns:
            id_cols.append(col)

    pas_cols = _pas_index_columns(context, df)
    id_cols = list(dict.fromkeys(id_cols + pas_cols))
    id_cols = [c for c in id_cols if not df[c].isna().all()]
    return id_cols


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

        id_cols = _build_pivot_id_columns(df, context)
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
