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
        client_mode = prep.is_client_mode(cfg)
        ts = timestamp or prep.utc_timestamp()
        prof_cfg = context.profils.get(profile, {}) if isinstance(context.profils, dict) else {}
        forbidden = list(prof_cfg.get("forbidden_words", [])) if isinstance(prof_cfg, dict) else []

        specialist_results = list(s3_output.get("specialist_results") or [])
        min_cpk_val = prep.min_cpk(specialist_results)

        recommandations = list(s6_output.get("recommandations") or [])
        if client_mode:
            recommandations = prep.cap_recommendations(
                recommandations,
                int(cfg.get("max_recommandations_client", 4)),
            )

        prio = prep.priorite_max(recommandations)
        verdict_key = prep.verdict_key(prio)
        verdict_lbl = prep.verdict_label(prio, cfg)
        banner = prep.verdict_banner(verdict_key, cfg)
        bullets = prep.verdict_bullets(
            specialist_results, recommandations, intent, s3_output
        )

        synthese_s5 = prep.sanitize_text(str(s5_output.get("synthese", "") or ""))
        synthese_s6 = prep.sanitize_text(str(s6_output.get("synthese_action", "") or ""))
        if client_mode:
            synthese_s5 = prep.strip_client_synthesis(synthese_s5, min_cpk_val)
            synthese_s6 = prep.strip_client_synthesis(synthese_s6, min_cpk_val)
            synthese_s5 = prep.sanitize_client_visible(synthese_s5)
            synthese_s6 = prep.sanitize_client_visible(synthese_s6)
        synthese_s5 = prep.apply_profile_text(synthese_s5, profile, forbidden)
        synthese_s6 = prep.apply_profile_text(synthese_s6, profile, forbidden)

        metric_tables = prep.build_metric_tables(
            s4_output,
            specialist_results,
            profile,
            forbidden,
            client_mode=client_mode,
        )
        if client_mode:
            metric_tables = prep.annotate_cpk_table_colors(metric_tables, cfg)

        graphs_raw = list(s4_output.get("graphs", s4_output.get("charts", [])) or [])
        if client_mode:
            graphs_raw = prep.filter_priority_graphs(graphs_raw, cfg)
        else:
            max_g = prep.max_graphiques(profile, cfg)
            graphs_raw = graphs_raw[:max_g]

        chart_items: list[dict] = []
        for g in graphs_raw:
            if not isinstance(g, dict):
                continue
            png = g.get("png_bytes")
            if png is None and g.get("error"):
                continue
            cap = prep.sanitize_text(str(g.get("description", "")))
            if client_mode:
                cap = prep.sanitize_client_visible(cap)
            chart_items.append(
                {
                    "title": prep.sanitize_text(str(g.get("title", g.get("type", "Graphique")))),
                    "caption": prep.apply_profile_text(cap, profile, forbidden),
                    "png_bytes": png if isinstance(png, (bytes, bytearray)) else None,
                    "error": g.get("error"),
                }
            )

        raw_interps: list[dict] = []
        for it in s5_output.get("interpretations") or []:
            if not isinstance(it, dict) or prep.is_graph_only_interpretation(it):
                continue
            text = prep.prepare_interpretation_text(
                it, specialist_results, profile, forbidden
            )
            if client_mode:
                text = prep.sanitize_client_visible(text)
            if not prep.is_meaningful_text(text):
                continue
            raw_interps.append({**it, "text": text})

        cpk_synthesis = ""
        dunn_annexe: list[dict] = []
        interp_items: list[dict] = []
        seen_interp: set[tuple[str, str]] = set()

        if client_mode:
            cpk_synthesis = prep.aggregate_cpk_interpretations(raw_interps)
            for it in raw_interps:
                spec = str(it.get("specialist", "")).lower()
                if spec == "cp_cpk":
                    continue
                if spec == "dunn_posthoc":
                    dunn_annexe.append(
                        {
                            "label": prep.specialist_client_label(spec),
                            "text": it.get("text", ""),
                        }
                    )
                    continue
                label = prep.specialist_client_label(spec)
                key = (label, str(it.get("text", ""))[:120])
                if key in seen_interp:
                    continue
                seen_interp.add(key)
                interp_items.append(
                    {
                        "specialist": label,
                        "text": it.get("text", ""),
                        "statut": str(it.get("statut", "accept")),
                        "badge": "",
                    }
                )
            if cpk_synthesis and not any(
                "capabilit" in str(i.get("specialist", "")).lower() for i in interp_items
            ):
                interp_items.insert(
                    0,
                    {
                        "specialist": "Capabilité processus",
                        "text": cpk_synthesis,
                        "statut": "accept",
                        "badge": "",
                    },
                )
        else:
            for it in raw_interps:
                spec = prep.sanitize_text(str(it.get("specialist", "analyse")))
                text = str(it.get("text", ""))
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
                        "badge": prep.interpretation_badge(statut, client_mode=False),
                    }
                )

        reco_rows: list[dict] = []
        for rec in sorted(
            recommandations,
            key=lambda r: prep.priority_rank(str(r.get("priorite", "P4"))),
        ):
            action = prep.sanitize_text(str(rec.get("action", "")))
            if client_mode:
                action = prep.sanitize_client_visible(action)
            reco_rows.append(
                {
                    "priorite": str(rec.get("priorite", "P4")).upper(),
                    "action": prep.apply_profile_text(action, profile, forbidden),
                    "responsable": prep.sanitize_text(str(rec.get("responsable", ""))),
                    "delai": prep.sanitize_text(str(rec.get("delai", ""))),
                    "justification": prep.apply_profile_text(
                        prep.sanitize_client_visible(
                            prep.sanitize_text(str(rec.get("justification", "")))
                        )
                        if client_mode
                        else prep.sanitize_text(str(rec.get("justification", ""))),
                        profile,
                        forbidden,
                    ),
                }
            )

        warning_count = len(s5_output.get("warnings") or []) + len(
            s6_output.get("warnings") or []
        )
        operateur = ""
        filtres = intent.get("filtres") or {}
        if isinstance(filtres, dict):
            operateur = str(
                filtres.get("operateur")
                or filtres.get("operator")
                or intent.get("operateur")
                or ""
            )

        meta = {
            "timestamp": ts,
            "profile": profile,
            "question": question_originale,
            "bandeau_couleur": str(cfg.get("bandeau_defaut_couleur", "#1565C0")),
            "client": prep.client_display_name(context),
            "piece": str(intent.get("piece") or ""),
            "operation": str(intent.get("operation") or ""),
            "operateur": operateur,
            "reference": prep.report_reference(ts, cfg),
            "verdict": verdict_lbl,
            "verdict_key": verdict_key,
            "priorite_max": prio,
            "client_mode": client_mode,
            "fidelite_score": float(s5_output.get("fidelite_score", 0.0) or 0.0),
            "industria_version": str(cfg.get("industria_version", "v4.0")),
            "nb_recommandations": len(reco_rows),
            "nb_graphiques": len(chart_items),
            "warning_count": warning_count if not client_mode else 0,
            "specialists_executed": [
                str(r.get("agent", ""))
                for r in specialist_results
                if r.get("status") == "success"
            ],
        }

        exec_paragraphs = [p for p in (synthese_s5, synthese_s6) if p]
        if client_mode and cpk_synthesis and cpk_synthesis not in synthese_s5:
            exec_paragraphs.insert(1, cpk_synthesis)

        blocks: list[ReportBlock] = [
            ReportBlock("cover", {"meta": meta}),
            ReportBlock(
                "verdict",
                {
                    "label": verdict_lbl,
                    "priorite_max": prio,
                    "verdict_key": verdict_key,
                    "banner": banner,
                    "bullets": bullets,
                    "client_mode": client_mode,
                },
            ),
            ReportBlock(
                "executive",
                {
                    "paragraphs": exec_paragraphs,
                    "synthese_s5": synthese_s5,
                    "synthese_s6": synthese_s6,
                    "cpk_synthesis": cpk_synthesis if client_mode else "",
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
                    "reference": meta["reference"],
                    "fidelite_score": meta["fidelite_score"],
                    "industria_version": meta["industria_version"],
                    "warning_count": warning_count,
                    "client_mode": client_mode,
                },
            ),
        ]
        if client_mode and dunn_annexe:
            blocks.append(ReportBlock("annexe_dunn", {"items": dunn_annexe}))
        elif not client_mode:
            blocks.append(
                ReportBlock(
                    "annexe_warnings",
                    {"count": warning_count, "specialists": meta["specialists_executed"]},
                )
            )

        document = ReportDocument(meta=meta, blocks=blocks)
        return {"document": document, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"document": None, "error": str(exc)}
