"""
P7-F2 compact — C2 construction des blocs JSON (sans assembler, sans PDF).

Zéro LLM, zéro S3 write, zéro renderer.
"""

from __future__ import annotations

from typing import Any

from systems.s7 import f2_pedagogy, f2_templates, prep
from systems.s7.document import ReportBlock, ReportDocument
from systems.s7.f2_compact_display import (
    ci95_display,
    compact_level_display,
    compact_report_title,
    exclusion_detail_client,
    favorable_indicator_label,
    format_effectif_display,
    priority_entity_label,
    _fmt_num,
    _fmt_pct,
)
from systems.s7.f2_compact_labels import (
    analysis_level_label,
    resolve_factor_label,
    resolve_variable_label,
    synthesis_title,
    tolerances_for_variable,
)
from systems.s7.f2_compact_charts import build_compact_chart_items
from systems.s7.f2_compact_selection import (
    F2CompactSelection,
    build_f2_compact_selection,
)
from systems.s7.f2_high_cardinality import (
    apply_high_cardinality_projection,
    exploratory_disclaimer_paragraph,
)
from systems.s7.f2_compact_templates import (
    business_reading_sections_compact,
    business_synthesis_lines,
    conclusion_key_paragraphs,
    exclusion_reason_label,
    final_verdict_paragraphs_compact,
    interpretation_limits_paragraphs_compact,
    statistical_test_paragraphs,
    verdict_bullets_compact,
)
from systems.s7.f2_compact_verdict import compute_compact_verdict
from systems.s7.f2_report_blocks import (
    extract_group_descriptive_list,
    select_group_descriptive_blocks,
)

F2_COMPACT_BLOCK_ORDER: tuple[str, ...] = (
    "cover",
    "business_synthesis",
    "conclusion_key",
    "verdict",
    "business_context",
    "key_indicators",
    "group_comparison_table",
    "how_to_read_cpk",
    "statistical_reliability",
    "charts",
    "statistical_test",
    "business_reading",
    "final_verdict",
    "excluded_groups",
    "interpretation_limits",
    "traceability",
)


def build_f2_compact_document(
    s3_output: dict,
    intent: dict,
    *,
    context: Any = None,
    cfg: dict | None = None,
    question_originale: str = "",
    chart_items: list[dict[str, Any]] | None = None,
    specialist_results: list[dict[str, Any]] | None = None,
    timestamp: str = "",
    profile: str = "technicien",
    meta_extra: dict[str, Any] | None = None,
    df_propre: Any = None,
) -> ReportDocument:
    """
    Assemble un ReportDocument F2 compact inspectable (C2/C3).
    """
    cfg = cfg or {}
    if context is not None and not cfg:
        cfg = prep.rapport_pdf_config(context)

    selection = build_f2_compact_selection(s3_output, intent, context, cfg)
    primary_block = _primary_block(s3_output, selection)
    apply_high_cardinality_projection(
        selection,
        cfg,
        df_propre=df_propre,
        context=context,
        intent=intent,
        primary_block=primary_block,
    )
    interpretation_limits = str(
        (primary_block or {}).get("interpretation_limits") or ""
    )
    worse_direction = str(
        (primary_block or {}).get("worse_direction") or "both"
    )

    variable_label = resolve_variable_label(context, intent, selection.variable)
    factor_label = resolve_factor_label(context, intent, selection.group_by)
    tolerances = tolerances_for_variable(context, intent, selection.variable)
    level_label = analysis_level_label(
        primary_block or {"level": selection.level}, context
    )
    title = synthesis_title(variable_label, factor_label)
    report_title = compact_report_title(variable_label, factor_label)

    verdict = compute_compact_verdict(selection, context, cfg)
    chart_items = build_compact_chart_items(
        list(chart_items or []),
        selection,
        intent,
        context,
        df_propre=df_propre,
        factor_label=factor_label,
    )
    for item in chart_items:
        if isinstance(item, dict) and factor_label and selection.variable:
            item["title"] = (
                f"Comparaison par {factor_label} — {selection.variable}"
            )
    ts = timestamp or prep.utc_timestamp()
    question = question_originale or str(intent.get("question") or "")

    meta: dict[str, Any] = {
        "timestamp": ts,
        "profile": profile,
        "question": question,
        "report_title": report_title,
        "question_technique": question,
        "reference": prep.report_reference(ts, cfg),
        "verdict": verdict.label,
        "verdict_key": verdict.verdict_key,
        "render_mode": "f2_compact",
        "f2_variable": selection.variable,
        "f2_source_level": selection.level,
        "f2_compact_selection": selection.selection_meta,
        "client": prep.client_display_name(context) if context else "",
        "piece": str(intent.get("piece") or ""),
        "operation": str(intent.get("operation") or ""),
        "industria_version": str(cfg.get("industria_version", "v4.0")),
    }
    if meta_extra:
        meta.update(meta_extra)

    block_map = _build_block_map(
        selection=selection,
        intent=intent,
        context=context,
        cfg=cfg,
        meta=meta,
        title=title,
        variable_label=variable_label,
        factor_label=factor_label,
        tolerances=tolerances,
        level_label=level_label,
        verdict=verdict,
        worse_direction=worse_direction,
        interpretation_limits=interpretation_limits,
        chart_items=chart_items or [],
        specialist_results=specialist_results or [],
        primary_block=primary_block,
    )

    blocks = [
        ReportBlock(key, block_map[key])
        for key in F2_COMPACT_BLOCK_ORDER
        if key in block_map
    ]
    return ReportDocument(meta=meta, blocks=blocks)


def resolve_f2_compact_plan(
    s3_output: dict,
    intent: dict,
    context: Any = None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """
    Décide si le rapport utilise F2 compact (flag explicite uniquement).

    intent.rapport_mode, f2_narratif_enabled et group_descriptive seuls ne suffisent pas.
    """
    cfg = cfg or {}
    if not prep.is_f2_compact_enabled(cfg):
        return {"use_compact": False, "skipped_reason": None}

    from systems.s7.f2_report_blocks import is_f2_intention_eligible

    if not is_f2_intention_eligible(intent):
        return {"use_compact": False, "skipped_reason": "intention_not_eligible"}

    if not extract_group_descriptive_list(s3_output):
        return {"use_compact": False, "skipped_reason": "no_group_descriptive"}

    selection = build_f2_compact_selection(s3_output, intent, context, cfg)
    if selection.skipped_reason:
        return {
            "use_compact": False,
            "skipped_reason": selection.skipped_reason,
        }

    return {"use_compact": True, "skipped_reason": None, "selection": selection}


def f2_compact_document_to_dict(doc: ReportDocument) -> dict[str, Any]:
    """Export JSON inspectable pour tests et revue C2."""
    return {
        "meta": doc.meta,
        "block_types": doc.block_types(),
        "blocks": [
            {"block_type": b.block_type, "data": b.data} for b in doc.blocks
        ],
    }


def _primary_block(
    s3_output: dict, selection: F2CompactSelection
) -> dict[str, Any] | None:
    blocks_list = extract_group_descriptive_list(s3_output)
    if not blocks_list:
        return None
    primary, _, _ = select_group_descriptive_blocks(blocks_list, selection.variable)
    return primary


def _build_block_map(
    *,
    selection: F2CompactSelection,
    intent: dict,
    context: Any,
    cfg: dict,
    meta: dict[str, Any],
    title: str,
    variable_label: str,
    factor_label: str,
    tolerances: dict[str, Any] | None,
    level_label: str,
    verdict: Any,
    worse_direction: str,
    interpretation_limits: str,
    chart_items: list[dict[str, Any]],
    specialist_results: list[dict[str, Any]],
    primary_block: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    rows = list(selection.rows_for_display)
    worst = selection.worst_reliable
    best = selection.best_reliable
    worst_group = str((worst or {}).get("group_value", ""))
    best_group = str((best or {}).get("group_value", "")) if best else None
    degenerate = selection.degenerate or bool(selection.skipped_reason)
    favorable_strength = str(selection.favorable_strength or "none")
    has_distinct_favorable = bool(
        favorable_strength in ("robust", "limited")
        and best_group
        and worst_group
        and best_group != worst_group
    )

    worst_pct = _float_or_none((worst or {}).get("out_of_tolerance_rate"))
    worst_cpk = _float_or_none((worst or {}).get("cpk"))
    min_cpk_val, min_cpk_row, min_cpk_path = _min_cpk_row(rows)

    compact_cfg = prep.f2_compact_config(cfg)
    max_rows = int(compact_cfg.get("max_table_rows") or 6)
    table_rows = rows if selection.high_cardinality_active else rows[:max_rows]

    cover = {"meta": meta}
    synthesis = business_synthesis_lines(
        title=title,
        variable_tag=selection.variable,
        variable_label=variable_label,
        tolerances=tolerances,
        factor_label=factor_label,
        analysis_level_label=level_label,
        analysis_level=selection.level,
    )
    hc_note = exploratory_disclaimer_paragraph(selection, factor_label=factor_label)
    if hc_note:
        synthesis = dict(synthesis)
        lines = list(synthesis.get("lines") or [])
        lines.append(hc_note)
        synthesis["lines"] = lines
        synthesis["high_cardinality_note"] = hc_note

    conclusion = {
        "title": "Conclusion clé",
        "worst_group": worst_group or None,
        "best_group": best_group if has_distinct_favorable else None,
        "paragraphs": conclusion_key_paragraphs(
            variable_label=variable_label,
            worst_group=worst_group,
            best_group=best_group,
            worst_pct=worst_pct,
            worst_cpk=worst_cpk,
            factor_label=factor_label,
            degenerate=degenerate,
            has_distinct_favorable=has_distinct_favorable,
            favorable_strength=favorable_strength,
            favorable_row=best if has_distinct_favorable else None,
        ),
        "reliable_count": len(selection.rows_reliable),
        "displayed_count": len(rows),
        "excluded_count": len(selection.rows_excluded),
        "high_cardinality_active": selection.high_cardinality_active,
    }

    verdict_block = {
        "label": verdict.label,
        "verdict_key": verdict.verdict_key,
        "banner": verdict.banner,
        "bullets": verdict_bullets_compact(
            verdict=verdict,
            worst_group=worst_group or None,
            worst_pct=worst_pct,
            worst_cpk=worst_cpk,
        ),
        "tone": verdict.tone,
        "rationale": verdict.rationale,
    }

    business_context = {
        "title": "Contexte de l'analyse",
        "variable": selection.variable,
        "variable_label": variable_label,
        "group_by": selection.group_by,
        "group_by_label": factor_label,
        "analysis_level": selection.level,
        "analysis_level_label": level_label,
        "aggregation": dict(selection.aggregation_meta),
        "tolerances": tolerances,
        "hors_tolerance_definition": f2_templates.hors_tolerance_definition(
            selection.level
        ),
        "paragraphs": [
            f2_templates.business_context_paragraph(
                variable=variable_label,
                group_by_label=factor_label,
                analysis_level_label=level_label,
            )
        ],
    }

    key_indicators = _build_key_indicators(
        worst_group,
        best_group if has_distinct_favorable else None,
        worst,
        best if has_distinct_favorable else None,
        min_cpk_val,
        min_cpk_row,
        selection.level,
        factor_label=factor_label,
        favorable_strength=favorable_strength if has_distinct_favorable else "none",
    )

    comparison_table = _build_group_comparison_table(
        table_rows,
        worse_direction,
        factor_label,
        verdict_key=verdict.verdict_key,
    )

    how_cpk = f2_pedagogy.build_how_to_read_cpk(
        context,
        cpk_present=min_cpk_val is not None,
        worst_group=str(
            (min_cpk_row or worst or {}).get("group_value", worst_group)
        ),
        min_cpk=min_cpk_val,
        min_cpk_source_path=min_cpk_path,
    )

    reliability = _build_statistical_reliability(rows, selection, level_label)

    charts = {
        "items": chart_items,
        "section_title": "Graphiques",
    }

    global_test = _extract_global_test(specialist_results)
    statistical_test = {
        "title": "Test statistique global",
        "test_available": global_test is not None,
        "test": global_test,
        "paragraphs": statistical_test_paragraphs(
            global_test,
            factor_label=factor_label,
            variable_label=variable_label,
        ),
    }

    reading = {
        "title": "Lecture métier",
        "sections": business_reading_sections_compact(
            rows,
            worst_row=worst,
            favorable_row=best if has_distinct_favorable else None,
            favorable_strength=favorable_strength,
            worse_direction=worse_direction,
            analysis_level=selection.level,
            factor_label=factor_label,
        ),
    }

    hierarchy = [str(r.get("group_value", "")) for r in rows[:5]]
    final_verdict = {
        "title": "Verdict métier",
        "group_hierarchy": [
            {
                "rank": r.get("rank"),
                "group_value": r.get("group_value"),
                "severity_label": r.get("severity_label"),
                "severity_display": compact_level_display(
                    str(r.get("severity_label", "")),
                    verdict_key=verdict.verdict_key,
                ),
            }
            for r in rows[:5]
        ],
        "paragraphs": final_verdict_paragraphs_compact(
            hierarchy=hierarchy,
            worst_group=worst_group,
            factor_label=factor_label,
            verdict_label=verdict.label,
        ),
    }

    total_detected = selection.selection_meta.get("total_rows") or (
        len(rows) + len(selection.rows_excluded)
    )
    excluded = {
        "title": "Groupes non exploités",
        "summary": (
            f"{len(selection.rows_excluded)} groupes non exploités "
            f"sur {total_detected} groupes détectés"
        ),
        "rows": [
            {
                "group_value": e.group_value,
                "n": e.n,
                "exclusion_reason": e.exclusion_reason,
                "reason_label": exclusion_reason_label(e.exclusion_reason),
                "detail": exclusion_detail_client(e.exclusion_reason, e.detail),
            }
            for e in selection.rows_excluded
        ],
    }

    limits_paragraphs = interpretation_limits_paragraphs_compact(
        base_text=interpretation_limits,
        analysis_level=selection.level,
        factor_label=factor_label,
        variable_label=variable_label,
    )
    if hc_note and hc_note not in limits_paragraphs:
        limits_paragraphs = list(limits_paragraphs) + [hc_note]
    limits = {
        "title": "Limites d'interprétation",
        "paragraphs": limits_paragraphs,
        "source": "group_descriptive.interpretation_limits",
        "high_cardinality_active": selection.high_cardinality_active,
    }

    traceability = {
        "sha256": "",
        "timestamp": meta.get("timestamp"),
        "reference": meta.get("reference"),
        "render_mode": "f2_compact",
        "f2_variable": selection.variable,
        "f2_source_level": selection.level,
        "reliable_count": len(selection.rows_reliable),
        "displayed_count": len(rows),
        "high_cardinality_active": selection.high_cardinality_active,
        "excluded_count": len(selection.rows_excluded),
        "thresholds_used": selection.thresholds_used,
        "high_cardinality": selection.high_cardinality,
        "industria_version": meta.get("industria_version"),
        "client_mode": bool(meta.get("client_mode")),
        "fidelite_score": meta.get("fidelite_score", 0.0),
    }

    return {
        "cover": cover,
        "business_synthesis": synthesis,
        "conclusion_key": conclusion,
        "verdict": verdict_block,
        "business_context": business_context,
        "key_indicators": key_indicators,
        "group_comparison_table": comparison_table,
        "how_to_read_cpk": how_cpk,
        "statistical_reliability": reliability,
        "charts": charts,
        "statistical_test": statistical_test,
        "business_reading": reading,
        "final_verdict": final_verdict,
        "excluded_groups": excluded,
        "interpretation_limits": limits,
        "traceability": traceability,
    }


def _build_key_indicators(
    worst_group: str,
    best_group: str | None,
    worst: dict | None,
    best: dict | None,
    min_cpk_val: float | None,
    min_cpk_row: dict | None,
    analysis_level: str,
    *,
    factor_label: str = "",
    favorable_strength: str = "none",
) -> dict[str, Any]:
    unit = "unités" if analysis_level == "aggregated_unit" else "mesures"
    prio_label = priority_entity_label(factor_label)
    rows_out: list[dict[str, Any]] = [
        {
            "label": prio_label,
            "value": worst_group or "—",
            "sub": "rang 1 — prioritaire",
        },
    ]
    if worst and worst.get("out_of_tolerance_rate") is not None:
        raw = worst["out_of_tolerance_rate"]
        rows_out.append(
            {
                "label": "Taux hors tolérance (groupe prioritaire)",
                "value": _fmt_pct(raw),
                "raw": raw,
            }
        )
    if min_cpk_val is not None and min_cpk_row:
        rows_out.append(
            {
                "label": "Cpk le plus faible",
                "value": _fmt_num(min_cpk_val),
                "raw": min_cpk_val,
                "group": str(min_cpk_row.get("group_value", "")),
            }
        )
    if best_group:
        fav_label = favorable_indicator_label(favorable_strength)
        fav_sub = (
            "à confirmer"
            if str(favorable_strength).lower() == "limited"
            else f"rang {best.get('rank') if best else '—'} — favorable"
        )
        rows_out.append(
            {
                "label": fav_label,
                "value": best_group,
                "sub": fav_sub,
            }
        )
    if worst and worst.get("n") is not None:
        n = worst["n"]
        rows_out.append(
            {
                "label": "Effectif analysé (groupe prioritaire)",
                "value": f"{n} {unit}",
                "raw_n": n,
            }
        )
    return {
        "title": "Indicateurs clés",
        "worst_group": worst_group or None,
        "best_group": best_group,
        "rows": rows_out,
    }


def _build_group_comparison_table(
    rows: list[dict[str, Any]],
    worse_direction: str,
    factor_label: str,
    *,
    verdict_key: str,
) -> dict[str, Any]:
    table_rows: list[dict[str, Any]] = []
    for row in rows:
        table_rows.append(
            {
                "group_value": row.get("group_value"),
                "n": row.get("n"),
                "n_display": format_effectif_display(row.get("n")),
                "mean": row.get("mean"),
                "mean_display": _fmt_num(row.get("mean")),
                "std": row.get("std"),
                "std_display": _fmt_num(row.get("std")),
                "out_of_tolerance_rate": row.get("out_of_tolerance_rate"),
                "out_of_tolerance_rate_display": _fmt_pct(
                    row.get("out_of_tolerance_rate")
                ),
                "cp": row.get("cp"),
                "cp_display": _fmt_num(row.get("cp")),
                "cpk": row.get("cpk"),
                "cpk_display": _fmt_num(row.get("cpk")),
                "rank": row.get("rank"),
                "severity_label": row.get("severity_label"),
                "severity_display": compact_level_display(
                    str(row.get("severity_label", "")),
                    verdict_key=verdict_key,
                ),
            }
        )
    foot = (
        "Classement : taux hors tolérance décroissant, puis Cpk croissant, "
        f"puis proximité aux limites hors tolérance (direction : {worse_direction})."
    )
    return {
        "title": f"Comparaison des groupes — {factor_label}",
        "columns": [
            "Groupe",
            "n",
            "Moyenne",
            "Écart-type",
            "% hors tol.",
            "Cp",
            "Cpk",
            "Rang",
            "Niveau",
        ],
        "rows": table_rows,
        "footnote": foot,
    }


def _build_statistical_reliability(
    rows: list[dict[str, Any]],
    selection: F2CompactSelection,
    level_label: str,
) -> dict[str, Any]:
    table_rows: list[dict[str, Any]] = []
    for row in rows:
        table_rows.append(
            {
                "Groupe": row.get("group_value"),
                "n": format_effectif_display(row.get("n")),
                "Moyenne": _fmt_num(row.get("mean")),
                "IC95 moyenne": ci95_display(row.get("ci95_mean")),
                "% hors tolérance": _fmt_pct(row.get("out_of_tolerance_rate")),
                "IC95 % hors tolérance": ci95_display(
                    row.get("ci95_out_of_tolerance_rate"),
                    as_percent=True,
                ),
                "Cpk": _fmt_num(row.get("cpk")),
                "Statut fiabilité": _reliability_status(row),
            }
        )
    return {
        "title": "Fiabilité statistique",
        "analysis_level": selection.level,
        "analysis_level_label": level_label,
        "columns": [
            "Groupe",
            "n",
            "Moyenne",
            "IC95 moyenne",
            "% hors tolérance",
            "IC95 % hors tolérance",
            "Cpk",
            "Statut fiabilité",
        ],
        "rows": table_rows,
        "limits_paragraph": f2_templates.reliability_limits_paragraph(selection.level),
    }


def _reliability_status(row: dict[str, Any]) -> str:
    warnings = row.get("warnings") or []
    if warnings:
        return "Avertissement S3"
    return "Fiable"


def _extract_global_test(
    specialist_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for row in specialist_results:
        if str(row.get("status", "")).lower() != "success":
            continue
        agent = str(row.get("agent") or "")
        if agent not in ("anova_kruskal",):
            continue
        result = row.get("result")
        if not isinstance(result, dict):
            continue
        p_value = result.get("p_value")
        if p_value is None:
            continue
        return {
            "agent": agent,
            "methode_choisie": result.get("methode_choisie"),
            "test_name": result.get("test_stat_name"),
            "p_value": p_value,
            "p_value_display": result.get("p_value_display"),
            "significatif": bool(result.get("significatif")),
        }
    return None


def _min_cpk_row(
    rows: list[dict[str, Any]],
) -> tuple[float | None, dict | None, str | None]:
    best: tuple[float | None, dict | None, str | None] = (None, None, None)
    for i, row in enumerate(rows):
        cpk = row.get("cpk")
        if cpk is None:
            continue
        try:
            v = float(cpk)
        except (TypeError, ValueError):
            continue
        if best[0] is None or v < best[0]:
            best = (v, row, f"rows_reliable[{i}].cpk")
    return best


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


