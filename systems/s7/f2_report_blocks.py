"""
P7-F2a — construction des 9 blocs rapport métier depuis group_descriptive S3.

Zéro LLM, zéro numpy/pandas, zéro recalcul statistique.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from systems.s7 import f2_pedagogy, f2_templates, prep

_F2_INTENTIONS = frozenset(
    {"comparaison_groupes", "diagnostic_causal", "analyse_complete"}
)

F2_NARRATIF_BLOCKS_BEFORE_CHARTS: tuple[str, ...] = (
    "conclusion_key",
    "business_context",
    "key_indicators",
    "how_to_read_cpk",
    "group_comparison_table",
    "statistical_reliability",
)
F2_NARRATIF_BLOCKS_AFTER_CHARTS: tuple[str, ...] = (
    "business_reading",
    "final_verdict",
    "interpretation_limits",
)

_ANALYSIS_LEVEL_LABELS = {
    "measure": "mesure brute (une ligne par mesure capteur)",
    "aggregated_unit": "unité métier agrégée",
}


@dataclass
class F2DescriptiveSource:
    block: dict[str, Any]
    level: str
    measure_annex: dict[str, Any] | None
    variable: str
    group_by: str
    intent: dict[str, Any]
    selection: dict[str, Any]


@dataclass
class F2ReportBundle:
    variable: str
    source_level: str
    blocks: dict[str, dict[str, Any]]
    provenance: dict[str, list[str]] = field(default_factory=dict)
    skipped_reason: str | None = None


def is_f2_intention_eligible(intent: dict) -> bool:
    intention = str(intent.get("intention") or "").strip()
    if intention not in _F2_INTENTIONS:
        return False
    if intention == "analyse_complete":
        gb = intent.get("group_by")
        if isinstance(gb, list):
            return bool(gb)
        return bool(str(gb or "").strip())
    return True


def extract_group_descriptive_list(s3_output: dict) -> list[dict[str, Any]]:
    raw = s3_output.get("group_descriptive")
    if isinstance(raw, list) and raw:
        return [b for b in raw if isinstance(b, dict)]
    ms = s3_output.get("metrics_summary")
    if isinstance(ms, dict):
        nested = ms.get("group_descriptive")
        if isinstance(nested, list):
            return [b for b in nested if isinstance(b, dict)]
    return []


def select_group_descriptive_blocks(
    blocks: list[dict[str, Any]],
    variable: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """Retourne (primary, measure_annex, selection_meta)."""
    filtered = blocks
    if variable:
        filtered = [b for b in blocks if b.get("variable") == variable]

    agg: dict[str, Any] | None = None
    measure: dict[str, Any] | None = None
    for b in filtered:
        level = str(b.get("level", ""))
        if level == "aggregated_unit":
            ag = b.get("aggregation") or {}
            if ag.get("applied"):
                agg = b
        elif level == "measure":
            measure = b

    primary = agg if agg is not None else measure
    measure_annex = measure if agg is not None and measure is not None else None

    selection = {
        "primary_level": primary.get("level") if primary else None,
        "fallback_used": agg is None and measure is not None,
        "measure_annex_available": measure_annex is not None,
        "variable": (primary or measure or {}).get("variable"),
        "group_by": (primary or measure or {}).get("group_by"),
        "ranking_method": (primary or {}).get("ranking_method"),
        "worse_direction": (primary or {}).get("worse_direction"),
    }
    return primary, measure_annex, selection


def _fmt_num(value: Any, decimals: int = 3) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f} %".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _row_by_rank(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: int(r.get("rank") or 999))


def _worst_row(rows: list[dict]) -> dict | None:
    ordered = _row_by_rank(rows)
    return ordered[0] if ordered else None


def _min_cpk_row(rows: list[dict]) -> tuple[float | None, dict | None, str | None]:
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
            best = (v, row, f"rows[{i}].cpk")
    return best


def _analysis_level_label(block: dict, context: Any) -> str:
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
        return _ANALYSIS_LEVEL_LABELS["aggregated_unit"]
    return _ANALYSIS_LEVEL_LABELS.get(level, level)


def _group_by_label(group_by: str, intent: dict) -> str:
    from systems.s5.prep import friendly_group_label

    return friendly_group_label(group_by, intent)


def _tolerances_from_context(
    context: Any, intent: dict, variable: str
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
            "interval_display": f"[{_fmt_num(lti)} ; {_fmt_num(lts)}]{(' ' + unit) if unit else ''}",
        }
    except (TypeError, ValueError, KeyError):
        return None


def build_f2_bundle(
    s3_output: dict,
    intent: dict,
    context: Any = None,
    *,
    variable: str | None = None,
) -> F2ReportBundle:
    """
    Construit les 9 blocs P7-F2 ou retourne skipped_reason si données absentes.
    """
    prov: dict[str, list[str]] = {}
    blocks_list = extract_group_descriptive_list(s3_output)
    if not blocks_list:
        return F2ReportBundle(
            variable=variable or "",
            source_level="",
            blocks={},
            provenance=prov,
            skipped_reason="no_group_descriptive",
        )

    if variable is None:
        vars_intent = intent.get("variables") or []
        if isinstance(vars_intent, list) and vars_intent:
            variable = str(vars_intent[0])
        elif blocks_list:
            variable = str(blocks_list[0].get("variable", ""))

    primary, measure_annex, selection = select_group_descriptive_blocks(
        blocks_list, variable
    )
    if primary is None:
        return F2ReportBundle(
            variable=variable or "",
            source_level="",
            blocks={},
            provenance=prov,
            skipped_reason="no_group_descriptive",
        )

    source = F2DescriptiveSource(
        block=primary,
        level=str(primary.get("level", "")),
        measure_annex=measure_annex,
        variable=str(primary.get("variable", "")),
        group_by=str(primary.get("group_by", "")),
        intent=intent,
        selection=selection,
    )

    built = _build_all_blocks(source, context, prov)
    return F2ReportBundle(
        variable=source.variable,
        source_level=source.level,
        blocks=built,
        provenance=prov,
        skipped_reason=None,
    )


def _build_all_blocks(
    source: F2DescriptiveSource,
    context: Any,
    prov: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    block = source.block
    rows = list(block.get("rows") or [])
    ordered = _row_by_rank(rows)
    worst = _worst_row(rows)
    best = ordered[-1] if ordered else None
    worst_group = str(block.get("worst_group") or (worst or {}).get("group_value", ""))
    best_group = str(block.get("best_group") or (best or {}).get("group_value", ""))
    group_by_label = _group_by_label(source.group_by, source.intent)
    level_label = _analysis_level_label(block, context)
    worse_dir = str(block.get("worse_direction", "both"))
    tolerances = _tolerances_from_context(context, source.intent, source.variable)

    worst_pct = (worst or {}).get("out_of_tolerance_rate")
    worst_cpk = (worst or {}).get("cpk")
    if worst is not None and worst_pct is not None:
        prov.setdefault("conclusion_key", []).append("rows[rank=1].out_of_tolerance_rate")
    if worst_cpk is not None:
        prov.setdefault("conclusion_key", []).append("rows[rank=1].cpk")

    conclusion = {
        "title": "Conclusion clé",
        "selection": source.selection,
        "worst_group": worst_group,
        "best_group": best_group,
        "facts": _build_facts(worst, worst_group, prov),
        "paragraphs": f2_templates.conclusion_paragraphs(
            variable=source.variable,
            worst_group=worst_group,
            best_group=best_group,
            worst_pct=float(worst_pct) if worst_pct is not None else None,
            worst_cpk=float(worst_cpk) if worst_cpk is not None else None,
            group_by_label=group_by_label,
        ),
        "max_facts": 3,
    }

    agg_meta = dict(block.get("aggregation") or {})
    business_context = {
        "title": "Contexte métier",
        "variable": source.variable,
        "variable_display": source.variable.replace("_", " "),
        "group_by": source.group_by,
        "group_by_display": group_by_label,
        "analysis_level": source.level,
        "analysis_level_label": level_label,
        "aggregation": agg_meta,
        "tolerances": tolerances,
        "hors_tolerance_definition": f2_templates.hors_tolerance_definition(
            source.level
        ),
        "paragraphs": [
            f2_templates.business_context_paragraph(
                variable=source.variable,
                group_by_label=group_by_label,
                analysis_level_label=level_label,
            )
        ],
    }

    min_cpk_val, min_cpk_row, min_cpk_path = _min_cpk_row(rows)
    key_indicators = _build_key_indicators(
        worst_group,
        best_group,
        worst,
        best,
        min_cpk_val,
        min_cpk_row,
        source.level,
        prov,
    )

    comparison_table = _build_group_comparison_table(ordered, block, prov)

    cpk_present = min_cpk_val is not None
    how_cpk = f2_pedagogy.build_how_to_read_cpk(
        context,
        cpk_present=cpk_present,
        worst_group=str((min_cpk_row or worst or {}).get("group_value", worst_group)),
        min_cpk=min_cpk_val,
        min_cpk_source_path=min_cpk_path,
    )

    reliability = _build_statistical_reliability(
        ordered,
        source,
        prov,
    )

    reading = _build_business_reading(ordered, source, worse_dir, prov)

    hierarchy = [str(r.get("group_value", "")) for r in ordered]
    final_verdict = {
        "title": "Verdict et hiérarchie des groupes",
        "group_hierarchy": [
            {
                "rank": r.get("rank"),
                "group_value": r.get("group_value"),
                "severity_label": r.get("severity_label"),
                "severity_display": f2_templates.severity_display(
                    str(r.get("severity_label", ""))
                ),
            }
            for r in ordered
        ],
        "paragraphs": f2_templates.final_verdict_paragraphs(
            hierarchy=hierarchy,
            worst_group=worst_group,
            group_by_label=group_by_label,
        ),
        "action_orientation": "investigation_qualite_groupe_critique",
    }

    limits = {
        "title": "Limites d'interprétation",
        "paragraphs": f2_templates.interpretation_limits_paragraphs(
            base_text=str(block.get("interpretation_limits", "")),
            analysis_level=source.level,
            measure_annex_available=bool(source.measure_annex),
        ),
        "source": "group_descriptive.interpretation_limits",
        "template_id": "f2_association_not_causality_v1",
    }

    return {
        "conclusion_key": conclusion,
        "business_context": business_context,
        "key_indicators": key_indicators,
        "group_comparison_table": comparison_table,
        "how_to_read_cpk": how_cpk,
        "statistical_reliability": reliability,
        "business_reading": reading,
        "final_verdict": final_verdict,
        "interpretation_limits": limits,
    }


def _build_facts(
    worst: dict | None,
    worst_group: str,
    prov: dict[str, list[str]],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if worst is None:
        return facts
    pct = worst.get("out_of_tolerance_rate")
    if pct is not None:
        facts.append(
            {
                "key": "out_of_tolerance_rate",
                "group": worst_group,
                "value": pct,
                "unit": "%",
                "source_path": "rows[rank=1].out_of_tolerance_rate",
            }
        )
        prov.setdefault("key_indicators", []).append(
            "rows[rank=1].out_of_tolerance_rate"
        )
    cpk = worst.get("cpk")
    if cpk is not None:
        facts.append(
            {
                "key": "cpk",
                "group": worst_group,
                "value": cpk,
                "unit": None,
                "source_path": "rows[rank=1].cpk",
            }
        )
    return facts[:3]


def _build_key_indicators(
    worst_group: str,
    best_group: str,
    worst: dict | None,
    best: dict | None,
    min_cpk_val: float | None,
    min_cpk_row: dict | None,
    analysis_level: str,
    prov: dict[str, list[str]],
) -> dict[str, Any]:
    unit = "unités" if analysis_level == "aggregated_unit" else "mesures"
    rows_out: list[dict[str, Any]] = [
        {
            "label": "Groupe le plus critique",
            "value": worst_group,
            "sub": "rang 1 — critique",
        },
    ]
    if worst and worst.get("out_of_tolerance_rate") is not None:
        raw = worst["out_of_tolerance_rate"]
        rows_out.append(
            {
                "label": "Taux hors tolérance (groupe critique)",
                "value": _fmt_pct(raw),
                "raw": raw,
                "source_path": "rows[rank=1].out_of_tolerance_rate",
            }
        )
    if min_cpk_val is not None and min_cpk_row:
        gv = str(min_cpk_row.get("group_value", ""))
        rows_out.append(
            {
                "label": "Cpk le plus faible",
                "value": _fmt_num(min_cpk_val),
                "raw": min_cpk_val,
                "group": gv,
                "source_path": "rows[].cpk (minimum)",
            }
        )
        prov.setdefault("key_indicators", []).append("rows[].cpk")
    rows_out.append(
        {
            "label": "Groupe le plus favorable",
            "value": best_group,
            "sub": f"rang {best.get('rank') if best else '—'} — favorable",
        }
    )
    if worst and worst.get("n") is not None:
        n = worst["n"]
        rows_out.append(
            {
                "label": "Effectif analysé (groupe critique)",
                "value": f"{n} {unit}",
                "raw_n": n,
                "source_path": "rows[rank=1].n",
            }
        )
    return {
        "title": "Indicateurs clés",
        "worst_group": worst_group,
        "best_group": best_group,
        "rows": rows_out,
    }


def _build_group_comparison_table(
    ordered: list[dict],
    block: dict,
    prov: dict[str, list[str]],
) -> dict[str, Any]:
    table_rows: list[dict[str, Any]] = []
    for i, row in enumerate(ordered):
        rank = row.get("rank")
        path_base = f"rows[{i}]"
        prov.setdefault("group_comparison_table", []).append(path_base)
        table_rows.append(
            {
                "group_value": row.get("group_value"),
                "n": row.get("n"),
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
                "rank": rank,
                "severity_label": row.get("severity_label"),
                "severity_display": f2_templates.severity_display(
                    str(row.get("severity_label", ""))
                ),
            }
        )
    foot = (
        "Classement : taux hors tolérance décroissant, puis Cpk croissant, "
        f"puis proximité à la limite critique (direction : {block.get('worse_direction', 'both')})."
    )
    return {
        "title": "Comparaison des groupes",
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
    ordered: list[dict],
    source: F2DescriptiveSource,
    prov: dict[str, list[str]],
) -> dict[str, Any]:
    groups_out: list[dict[str, Any]] = []
    global_warnings: list[Any] = list(source.block.get("warnings") or [])
    if source.measure_annex:
        global_warnings.append(
            {
                "code": "measure_annex_available",
                "message": "Détail niveau mesure disponible en annexe S3.",
            }
        )

    measure_note = ""
    if source.selection.get("measure_annex_available"):
        measure_note = (
            "Un détail au niveau mesure brute est disponible en annexe "
            "(effectifs capteur)."
        )
    if source.selection.get("fallback_used"):
        global_warnings.append(
            {
                "code": "analysis_level_measure_fallback",
                "message": "Analyse principale au niveau mesure (agrégation non appliquée).",
            }
        )

    for row in ordered:
        groups_out.append(
            {
                "group_value": row.get("group_value"),
                "ci95_mean": row.get("ci95_mean"),
                "ci95_out_of_tolerance_rate": row.get("ci95_out_of_tolerance_rate"),
                "warnings": list(row.get("warnings") or []),
            }
        )

    return {
        "title": "Fiabilité statistique",
        "analysis_level": source.level,
        "measure_annex_note": measure_note,
        "groups": groups_out,
        "global_warnings": global_warnings,
        "limits_paragraph": f2_templates.reliability_limits_paragraph(source.level),
    }


def _build_business_reading(
    ordered: list[dict],
    source: F2DescriptiveSource,
    worse_direction: str,
    prov: dict[str, list[str]],
) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for row in ordered:
        sev = str(row.get("severity_label", "")).lower()
        gv = str(row.get("group_value", ""))
        rank = row.get("rank")
        if sev == "critique":
            sections.append(
                {
                    "tier": "critique",
                    "heading": f"Priorité principale — {gv}",
                    "paragraphs": [
                        f2_templates.business_reading_paragraph_critique(
                            group_value=gv,
                            pct=row.get("out_of_tolerance_rate"),
                            cpk=row.get("cpk"),
                            worse_direction=worse_direction,
                        )
                    ],
                    "source_row_rank": rank,
                }
            )
        elif sev == "favorable":
            sections.append(
                {
                    "tier": "favorable",
                    "heading": f"Référence favorable — {gv}",
                    "paragraphs": [
                        f2_templates.business_reading_paragraph_favorable(
                            group_value=gv,
                            pct=row.get("out_of_tolerance_rate"),
                            n=row.get("n"),
                            analysis_level=source.level,
                        )
                    ],
                    "source_row_rank": rank,
                }
            )
        else:
            sections.append(
                {
                    "tier": "surveillance",
                    "heading": f"Groupe à surveiller — {gv}",
                    "paragraphs": [
                        f2_templates.business_reading_paragraph_surveillance(gv, rank)
                    ],
                    "source_row_rank": rank,
                }
            )
    prov.setdefault("business_reading", []).append("rows[].severity_label")
    return {"title": "Lecture métier", "sections": sections}


def resolve_f2_narratif_plan(
    render_mode_requested: str,
    intent: dict,
    s3_output: dict,
    context: Any,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """
    Décide si le rapport utilise le narratif F2 ou retombe en audit.

    f2_narratif_skipped n'est renseigné que si narratif_metier était demandé.
    """
    if render_mode_requested != "narratif_metier":
        return {"use_f2": False, "skipped_reason": None, "bundle": None}

    if not prep.is_f2_narratif_enabled(cfg or {}):
        return {
            "use_f2": False,
            "skipped_reason": "f2_narratif_disabled",
            "bundle": None,
        }

    if not is_f2_intention_eligible(intent):
        return {
            "use_f2": False,
            "skipped_reason": "intention_not_eligible",
            "bundle": None,
        }

    bundle = build_f2_bundle(s3_output, intent, context)
    if bundle.skipped_reason:
        return {
            "use_f2": False,
            "skipped_reason": bundle.skipped_reason,
            "bundle": None,
        }
    return {"use_f2": True, "skipped_reason": None, "bundle": bundle}


def assemble_narratif_document_blocks(
    bundle: F2ReportBundle,
    *,
    meta: dict[str, Any],
    verdict_data: dict[str, Any],
    chart_items: list[dict[str, Any]],
    reco_rows: list[dict[str, Any]],
    trace_block: Any,
    dunn_annexe: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """Assemble les ReportBlock pour le mode narratif_metier F2."""
    from systems.s7.document import ReportBlock

    blocks: list[Any] = [
        ReportBlock("cover", {"meta": meta}),
        ReportBlock("verdict", verdict_data),
    ]
    for key in F2_NARRATIF_BLOCKS_BEFORE_CHARTS:
        blocks.append(ReportBlock(key, dict(bundle.blocks[key])))
    blocks.append(
        ReportBlock(
            "charts",
            {"items": chart_items, "section_title": "GRAPHIQUES"},
        )
    )
    for key in F2_NARRATIF_BLOCKS_AFTER_CHARTS:
        blocks.append(ReportBlock(key, dict(bundle.blocks[key])))
    blocks.append(ReportBlock("recommendations", {"items": reco_rows}))
    if dunn_annexe:
        blocks.append(ReportBlock("annexe_dunn", {"items": dunn_annexe}))
    blocks.append(trace_block)
    return blocks


def collect_all_numeric_values(block: dict) -> set[float]:
    """Extrait les nombres du bloc S3 pour tests de provenance."""
    out: set[float] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            out.add(float(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(block.get("rows"))
    return out
