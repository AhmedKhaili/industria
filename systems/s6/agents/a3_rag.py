"""
A3 — Enrichissement procédures via RagPort (Python pur côté recherche).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.s6.rag_port import StubRagPort

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext
    from systems.s6.rag_port import RagPort


def run(
    items: list[dict],
    context: "ClientContext",
    rag_port: "RagPort | None" = None,
) -> dict:
    try:
        port = rag_port or StubRagPort()
        cfg = context.get_recommandations()
        rag_cfg = cfg.get("rag", {}) if isinstance(cfg, dict) else {}
        min_rel = float(rag_cfg.get("min_relevance", 0.7))
        empty_msg = str(
            rag_cfg.get(
                "message_vide",
                "Aucune procédure locale trouvée. Contacter l'ingénieur procédé.",
            )
        )

        warnings: list[str] = []
        any_rag = False

        for item in items:
            query = f"{item.get('action_type')} {item.get('cause_label')} {item.get('justification')}"
            res = port.search(query, min_relevance=min_rel)
            results = res.get("results") or []
            n = int(res.get("n_found", 0) or 0)
            if results and n > 0:
                top = results[0] if isinstance(results[0], dict) else {}
                text = str(top.get("text", "")).strip()
                if text:
                    item["rag_excerpt"] = text[:500]
                    item["rag_used"] = True
                    any_rag = True
                    continue
            item["rag_excerpt"] = ""
            item["rag_used"] = False
            if item.get("priorite") in ("P1", "P2"):
                warnings.append(empty_msg)

        return {"error": None, "items": items, "rag_used": any_rag, "warnings": warnings}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "items": items, "rag_used": False, "warnings": []}
