"""
Validation du df_propre avant passage à S3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def _tag_sans_valeur_yaml(
    context: "ClientContext",
    piece: str | None,
    operation: str | None,
    tag: str,
) -> bool:
    """Tag déclaré dans le YAML mais sans tolérances (lti/lts/nominal tous null)."""
    if not piece or not operation:
        return False
    tol = context.get_tolerance(piece, operation, tag)
    if tol is None:
        return False
    return (
        tol.get("lti") is None
        and tol.get("lts") is None
        and tol.get("nominal") is None
    )


def _split_missing_variables(
    variables: list[str],
    df_columns: set[str],
    context: "ClientContext",
    piece: str | None,
    operation: str | None,
) -> tuple[list[str], list[str]]:
    missing = [v for v in variables if v not in df_columns]
    ignored: list[str] = []
    required: list[str] = []
    for tag in missing:
        if _tag_sans_valeur_yaml(context, piece, operation, tag):
            ignored.append(tag)
        else:
            required.append(tag)
    return required, ignored


def run(
    df: pd.DataFrame,
    context: "ClientContext",
    intent: dict,
) -> dict:
    try:
        if df is None or df.empty:
            return {"error": "df_propre vide", "valid": False}

        col_piece = context.colonnes.get("piece", "Designation Reference")
        col_op = context.colonnes.get("operation", "Operation")
        col_tag = context.colonnes.get("tag", "Tag")

        piece = intent.get("piece") or (intent.get("filtres") or {}).get("piece")
        operation = intent.get("operation") or (intent.get("filtres") or {}).get("operation")
        if isinstance(piece, list):
            piece = piece[0] if piece else None

        if col_piece in df.columns and piece:
            if piece not in df[col_piece].astype(str).unique():
                return {
                    "error": f"Pièce {piece} absente du df_propre",
                    "valid": False,
                }

        if col_op in df.columns and operation:
            if operation not in df[col_op].astype(str).unique():
                return {
                    "error": f"Opération {operation} absente du df_propre",
                    "valid": False,
                }

        variables = intent.get("variables") or []
        colonnes_vides_ignorees: list[str] = []
        if variables:
            missing_required, colonnes_vides_ignorees = _split_missing_variables(
                variables,
                set(df.columns),
                context,
                piece,
                operation,
            )
            if missing_required:
                return {
                    "error": f"Variables absentes après pivot : {missing_required[:5]}",
                    "valid": False,
                }

        if col_tag in df.columns:
            return {
                "error": "Format LONG détecté : pivot incomplet (colonne Tag présente)",
                "valid": False,
            }

        result: dict = {
            "error": None,
            "valid": True,
            "row_count": len(df),
            "column_count": len(df.columns),
        }
        if colonnes_vides_ignorees:
            result["colonnes_vides_ignorees"] = colonnes_vides_ignorees
        return result
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "valid": False}
