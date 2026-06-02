"""
P7-F2 compact — libellés métier depuis YAML / intent (zéro paraphrase inventée).
"""

from __future__ import annotations

from typing import Any

from systems.s7.f2_compact_selection import _find_factor_config


def resolve_variable_label(
    context: Any,
    intent: dict,
    variable: str,
) -> str:
    """Libellé tag depuis YAML ; à défaut le tag technique."""
    if not variable:
        return ""
    if context is not None and intent:
        piece = intent.get("piece")
        operation = intent.get("operation")
        if piece and operation:
            tol = context.get_tolerance(str(piece), str(operation), variable)
            if isinstance(tol, dict):
                for key in ("libelle_court", "libelle", "label", "nom", "description"):
                    val = tol.get(key)
                    if val:
                        return str(val)
    if context is not None:
        groups = getattr(context, "entites_variables", {}) or {}
        if isinstance(groups, dict):
            op_keys = [str(intent.get("operation") or "")] if intent.get("operation") else list(groups.keys())
            for op_key in op_keys:
                op_groups = groups.get(op_key, {}) if op_key else {}
                if not isinstance(op_groups, dict):
                    continue
                for group_cfg in op_groups.values():
                    if not isinstance(group_cfg, dict):
                        continue
                    pattern = str(group_cfg.get("pattern_tag") or "")
                    if pattern and _tag_matches_pattern(variable, pattern):
                        for key in ("libelle_court", "libelle", "label", "description"):
                            val = group_cfg.get(key)
                            if val:
                                return str(val)
    return variable


def resolve_factor_label(
    context: Any,
    intent: dict,
    group_by: str,
) -> str:
    """Libellé facteur depuis entites.facteurs_analyse ou friendly_group_label."""
    factor_cfg = _find_factor_config(context, group_by)
    if factor_cfg:
        for key in ("libelle_court", "libelle", "label", "description"):
            val = factor_cfg.get(key)
            if val:
                return str(val)
    from systems.s5.prep import friendly_group_label

    return friendly_group_label(group_by, intent)


def synthesis_title(variable_label: str, factor_label: str) -> str:
    return (
        f"Synthèse métier — Comparaison de {variable_label} selon {factor_label}"
    )


def tolerances_for_variable(
    context: Any,
    intent: dict,
    variable: str,
) -> dict[str, Any] | None:
    if context is None:
        return None
    piece = intent.get("piece")
    operation = intent.get("operation")
    if not piece or not operation:
        return None
    tol = context.get_tolerance(str(piece), str(operation), variable)
    if not tol:
        return None
    try:
        lti = float(tol["lti"])
        lts = float(tol["lts"])
        nominal = tol.get("nominal")
        unit = str(tol.get("unite", ""))
        return {
            "lti": lti,
            "lts": lts,
            "nominal": float(nominal) if nominal is not None else None,
            "unit": unit,
            "interval_display": (
                f"[{_fmt_num(lti)} ; {_fmt_num(lts)}]"
                f"{(' ' + unit) if unit else ''}"
            ),
        }
    except (TypeError, ValueError, KeyError):
        return None


def analysis_level_label(block: dict, context: Any) -> str:
    level = str(block.get("level", "measure"))
    agg = block.get("aggregation") or {}
    if level == "aggregated_unit" and agg.get("applied"):
        unit_id = agg.get("unit_id")
        if context and unit_id:
            raw = context.get_agregation_metier_f2_raw()
            unites = raw.get("unites") or {}
            unit_cfg = unites.get(unit_id) if isinstance(unites, dict) else {}
            if isinstance(unit_cfg, dict) and unit_cfg.get("label"):
                return str(unit_cfg["label"])
        return "unité métier agrégée"
    labels = {
        "measure": "mesure brute (une ligne par mesure capteur)",
    }
    return labels.get(level, level)


def _tag_matches_pattern(tag: str, pattern: str) -> bool:
    import fnmatch

    if "[" in pattern or "*" in pattern or "?" in pattern:
        regex = pattern.replace(".", r"\.").replace("*", ".*")
        import re

        return bool(re.search(regex, tag))
    return fnmatch.fnmatch(tag, pattern)


def _fmt_num(value: Any, decimals: int = 3) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "—"
