"""
A1 — Assembleur S7 : ReportDocument pré-formaté (Python pur).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.s7 import prep
from systems.s7.document import ReportBlock, ReportDocument

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def run(
    question_originale: str,
    intent: dict,
    s3_output: dict,
    s4_output: dict,
    s5_output: dict,
    s6_output: dict,
    context: "ClientContext",
    profile: str,
    *,
    timestamp: str | None = None,
) -> dict:
    try:
        cfg = prep.rapport_pdf_config(context)
        ts = timestamp or prep.utc_timestamp()
        prof_cfg = context.profils.get(profile, {}) if isinstance(context.profils, dict) else {}
        forbidden = list(prof_cfg.get("forbidden_words", [])) if isinstance(prof_cfg, dict) else []

        recommandations = list(s6_output.get("recommandations") or [])
        prio = prep.priorite_max(recommandations)
        verdict_lbl = prep.verdict_label(prio, cfg)

        synthese_s5 = prep.apply_profile_text(
            prep.sanitize_text(str(s5_output.get("synthese", "") or "")),
            profile,
            forbidden,
        )
        synthese_s6 = prep.apply_profile_text(
            prep.sanitize_text(str(s6_output.get("synthese_action", "") or "")),
            profile,
            forbidden,
        )

        specialist_results = list(s3_output.get("specialist_results") or [])
        metric_tables = prep.build_metric_tables(
            s4_output, specialist_results, profile, forbidden
        )

        graphs_raw = list(s4_output.get("graphs", s4_output.get("charts", [])) or [])
        max_g = prep.max_graphiques(profile, cfg)
        chart_items: list[dict] = []
        for g in graphs_raw[:max_g]:
            if not isinstance(g, dict):
                continue
            png = g.get("png_bytes")
            if png is None and g.get("error"):
                continue
            chart_items.append(
                {
                    "title": prep.sanitize_text(str(g.get("title", g.get("type", "Graphique")))),
                    "caption": prep.apply_profile_text(
                        prep.sanitize_text(str(g.get("description", ""))),
                        profile,
                        forbidden,
                    ),
                    "png_bytes": png if isinstance(png, (bytes, bytearray)) else None,
                    "error": g.get("error"),
                }
            )

        interp_items: list[dict] = []
        seen_interp: set[tuple[str, str]] = set()
        for it in s5_output.get("interpretations") or []:
            if not isinstance(it, dict) or prep.is_graph_only_interpretation(it):
                continue
            text = prep.prepare_interpretation_text(
                it, specialist_results, profile, forbidden
            )
            if not prep.is_meaningful_text(text):
                continue
            spec = prep.sanitize_text(str(it.get("specialist", "analyse")))
            key = (spec.lower(), text[:120])
            if key in seen_interp:
                continue
            seen_interp.add(key)
            statut = str(it.get("statut", "accept"))
            interp_items.append(
                {
                    "specialist": spec,
                    "text": text,
                    "statut": statut,
                    "badge": prep.interpretation_badge(statut),
                }
            )

        reco_rows: list[dict] = []
        for rec in sorted(
            recommandations,
            key=lambda r: prep.priority_rank(str(r.get("priorite", "P4"))),
        ):
            reco_rows.append(
                {
                    "priorite": str(rec.get("priorite", "P4")).upper(),
                    "action": prep.apply_profile_text(
                        prep.sanitize_text(str(rec.get("action", ""))),
                        profile,
                        forbidden,
                    ),
                    "responsable": prep.sanitize_text(str(rec.get("responsable", ""))),
                    "delai": prep.sanitize_text(str(rec.get("delai", ""))),
                    "justification": prep.apply_profile_text(
                        prep.sanitize_text(str(rec.get("justification", ""))),
                        profile,
                        forbidden,
                    ),
                }
            )

        warning_count = len(s5_output.get("warnings") or []) + len(s6_output.get("warnings") or [])

        meta = {
            "timestamp": ts,
            "profile": profile,
            "question": question_originale,
            "client": prep.client_display_name(context),
            "piece": str(intent.get("piece") or ""),
            "operation": str(intent.get("operation") or ""),
            "verdict": verdict_lbl,
            "verdict_key": prep.verdict_key(prio),
            "priorite_max": prio,
            "fidelite_score": float(s5_output.get("fidelite_score", 0.0) or 0.0),
            "industria_version": str(cfg.get("industria_version", "v4.0")),
            "nb_recommandations": len(reco_rows),
            "nb_graphiques": len(chart_items),
            "warning_count": warning_count,
            "specialists_executed": [
                str(r.get("agent", ""))
                for r in specialist_results
                if r.get("status") == "success"
            ],
        }

        blocks: list[ReportBlock] = [
            ReportBlock("cover", {"meta": meta}),
            ReportBlock("verdict", {"label": verdict_lbl, "priorite_max": prio}),
            ReportBlock(
                "executive",
                {
                    "paragraphs": [p for p in (synthese_s5, synthese_s6) if p],
                    "synthese_s5": synthese_s5,
                    "synthese_s6": synthese_s6,
                },
            ),
            ReportBlock("recommendations", {"items": reco_rows}),
            ReportBlock("charts", {"items": chart_items}),
            ReportBlock("metrics_table", {"tables": metric_tables}),
            ReportBlock("interpretations", {"items": interp_items}),
            ReportBlock(
                "traceability",
                {
                    "sha256": "",
                    "timestamp": ts,
                    "fidelite_score": meta["fidelite_score"],
                    "industria_version": meta["industria_version"],
                    "warning_count": warning_count,
                },
            ),
            ReportBlock(
                "annexe_warnings",
                {"count": warning_count, "specialists": meta["specialists_executed"]},
            ),
        ]

        document = ReportDocument(meta=meta, blocks=blocks)
        return {"document": document, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"document": None, "error": str(exc)}
